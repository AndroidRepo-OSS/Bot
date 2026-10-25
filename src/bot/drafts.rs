//! Draft preparation and replacement after a usable Telegram message exists.
//!
//! [`create`] checks evidence/cooldown, generates content and sends a rendered review
//! photo. [`revise`] preserves the previous draft on failure and swaps state before
//! old-message cleanup. Channel copies belong to [`super::publication`].

use super::{App, DraftSession, State, ui};
use crate::{
    db,
    error::{Error, Result},
    generation::{self, Outcome as Generated},
    media,
    repositories::{self, RepositoryRef},
};
use std::sync::Arc;
use teloxide::{
    prelude::*,
    types::{InputFile, ParseMode},
};
/// Remove an owner’s active state and clear its message controls best effort.
///
/// When `delete` is true, also delete the draft and associated missing-README
/// notice. State is removed before any Telegram request, so stale controls fail admission.
pub(super) async fn deactivate(app: &App, source: &Message, owner: UserId, delete: bool) {
    let previous = app.states.lock().await.remove(&owner);
    if let Some(previous) = previous {
        ui::clear_controls(&app.bot, source, previous.message()).await;
        if delete {
            ui::delete(&app.bot, source.chat.id, previous.message()).await;
            if let State::Draft { session, .. } = previous
                && let Some(notice) = session.notice
            {
                ui::delete(&app.bot, source.chat.id, notice).await;
            }
        }
    }
}
/// Inspect, register and generate a repository under one of four work permits.
///
/// Records cooldown refusals before generation. A valid draft becomes active only
/// after the caption/banner message is sent; missing download evidence creates an
/// owner-bound approval message. `allow_missing` must come from that approval.
/// This may call the model provider and sends staff messages, never channel copies.
///
/// # Errors
///
/// Propagates sanitized provider, database, generation, rendering and Telegram
/// failures. A closed work semaphore returns [`Error::External`].
pub(super) async fn create(
    app: &App,
    source: &Message,
    owner: UserId,
    reference: RepositoryRef,
    allow_missing: bool,
) -> Result<()> {
    let _permit = app
        .work_slots
        .acquire()
        .await
        .map_err(|_| Error::External)?;
    let repository = Arc::new(
        repositories::fetch(
            &app.http,
            &reference,
            app.config.provider_token(reference.provider),
        )
        .await?,
    );
    let repository_id = db::register(&app.pool, &repository, &reference).await?;
    if let Some(until) = db::eligibility(
        &app.pool,
        repository_id,
        &repository.reference,
        owner.0 as i64,
    )
    .await?
    {
        ui::say(
            &app.bot,
            source,
            format!(
                "This repository is on cooldown until {}.",
                until.format("%Y-%m-%d %H:%M:%S UTC")
            ),
        )
        .await?;
        return Ok(());
    }
    match generation::generate(
        &app.http,
        &app.config,
        &repository,
        allow_missing,
        |draft| ui::caption(draft).map(|_| ()),
    )
    .await?
    {
        Generated::Draft(draft) => {
            let (message, artwork) = send_draft(app, source, &repository, &draft).await?;
            let mut session = DraftSession {
                owner,
                message: message.id,
                repository: repository.clone(),
                repository_id,
                draft,
                notice: None,
            };
            app.states.lock().await.insert(
                owner,
                State::Draft {
                    session: Arc::new(session.clone()),
                    confirming: false,
                },
            );
            if repository.readme.is_none()
                && let Ok(notice) = ui::say(
                    &app.bot,
                    source,
                    "⚠️ No README was found. This draft uses repository metadata only.",
                )
                .await
            {
                session.notice = Some(notice.id);
                app.states.lock().await.insert(
                    owner,
                    State::Draft {
                        session: Arc::new(session),
                        confirming: false,
                    },
                );
            }
            app.audit(format!(
                "Draft created by user {}; repository #{repository_id}; artwork {artwork}.",
                owner.0
            ))
            .await;
        }
        Generated::NotAndroid(reason) => {
            ui::say(
                &app.bot,
                source,
                format!("Not an Android project: {reason}"),
            )
            .await?;
        }
        Generated::Insufficient(reason) => {
            ui::say(
                &app.bot,
                source,
                format!("Insufficient repository evidence: {reason}"),
            )
            .await?;
        }
        Generated::MissingDownload(reason) => {
            let mut request = app
                .bot
                .send_message(
                    source.chat.id,
                    format!("⚠️ {reason}\n\nGenerate a draft without a Download button?"),
                )
                .reply_markup(ui::missing_download());
            if let Some(thread) = source.thread_id {
                request = request.message_thread_id(thread);
            }
            let sent = request.await?;
            app.states.lock().await.insert(
                owner,
                State::AwaitingDownloadApproval {
                    owner,
                    message: sent.id,
                    reference,
                },
            );
        }
    }
    Ok(())
}
/// Validate the final caption, render an attributed banner and send the review photo.
///
/// Returns the sent message and actual artwork ID; no workflow state is changed here.
///
/// # Errors
///
/// Propagates caption, renderer and Telegram failures.
async fn send_draft(
    app: &App,
    source: &Message,
    repository: &repositories::Repository,
    draft: &generation::Draft,
) -> Result<(Message, String)> {
    let caption = ui::caption(draft)?;
    let stack = repository
        .languages
        .first()
        .into_iter()
        .chain(repository.license.as_ref())
        .chain(repository.release.as_ref().map(|r| &r.tag))
        .map(String::as_str)
        .collect::<Vec<_>>()
        .join(" · ");
    let banner = media::render(
        &app.http,
        app.render_slots.clone(),
        media::BannerRequest {
            title: draft.title.clone(),
            repository: repository.reference.full_name(),
            stack,
        },
    )
    .await?;
    let mut request = app
        .bot
        .send_photo(
            source.chat.id,
            InputFile::memory(banner.bytes).file_name("repository-banner.png"),
        )
        .caption(caption)
        .parse_mode(ParseMode::Html)
        .reply_markup(ui::draft_keyboard(draft, false));
    if let Some(thread) = source.thread_id {
        request = request.message_thread_id(thread);
    }
    Ok((request.await?, banner.artwork))
}

