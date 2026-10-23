//! A single non-retried copy, followed by durable completion or compensation.
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

pub enum Outcome {
    Completed(Receipt),
    Compensated,
    Blocked(chrono::DateTime<Utc>),
    InProgress(i32),
    Recovery(i32, Option<Receipt>),
}
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
