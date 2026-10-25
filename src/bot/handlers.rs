//! Typed commands, staff admission and owner-bound callback transitions.
//!
//! Only `/start` bypasses staff chat/topic checks. Callback admission checks owner,
//! active message and phase together. Handlers delegate evidence/rendering to draft
//! preparation and durable channel effects to [`super::publication`].

use super::{
    App, DraftSession, State,
    drafts::{create, deactivate, revise},
    publication::{self, Outcome},
    ui::{self, Action},
};
use crate::{
    db,
    error::{Error, Result},
    repositories::RepositoryRef,
};
use chrono::{DateTime, Utc};
use std::sync::Arc;
use teloxide::{prelude::*, utils::command::BotCommands};

/// Typed Telegram commands; only [`Self::Start`] bypasses staff/topic admission.
#[derive(BotCommands, Clone)]
#[command(rename_rule = "lowercase")]
pub enum Command {
    /// Public introduction; no staff/topic authorization required.
    Start,
    /// Prepare a draft from the supplied repository-root URL.
    Post(String),
    /// Deactivate and best-effort delete the caller’s active draft.
    Cancel,
    /// Resolve an uncertain operation after staff inspect the channel.
    Reconcile(String),
}

/// Dispatch typed commands after enforcing staff chat/topic and user identity.
///
/// `/start` is public. An invalid `/post` URL preserves current state; a valid new
/// request deactivates previous controls before attempting preparation.
///
/// # Errors
///
/// Returns sanitized Telegram errors when a response cannot be delivered.
/// Workflow failures are otherwise passed to [`report`] for staff-safe reporting.
pub async fn command(app: Arc<App>, message: Message, command: Command) -> Result<()> {
    if matches!(command, Command::Start) {
        return ui::start(&app.bot, &message).await;
    }
    if !app.authorized(&message) {
        return Ok(());
    }
    let Some(owner) = message.from.as_ref().map(|user| user.id) else {
        return Ok(());
    };
    let result = match command {
        Command::Start => Ok(()),
        Command::Post(value) if value.trim().is_empty() => {
            ui::say(
                &app.bot,
                &message,
                "Send /post followed by a public GitHub or GitLab repository-root URL.",
            )
            .await?;
            Ok(())
        }
        Command::Post(value) => match RepositoryRef::parse(&value) {
            Ok(reference) => {
                deactivate(&app, &message, owner, false).await;
                create(&app, &message, owner, reference, false).await
            }
            Err(error) => Err(error),
        },
        Command::Cancel => {
            deactivate(&app, &message, owner, true).await;
            ui::say(&app.bot, &message, "🗑️ Draft cancelled.").await?;
            app.audit(format!("Draft cancelled by user {}.", owner.0))
                .await;
            Ok(())
        }
        Command::Reconcile(args) => reconcile(&app, &message, &args).await,
    };
    report(&app, &message, result).await
}
/// Report a workflow failure to the user, safe logs and the audit topic.
///
/// # Errors
///
/// Returns a sanitized Telegram error if the user-facing failure notice cannot be sent.
async fn report(app: &App, message: &Message, result: Result<()>) -> Result<()> {
    if let Err(error) = result {
        tracing::warn!(error = %error, "Workflow failed");
        ui::say(&app.bot, message, format!("⚠️ {error}")).await?;
        app.audit(format!("Workflow failed: {error}")).await;
    }
    Ok(())
}
/// Admit controls only for the owner, active message, topic and allowed phase.
///
/// Reads state briefly, then releases the mutex before I/O. Invalid controls do
/// not transition state; valid data from [`Action::parse`] alone is insufficient.
///
/// # Errors
///
/// Returns sanitized Telegram errors for control updates and replies. Workflow
/// failures are otherwise passed to [`report`].
pub async fn callback(app: Arc<App>, callback: CallbackQuery) -> Result<()> {
    let Some(message) = callback
        .message
        .as_ref()
        .and_then(|message| message.regular_message())
    else {
        return Ok(());
    };
    if !app.authorized(message) {
        return Ok(());
    }
    let owner = callback.from.id;
    let state = app.states.lock().await.get(&owner).cloned();
    let action = callback.data.as_deref().and_then(Action::parse);
    let valid = match (&state, action) {
        (
            Some(State::AwaitingDownloadApproval {
                owner: stored,
                message: id,
                ..
            }),
            Some(Action::WithoutDownload | Action::CancelDownload),
        ) => *stored == owner && *id == message.id,
        (
            Some(State::Draft {
                session,
                confirming,
            }),
            Some(action),
        ) if session.owner == owner && session.message == message.id => {
            matches!(
                (confirming, action),
                (_, Action::Cancel)
                    | (false, Action::Publish | Action::Regenerate)
                    | (true, Action::Confirm | Action::Back)
            )
        }
        _ => false,
    };
    let _ = app
        .bot
        .answer_callback_query(callback.id)
        .text(if valid {
            "Processing…"
        } else {
            "This control is not active for you. Create a draft with /post."
        })
        .show_alert(!valid)
        .await;
    if !valid {
        return Ok(());
    }
    let result = match (state, action) {
        (
            Some(State::AwaitingDownloadApproval { reference, .. }),
            Some(Action::WithoutDownload),
        ) => {
            deactivate(&app, message, owner, false).await;
            let result = create(&app, message, owner, reference, true).await;
            if result.is_ok() {
                ui::delete(&app.bot, message.chat.id, message.id).await;
            }
            result
        }
        (Some(State::AwaitingDownloadApproval { .. }), Some(Action::CancelDownload))
        | (Some(State::Draft { .. }), Some(Action::Cancel)) => {
            deactivate(&app, message, owner, true).await;
            ui::say(&app.bot, message, "🗑️ Draft cancelled.").await?;
            app.audit(format!("Draft cancelled by user {}.", owner.0))
                .await;
            Ok(())
        }
        (Some(State::Draft { session, .. }), Some(Action::Publish | Action::Back)) => {
            let confirming = action == Some(Action::Publish);
            app.bot
                .edit_message_reply_markup(message.chat.id, message.id)
                .reply_markup(ui::draft_keyboard(&session.draft, confirming))
                .await?;
            app.states.lock().await.insert(
                owner,
                State::Draft {
                    session,
                    confirming,
                },
            );
            Ok(())
        }
        (Some(State::Draft { session, .. }), Some(Action::Regenerate)) => {
            revise(&app, message, session).await
        }
        (Some(State::Draft { session, .. }), Some(Action::Confirm)) => {
            publish(&app, message, session).await
        }
        _ => Ok(()),
    };
    report(&app, message, result).await
}
/// Present the durable publication outcome and remove or restore draft controls.
///
/// Recovery notices direct staff to inspect the channel and reconcile; this helper
/// never retries a copy itself.
///
/// # Errors
///
/// Propagates reservation/delivery errors and sanitized Telegram reply/control errors.
async fn publish(app: &App, source: &Message, session: Arc<DraftSession>) -> Result<()> {
    let outcome = publication::publish(app, &session, source.chat.id, session.owner).await?;
    let text = match outcome {
        Outcome::Completed(receipt) => {
            deactivate(app, source, session.owner, true).await;
            app.audit(format!(
                "Publication #{} completed; channel message #{}.",
                receipt.operation, receipt.message
            ))
            .await;
            "✅ Published to the channel.".to_owned()
        }
        Outcome::Compensated => {
            restore(app, source, session).await?;
            "⚠️ Publication could not be recorded, so the channel copy was removed. You may retry."
                .into()
        }
        Outcome::Blocked(until) => {
            restore(app, source, session).await?;
            format!(
                "This repository is on cooldown until {}.",
                until.format("%Y-%m-%d %H:%M:%S UTC")
            )
        }
        Outcome::InProgress(id) => format!("⏳ Operation #{id} is still in progress."),
        Outcome::Recovery(id, receipt) => {
            let visible = receipt
                .map(|r| {
                    format!(
                        "/reconcile {id} {} {}",
                        r.message,
                        r.published_at.to_rfc3339()
                    )
                })
                .unwrap_or_else(|| format!("/reconcile {id} <channel-message-id> <ISO-8601-time>"));
            app.audit(format!(
                "Publication #{id} requires staff reconciliation. {visible}"
            ))
            .await;
            format!(
                "🚨 Delivery is unresolved. Inspect the channel. If visible: {visible}. If absent: /reconcile {id} absent. Do not send another copy."
            )
        }
    };
    ui::say(&app.bot, source, text).await?;
    Ok(())
}
/// Restore normal review controls and leave confirmation phase after a handled refusal.
///
/// # Errors
///
/// Returns a sanitized Telegram error if the keyboard cannot be updated; in that
/// case state is not replaced.
async fn restore(app: &App, source: &Message, session: Arc<DraftSession>) -> Result<()> {
    app.bot
        .edit_message_reply_markup(source.chat.id, session.message)
        .reply_markup(ui::draft_keyboard(&session.draft, false))
        .await?;
    app.states.lock().await.insert(
        session.owner,
        State::Draft {
            session,
            confirming: false,
        },
    );
    Ok(())
}
/// Parse staff inspection results and resolve an operation without copying again.
///
/// Accepts `<id> absent` or `<id> <message-id> <RFC-3339-time-with-timezone>`.
/// The configured channel is checked by persistence; live leases prevent reconciliation.
///
/// # Errors
///
/// Returns [`Error::Invalid`] for invalid syntax, IDs, timestamps or forbidden
/// operation transitions; propagates database and Telegram reply failures.
async fn reconcile(app: &App, source: &Message, args: &str) -> Result<()> {
    let usage = Error::Invalid(
        "Usage: /reconcile <operation-id> absent, or /reconcile <operation-id> <channel-message-id> <ISO-8601-publication-time-with-timezone>",
    );
    let parts: Vec<_> = args.split_whitespace().collect();
    let Some(id) = parts
        .first()
        .and_then(|v| v.parse::<i32>().ok())
        .filter(|v| *v > 0)
    else {
        return Err(usage);
    };
    match parts.as_slice() {
        [_, "absent"] => {
            db::reconcile_absent(&app.pool, id, app.config.channel).await?;
            ui::say(
                &app.bot,
                source,
                format!("✅ Operation #{id} closed with no visible publication."),
            )
            .await?;
        }
        [_, message, date] => {
            let message = message
                .parse::<i32>()
                .ok()
                .filter(|v| *v > 0)
                .ok_or(usage)?;
            let published_at = DateTime::parse_from_rfc3339(date)
                .map_err(|_| Error::Invalid("Use an ISO-8601 publication time with timezone."))?
                .with_timezone(&Utc);
            db::complete(
                &app.pool,
                db::Receipt {
                    operation: id,
                    channel: app.config.channel,
                    message,
                    published_at,
                },
                true,
            )
            .await?;
            ui::say(
                &app.bot,
                source,
                format!("✅ Channel message #{message} recorded; cooldown is active."),
            )
            .await?;
        }
        _ => return Err(usage),
    }
    app.audit(format!("Staff reconciled publication operation #{id}."))
        .await;
    Ok(())
}