/// Generate and send a replacement while retaining the current usable draft.
///
/// Uses the same repository snapshot. Stores the replacement before best-effort
/// deletion of the previous message. Generation/send failure leaves the old draft
/// active and is reported to staff; a previous no-download draft retains that policy.
///
/// # Errors
///
/// Returns [`Error::External`] if work admission closes, or a sanitized Telegram
/// error if the failure notice cannot be sent. Replacement failures are handled locally.
pub(super) async fn revise(app: &App, source: &Message, session: Arc<DraftSession>) -> Result<()> {
    let _permit = app
        .work_slots
        .acquire()
        .await
        .map_err(|_| Error::External)?;
    let replacement = async {
        let Generated::Draft(draft) = generation::generate(
            &app.http,
            &app.config,
            &session.repository,
            session.draft.download_url.is_none(),
            |draft| ui::caption(draft).map(|_| ()),
        )
        .await?
        else {
            return Err(Error::Generation);
        };
        let (message, _) = send_draft(app, source, &session.repository, &draft).await?;
        let replacement = Arc::new(DraftSession {
            message: message.id,
            draft,
            ..(*session).clone()
        });
        app.states.lock().await.insert(
            session.owner,
            State::Draft {
                session: replacement,
                confirming: false,
            },
        );
        Ok::<_, Error>(())
    }
    .await;
    if replacement.is_err() {
        ui::say(
            &app.bot,
            source,
            "⚠️ Could not regenerate. Your current draft remains available.",
        )
        .await?;
        return Ok(());
    }
    ui::delete(&app.bot, source.chat.id, session.message).await;
    app.audit(format!(
        "Draft regenerated by user {}; repository #{}.",
        session.owner.0, session.repository_id
    ))
    .await;
    Ok(())
}
