//! The database/Telegram boundary is not atomic. Expired leases never allow recopying.
use crate::{
    error::{Error, Result},
    generation::Draft,
    repositories::RepositoryRef,
};
use chrono::{DateTime, Months, Utc};
use sqlx::{FromRow, Sqlite, SqlitePool, Transaction, types::Json};

type Tx<'a> = Transaction<'a, Sqlite>;

pub struct Intent<'a> {
    pub repository_id: i32,
    pub reference: &'a RepositoryRef,
    pub draft: &'a Draft,
    pub actor: i64,
    pub source_chat: i64,
    pub source_message: i32,
    pub channel: i64,
}
#[derive(Debug)]
pub enum Reservation {
    Reserved(i32),
    Blocked(DateTime<Utc>),
    InProgress(i32),
    Recovery(i32),
}
#[derive(Clone, Copy, Debug)]
pub struct Receipt {
    pub operation: i32,
    pub channel: i64,
    pub message: i32,
    pub published_at: DateTime<Utc>,
}
pub enum Delivery {
    Uncertain,
    Rejected,
}
#[derive(FromRow)]
struct Operation {
    id: i32,
    repository_app_id: i32,
    channel_id: i64,
    actor_user_id: i64,
    title: String,
    tags: Json<Vec<String>>,
    status: String,
    lease_expires_at: Option<DateTime<Utc>>,
    channel_message_id: Option<i64>,
    published_at: Option<DateTime<Utc>>,
}
async fn now(tx: &mut Tx<'_>) -> Result<DateTime<Utc>> {
    Ok(
        sqlx::query_scalar("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')")
            .fetch_one(&mut **tx)
            .await?,
    )
}
async fn operation(tx: &mut Tx<'_>, id: i32) -> Result<Operation> {
    // BEGIN IMMEDIATE has already acquired SQLite's writer lock, before any reads.
    sqlx::query_as("SELECT * FROM publication_operations WHERE id=?1")
        .bind(id)
        .fetch_optional(&mut **tx)
        .await?
        .ok_or(Error::Invalid("Publication operation does not exist."))
}

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
    for date in dates {
        let until = date
            .checked_add_months(Months::new(3))
            .ok_or(Error::Database)?;
        if until > current {
            return Ok(Some(until));
        }
    }
    Ok(None)
}

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
fn receipt_matches(op: &Operation, message: i32) -> Result<DateTime<Utc>> {
    if op.channel_message_id != Some(i64::from(message)) {
        return Err(Error::Invalid(
            "Operation already has a different channel receipt.",
        ));
    }
    op.published_at
        .ok_or(Error::Invalid("Operation has no publication timestamp."))
}
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
/// Store both the receipt and completed operation atomically, or reconcile after inspection.
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
