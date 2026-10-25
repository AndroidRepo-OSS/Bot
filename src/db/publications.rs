//! Durable publication state across the non-atomic SQLite/Telegram boundary.
//!
//! Every write transaction acquires `BEGIN IMMEDIATE` before reads and samples the
//! database clock after lock waits. [`reserve`] commits one open operation before
//! Telegram delivery; unique open-operation and channel-receipt constraints support
//! serialized decisions. A two-minute lease is ownership, never a retry timer.
//!
//! # Transitions
//!
//! | Current state | Event | Result |
//! | --- | --- | --- |
//! | No open operation | Eligible [`reserve`] | `copying`, live lease |
//! | `copying` | Definitive rejection via [`mark_delivery`] | `failed`, released |
//! | `copying` | Ambiguous delivery or observed expiry | `uncertain`, blocked |
//! | `copying` | Receipt stored by [`complete`] | `completed`, cooldown |
//! | `copying` | [`begin_compensation`] before deletion | `compensating`, receipt/lease |
//! | `compensating` | Confirmed deletion and [`finish_compensation`] | `abandoned`, released |
//! | `compensating` | Matching receipt stored conservatively | `completed`, cooldown |
//! | Unresolved, no live lease | Staff confirms visible message via [`complete`] | `completed` |
//! | Unresolved, no live lease | Staff confirms absence via [`reconcile_absent`] | `abandoned` |
//!
//! A failed database operation is never evidence of absent Telegram delivery. Staff
//! must inspect the channel before reconciliation. Completion preserves existing
//! receipt identity and timestamps. Cooldown uses three UTC calendar months with
//! month-end clamping; it is checked again inside the reservation transaction.

use crate::{
    error::{Error, Result},
    generation::Draft,
    repositories::RepositoryRef,
};
use chrono::{DateTime, Months, Utc};
use sqlx::{FromRow, Sqlite, SqlitePool, Transaction, types::Json};

/// SQLite write transaction; callers acquire the writer lock before state reads.
type Tx<'a> = Transaction<'a, Sqlite>;

/// Borrowed draft and numeric Telegram context to persist before a channel copy.
pub struct Intent<'a> {
    /// Registered repository whose open operation and cooldown will be checked.
    pub repository_id: i32,
    /// Observed repository path recorded for cooldown refusals.
    pub reference: &'a RepositoryRef,
    /// Validated title and tags captured in the reservation.
    pub draft: &'a Draft,
    /// Numeric ID of the staff user requesting publication.
    pub actor: i64,
    /// Staff chat holding the draft photo.
    pub source_chat: i64,
    /// Draft photo to copy exactly once.
    pub source_message: i32,
    /// Destination channel to bind to the durable operation.
    pub channel: i64,
}
/// Decision committed by [`reserve`] before any channel delivery effect.
#[derive(Debug)]
pub enum Reservation {
    /// New committed operation ID; the caller may attempt exactly one copy.
    Reserved(i32),
    /// Active cooldown expiry; no copy is authorized.
    Blocked(DateTime<Utc>),
    /// Existing live copy operation ID; no new copy is authorized.
    InProgress(i32),
    /// Existing unresolved operation ID requiring reconciliation, never recopying.
    Recovery(i32),
}
/// Observed channel message associated with one durable operation.
///
/// Online publication records local UTC time after receiving the Telegram receipt;
/// manual reconciliation supplies the visible message’s actual timestamp.
#[derive(Clone, Copy, Debug)]
pub struct Receipt {
    /// Durable publication operation ID.
    pub operation: i32,
    /// Channel in which the copy was observed.
    pub channel: i64,
    /// Observed channel message ID.
    pub message: i32,
    /// UTC publication time used as the cooldown origin.
    pub published_at: DateTime<Utc>,
}
/// Classification of a failed copy attempt for [`mark_delivery`].
pub enum Delivery {
    /// Delivery may have occurred; retain a blocking operation.
    Uncertain,
    /// Definitive rejection; mark failed and release the reservation.
    Rejected,
}
/// Persisted operation row read only after acquiring SQLite’s writer lock.
#[derive(FromRow)]
struct Operation {
    /// Durable operation primary key.
    id: i32,
    /// Stable local repository identity.
    repository_app_id: i32,
    /// Destination channel bound at reservation.
    channel_id: i64,
    /// Staff user recorded at reservation.
    actor_user_id: i64,
    /// Validated title captured before delivery.
    title: String,
    /// Validated category list stored as a JSON array.
    tags: Json<Vec<String>>,
    /// Persisted copying/uncertain/compensating/completed/failed/abandoned phase.
    status: String,
    /// Optional ownership deadline; expiration never authorizes a recopy.
    lease_expires_at: Option<DateTime<Utc>>,
    /// Receipt retained after delivery or before compensation.
    channel_message_id: Option<i64>,
    /// Receipt timestamp retained for idempotent completion.
    published_at: Option<DateTime<Utc>>,
}
/// Read the database UTC clock after the transaction has acquired its writer lock.
///
/// # Errors
///
/// Returns [`Error::Database`] if the query or timestamp decoding fails.
async fn now(tx: &mut Tx<'_>) -> Result<DateTime<Utc>> {
    Ok(
        sqlx::query_scalar("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')")
            .fetch_one(&mut **tx)
            .await?,
    )
}
/// Read a publication operation while holding the write transaction.
///
/// # Errors
///
/// Returns [`Error::Invalid`] for an unknown ID, or [`Error::Database`] on query failure.
async fn operation(tx: &mut Tx<'_>, id: i32) -> Result<Operation> {
    // BEGIN IMMEDIATE has already acquired SQLite's writer lock, before any reads.
    sqlx::query_as("SELECT * FROM publication_operations WHERE id=?1")
        .bind(id)
        .fetch_optional(&mut **tx)
        .await?
        .ok_or(Error::Invalid("Publication operation does not exist."))
}

