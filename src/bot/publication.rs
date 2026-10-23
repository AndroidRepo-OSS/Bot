//! Single-attempt Telegram copy coordinated with durable SQLite recovery.
//!
//! [`publish`] commits a reservation before delivery and retains receipt handling
//! through completion or compensation. Ambiguous delivery never causes an automatic
//! recopy. Database transitions live in [`crate::db`], without network effects.

use super::{App, DraftSession, ui};
use crate::{
    db::{self, Delivery, Receipt, Reservation},
    error::{Error, Result},
};
use chrono::Utc;
use std::time::Duration;
use teloxide::{
    ApiError, RequestError,
    prelude::*,
    types::{ChatId, MessageId},
};

/// Delivery result presented to staff after reservation and any recovery work.
pub enum Outcome {
    /// Durably completed publication with the stored receipt.
    Completed(Receipt),
    /// Channel deletion was confirmed and the operation released.
    Compensated,
    /// Repository cooldown expiry prevented copying.
    Blocked(chrono::DateTime<Utc>),
    /// Another live copy operation owns delivery.
    InProgress(i32),
    /// Unresolved operation ID and optional known receipt; staff must inspect/reconcile.
    Recovery(i32, Option<Receipt>),
}
/// Reserve durably, attempt one channel copy, then persist or compensate.
///
/// Requires the draft owner. A committed `copying` operation precedes the only copy,
/// which has a 60-second timeout and no automatic retry. Ambiguous delivery blocks
/// until reconciliation. After a receipt, failed persistence attempts durable
/// compensation before deletion; unconfirmed deletion is treated conservatively.
///
/// # Cancellation
///
/// The draining dispatcher must retain this future through completion, including
/// receipt persistence and compensation. Do not race the whole future against a
/// shutdown timeout; forced process termination leaves recovery state in SQLite.
///
/// # Errors
///
/// Returns [`Error::Invalid`] for a different actor, sanitized database errors
/// when reservation fails, or [`Error::Telegram`] after a definitive copy rejection
/// has been stored. Unresolved effects are returned as [`Outcome::Recovery`].
pub async fn publish(
    app: &App,
    session: &DraftSession,
    chat: ChatId,
    actor: UserId,
) -> Result<Outcome> {
    if actor != session.owner {
        return Err(Error::Invalid("Only the owner can publish this draft."));
    }
    let reservation = db::reserve(
        &app.pool,
        db::Intent {
            repository_id: session.repository_id,
            reference: &session.repository.reference,
            draft: &session.draft,
            actor: actor.0 as i64,
            source_chat: chat.0,
            source_message: session.message.0,
            channel: app.config.channel,
        },
    )
    .await?;
    let id = match reservation {
        Reservation::Reserved(id) => id,
        Reservation::Blocked(until) => return Ok(Outcome::Blocked(until)),
        Reservation::InProgress(id) => return Ok(Outcome::InProgress(id)),
        Reservation::Recovery(id) => return Ok(Outcome::Recovery(id, None)),
    };
    // Dispatcher drains this future on shutdown; never select/cancel around the
    // whole workflow. A killed process leaves the committed reservation blocking.
    let copied = tokio::time::timeout(
        Duration::from_secs(60),
        app.bot
            .copy_message(ChatId(app.config.channel), chat, session.message)
            .reply_markup(ui::published(&session.draft))
            .send(),
    )
    .await;
    let message = match copied {
        Ok(Ok(message)) => message,
        error => {
            let definitive = matches!(&error, Ok(Err(RequestError::Api(api))) if !matches!(api, ApiError::Unknown(_)))
                || matches!(
                    &error,
                    Ok(Err(
                        RequestError::RetryAfter(_) | RequestError::MigrateToChatId(_)
                    ))
                );
            let saved = db::mark_delivery(
                &app.pool,
                id,
                if definitive {
                    Delivery::Rejected
                } else {
                    Delivery::Uncertain
                },
            )
            .await;
            if definitive && saved.is_ok() {
                return Err(Error::Telegram);
            }
            return Ok(Outcome::Recovery(id, None));
        }
    };
    let receipt = Receipt {
        operation: id,
        channel: app.config.channel,
        message: message.0,
        published_at: Utc::now(),
    };
    if let Ok(stored) = db::complete(&app.pool, receipt, false).await {
        return Ok(Outcome::Completed(stored));
    }
    tracing::warn!(
        operation = id,
        channel_message = receipt.message,
        "Receipt persistence failed; preparing compensation"
    );
    match db::begin_compensation(&app.pool, receipt).await {
        Err(_) => return Ok(Outcome::Recovery(id, Some(receipt))),
        Ok(false) => return recover_visible(app, receipt).await,
        Ok(true) => {}
    }
    let deletion = tokio::time::timeout(
        Duration::from_secs(60),
        app.bot
            .delete_message(ChatId(receipt.channel), MessageId(receipt.message))
            .send(),
    )
    .await;
    if matches!(deletion, Ok(Ok(_))) {
        if db::finish_compensation(&app.pool, id).await.is_ok() {
            return Ok(Outcome::Compensated);
        }
        return Ok(Outcome::Recovery(id, Some(receipt)));
    }
    // A failed/ambiguous deletion is conservatively treated as a visible post.
    recover_visible(app, receipt).await
}
/// Retry receipt persistence up to three times after an unconfirmed deletion.
///
/// Retries only database completion, never channel delivery or deletion. Returns a
/// recovery outcome with the known receipt if durable completion remains unavailable.
///
/// # Errors
///
/// This implementation converts all persistence failures to [`Outcome::Recovery`];
/// the result signature matches the surrounding publication workflow.
async fn recover_visible(app: &App, receipt: Receipt) -> Result<Outcome> {
    for attempt in 0..3 {
        if let Ok(stored) = db::complete(&app.pool, receipt, false).await {
            return Ok(Outcome::Completed(stored));
        }
        if attempt < 2 {
            tokio::time::sleep(Duration::from_millis(200 << attempt)).await;
        }
    }
    Ok(Outcome::Recovery(receipt.operation, Some(receipt)))
}
