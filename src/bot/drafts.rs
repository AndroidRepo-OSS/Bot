//! Draft creation and regeneration; state is replaced only after a usable message exists.
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
                until.format("%Y-%m-%d")
            ),
        )
        .await?;
        return Ok(());
    }
    match generation::generate(&app.http, &app.config, &repository, allow_missing).await? {
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