/// Find an active three-calendar-month UTC cooldown for the repository.
///
/// Calendar addition clamps month ends. Earlier publications are checked too because
/// clamping can put their expiration after that of a later publication.
///
/// # Errors
///
/// Returns [`Error::Database`] on query, timestamp decoding or calendar overflow failures.
async fn cooldown(tx: &mut Tx<'_>, repository: i32) -> Result<Option<DateTime<Utc>>> {
    let current = now(tx).await?;
    let dates: Vec<DateTime<Utc>> = sqlx::query_scalar(
        "SELECT published_at FROM published_posts WHERE repository_app_id=?1
         AND julianday(published_at) >= julianday(?2, 'start of month', '-3 months')
         ORDER BY julianday(published_at) DESC, published_at DESC",
    )
    .bind(repository)
    .bind(current)
    .fetch_all(&mut **tx)
    .await?;
    // Calendar addition clamps to the last valid day, matching PostgreSQL's UTC cooldown.
    // Check earlier posts too: month-end clamping can put their expiry after a later post's.
    let mut latest = None;
    for date in dates {
        let until = date
            .checked_add_months(Months::new(3))
            .ok_or(Error::Database)?;
        if until > current {
            latest = Some(latest.map_or(until, |previous: DateTime<Utc>| previous.max(until)));
        }
    }
    Ok(latest)
}

/// Record a cooldown refusal in the caller’s transaction.
///
/// # Errors
///
/// Returns [`Error::Database`] if the attempt cannot be inserted.
async fn blocked_attempt(
    tx: &mut Tx<'_>,
    repository: i32,
    reference: &RepositoryRef,
    actor: i64,
    until: DateTime<Utc>,
) -> Result<()> {
    sqlx::query("INSERT INTO post_attempts (repository_app_id,provider,namespace,name,url,requested_by_user_id,attempted_at,status,blocked_until,reason)
        VALUES (?1,?2,?3,?4,?5,?6,strftime('%Y-%m-%dT%H:%M:%fZ','now'),'blocked',?7,'cooldown')").bind(repository).bind(reference.provider.name())
        .bind(&reference.namespace).bind(&reference.name).bind(reference.url()).bind(actor).bind(until).execute(&mut **tx).await?;
    Ok(())
}
/// Check cooldown before draft generation and persist a blocked attempt if needed.
///
/// Returns its expiry or `None`. This is advisory for draft preparation; [`reserve`]
/// checks cooldown and open operations again immediately before delivery.
///
/// # Errors
///
/// Returns [`Error::Database`] if the serialized transaction or timestamp handling fails.
pub async fn eligibility(
    pool: &SqlitePool,
    repository: i32,
    reference: &RepositoryRef,
    actor: i64,
) -> Result<Option<DateTime<Utc>>> {
    let mut tx = pool.begin_with("BEGIN IMMEDIATE").await?;
    let until = cooldown(&mut tx, repository).await?;
    if let Some(until) = until {
        blocked_attempt(&mut tx, repository, reference, actor, until).await?;
    }
    tx.commit().await?;
    Ok(until)
}
/// Commit a copy reservation or return the existing blocking condition.
///
/// Acquires `BEGIN IMMEDIATE` before reads. A new `copying` operation receives a
/// two-minute lease; only [`Reservation::Reserved`] permits a copy. Expired copies
/// become `uncertain`; compensating/uncertain operations require recovery. Lease
/// expiry never grants permission to recopy. Cooldown refusals record an attempt.
///
/// # Errors
///
/// Returns [`Error::Database`] for transaction, constraint, serialization or clock failures.
pub async fn reserve(pool: &SqlitePool, intent: Intent<'_>) -> Result<Reservation> {
    let mut tx = pool.begin_with("BEGIN IMMEDIATE").await?;
    let current = now(&mut tx).await?;
    let open: Option<Operation> = sqlx::query_as("SELECT * FROM publication_operations WHERE repository_app_id=?1 AND status IN ('copying','compensating','uncertain')")
        .bind(intent.repository_id).fetch_optional(&mut *tx).await?;
    let result = if let Some(open) = open {
        if open.status == "copying" && open.lease_expires_at.is_some_and(|lease| lease > current) {
            Reservation::InProgress(open.id)
        } else {
            if open.status == "copying" {
                sqlx::query("UPDATE publication_operations SET status='uncertain',lease_expires_at=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?1").bind(open.id).execute(&mut *tx).await?;
            }
            Reservation::Recovery(open.id)
        }
    } else if let Some(until) = cooldown(&mut tx, intent.repository_id).await? {
        blocked_attempt(
            &mut tx,
            intent.repository_id,
            intent.reference,
            intent.actor,
            until,
        )
        .await?;
        Reservation::Blocked(until)
    } else {
        let id = sqlx::query_scalar("INSERT INTO publication_operations (repository_app_id,source_chat_id,source_message_id,channel_id,actor_user_id,title,tags,status,lease_expires_at,created_at,updated_at)
            VALUES (?1,?2,?3,?4,?5,?6,?7,'copying',strftime('%Y-%m-%dT%H:%M:%fZ','now','+2 minutes'),strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now')) RETURNING id")
            .bind(intent.repository_id).bind(intent.source_chat).bind(i64::from(intent.source_message)).bind(intent.channel).bind(intent.actor)
            .bind(&intent.draft.title).bind(Json(&intent.draft.tags)).fetch_one(&mut *tx).await?;
        Reservation::Reserved(id)
    };
    tx.commit().await?;
    Ok(result)
}
/// Require the stored channel message ID and return its original publication time.
///
/// # Errors
///
/// Returns [`Error::Invalid`] for a different message ID or missing timestamp.
fn receipt_matches(op: &Operation, message: i32) -> Result<DateTime<Utc>> {
    if op.channel_message_id != Some(i64::from(message)) {
        return Err(Error::Invalid(
            "Operation already has a different channel receipt.",
        ));
    }
    op.published_at
        .ok_or(Error::Invalid("Operation has no publication timestamp."))
}
/// Require a live copy lease or an already completed/compensating operation.
///
/// # Errors
///
/// Returns [`Error::Invalid`] when the operation no longer owns a live copy;
/// propagates database clock failures.
async fn require_active(tx: &mut Tx<'_>, op: &Operation) -> Result<()> {
    if matches!(op.status.as_str(), "completed" | "compensating") {
        return Ok(());
    }
    if op.status != "copying" || op.lease_expires_at.is_none() {
        return Err(Error::Invalid("Publication no longer owns the operation."));
    }
    let current = now(tx).await?;
    if op.lease_expires_at.is_none_or(|lease| lease <= current) {
        return Err(Error::Invalid(
            "Publication lease expired; reconcile the channel.",
        ));
    }
    Ok(())
}
/// Prevent staff reconciliation while a copy or compensation lease is live.
///
/// # Errors
///
/// Returns [`Error::Invalid`] for a live lease or [`Error::Database`] on clock failure.
async fn require_reconcilable(tx: &mut Tx<'_>, op: &Operation) -> Result<()> {
    if matches!(op.status.as_str(), "copying" | "compensating") {
        let current = now(tx).await?;
        if op.lease_expires_at.is_some_and(|lease| lease > current) {
            return Err(Error::Invalid(
                "Publication is still in progress. Wait for its lease to expire.",
            ));
        }
    }
    Ok(())
}
/// Atomically store a publication, receipt and completed operation.
///
/// `reconciliation = false` requires active ownership or an existing completed/
/// compensating operation. `true` follows staff channel inspection and refuses live
/// copy/compensation leases. Channel and receipt identity must match; repeated
/// completion preserves the stored timestamp. No Telegram effect occurs here.
///
/// # Errors
///
/// Returns [`Error::Invalid`] for unknown operations, mismatched channels/receipts,
/// lost leases or incompatible states; [`Error::Database`] for persistence failures.
/// A failed transaction does not authorize another copy.
pub async fn complete(
    pool: &SqlitePool,
    receipt: Receipt,
    reconciliation: bool,
) -> Result<Receipt> {
    let mut tx = pool.begin_with("BEGIN IMMEDIATE").await?;
    let op = operation(&mut tx, receipt.operation).await?;
    if receipt.channel != op.channel_id {
        return Err(Error::Invalid("Operation belongs to another channel."));
    }
    if reconciliation {
        require_reconcilable(&mut tx, &op).await?;
    } else {
        require_active(&mut tx, &op).await?;
    }
    if !matches!(
        op.status.as_str(),
        "copying" | "uncertain" | "compensating" | "completed"
    ) {
        return Err(Error::Invalid(
            "Operation cannot be completed in its current state.",
        ));
    }
    let published_at = if matches!(op.status.as_str(), "compensating" | "completed") {
        receipt_matches(&op, receipt.message)?
    } else {
        receipt.published_at
    };
    if op.status != "completed" {
        let publication: Option<i32> = sqlx::query_scalar("INSERT INTO published_posts (repository_app_id,title,tags,created_by_user_id,channel_id,channel_message_id,published_at)
            VALUES (?1,?2,?3,?4,?5,?6,?7) ON CONFLICT (channel_id,channel_message_id) DO NOTHING RETURNING id")
            .bind(op.repository_app_id).bind(&op.title).bind(&op.tags).bind(op.actor_user_id).bind(op.channel_id).bind(i64::from(receipt.message)).bind(published_at).fetch_optional(&mut *tx).await?;
        let publication = match publication {
            Some(id) => id,
            None => {
                let (id, repository): (i32, i32) = sqlx::query_as("SELECT id,repository_app_id FROM published_posts WHERE channel_id=?1 AND channel_message_id=?2")
                    .bind(op.channel_id).bind(i64::from(receipt.message)).fetch_one(&mut *tx).await?;
                if repository != op.repository_app_id {
                    return Err(Error::Invalid(
                        "Channel receipt belongs to another repository.",
                    ));
                }
                id
            }
        };
        sqlx::query("UPDATE publication_operations SET status='completed',lease_expires_at=NULL,channel_message_id=?2,published_at=?3,published_post_id=?4,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?1")
            .bind(op.id).bind(i64::from(receipt.message)).bind(published_at).bind(publication).execute(&mut *tx).await?;
    }
    tx.commit().await?;
    Ok(Receipt {
        published_at,
        ..receipt
    })
}
/// Persist the receipt and a two-minute compensation lease before deletion.
///
/// Returns `true` for pending compensation (including a matching repeated call),
/// or `false` when already completed. The caller must await this commit before
/// issuing a Telegram delete request.
///
/// # Errors
///
/// Returns [`Error::Invalid`] for mismatched identity or lost copy ownership,
/// or [`Error::Database`] if the compensation transaction fails.
pub async fn begin_compensation(pool: &SqlitePool, receipt: Receipt) -> Result<bool> {
    let mut tx = pool.begin_with("BEGIN IMMEDIATE").await?;
    let op = operation(&mut tx, receipt.operation).await?;
    if receipt.channel != op.channel_id {
        return Err(Error::Invalid("Operation belongs to another channel."));
    }
    if matches!(op.status.as_str(), "completed" | "compensating") {
        receipt_matches(&op, receipt.message)?;
        return Ok(op.status == "compensating");
    }
    require_active(&mut tx, &op).await?;
    sqlx::query("UPDATE publication_operations SET status='compensating',lease_expires_at=strftime('%Y-%m-%dT%H:%M:%fZ','now','+2 minutes'),channel_message_id=?2,published_at=?3,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?1")
        .bind(op.id).bind(i64::from(receipt.message)).bind(receipt.published_at).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(true)
}
/// Release a compensating operation only after confirmed channel deletion.
///
/// Transitions to `abandoned`; repeating an already abandoned operation is accepted.
/// This function trusts the caller’s deletion confirmation and performs no network I/O.
///
/// # Errors
///
/// Returns [`Error::Invalid`] outside compensating/abandoned states or for unknown
/// operations; [`Error::Database`] for transaction failures.
pub async fn finish_compensation(pool: &SqlitePool, id: i32) -> Result<()> {
    let mut tx = pool.begin_with("BEGIN IMMEDIATE").await?;
    let op = operation(&mut tx, id).await?;
    if !matches!(op.status.as_str(), "compensating" | "abandoned") {
        return Err(Error::Invalid("Operation has no pending compensation."));
    }
    sqlx::query("UPDATE publication_operations SET status='abandoned',lease_expires_at=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?1").bind(id).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(())
}
/// Store a failed copy as uncertain or definitively rejected and clear its lease.
///
/// Uncertain delivery remains blocking; definitive rejection becomes `failed`.
/// Repeating the same classification is accepted, but changing it is rejected.
///
/// # Errors
///
/// Returns [`Error::Invalid`] for an incompatible operation state or unknown ID,
/// or [`Error::Database`] for transaction failures.
pub async fn mark_delivery(pool: &SqlitePool, id: i32, delivery: Delivery) -> Result<()> {
    let mut tx = pool.begin_with("BEGIN IMMEDIATE").await?;
    let op = operation(&mut tx, id).await?;
    let status = match delivery {
        Delivery::Uncertain => "uncertain",
        Delivery::Rejected => "failed",
    };
    if op.status != "copying" && op.status != status {
        return Err(Error::Invalid(
            "Operation already has another delivery state.",
        ));
    }
    sqlx::query("UPDATE publication_operations SET status=?2,lease_expires_at=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?1").bind(id).bind(status).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(())
}
/// Close an operation after staff confirm no channel publication is visible.
///
/// Checks the configured channel and refuses live copy/compensation leases or
/// completed publications. Failed/abandoned operations are already closed.
/// Trusts staff inspection and never performs another channel copy.
///
/// # Errors
///
/// Returns [`Error::Invalid`] for unknown IDs, wrong channels, live leases or
/// completed operations; [`Error::Database`] for transaction failures.
pub async fn reconcile_absent(pool: &SqlitePool, id: i32, channel: i64) -> Result<()> {
    let mut tx = pool.begin_with("BEGIN IMMEDIATE").await?;
    let op = operation(&mut tx, id).await?;
    if op.channel_id != channel {
        return Err(Error::Invalid("Operation belongs to another channel."));
    }
    require_reconcilable(&mut tx, &op).await?;
    if op.status == "completed" {
        return Err(Error::Invalid(
            "A completed publication cannot be reconciled as absent.",
        ));
    }
    if !matches!(op.status.as_str(), "failed" | "abandoned") {
        sqlx::query("UPDATE publication_operations SET status='abandoned',lease_expires_at=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?1").bind(id).execute(&mut *tx).await?;
    }
    tx.commit().await?;
    Ok(())
}
