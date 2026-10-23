//! Per-user draft workflow; teloxide serializes commands and callbacks by user.
mod drafts;
mod handlers;
mod publication;
pub mod ui;
use crate::{
    config::Config,
    error::{Error, Result},
    generation::Draft,
    repositories::{Repository, RepositoryRef},
};
use sqlx::PgPool;
use std::{collections::HashMap, sync::Arc};
use teloxide::{
    dispatching::UpdateHandler,
    prelude::*,
    types::{BotCommand, BotCommandScope, MessageId, Recipient},
    update_listeners::Polling,
};
use tokio::sync::{Mutex, Semaphore};

pub struct App {
    pub bot: Bot,
    pub config: Config,
    pub http: reqwest::Client,
    pub pool: PgPool,
    states: Mutex<HashMap<UserId, State>>,
    render_slots: Arc<Semaphore>,
    work_slots: Semaphore,
}
#[derive(Clone)]
enum State {
    Download {
        owner: UserId,
        message: MessageId,
        reference: RepositoryRef,
    },
    Draft {
        session: Arc<DraftSession>,
        confirming: bool,
    },
}
impl State {
    fn message(&self) -> MessageId {
        match self {
            Self::Download { message, .. } => *message,
            Self::Draft { session, .. } => session.message,
        }
    }
}
#[derive(Clone)]
pub struct DraftSession {
    pub owner: UserId,
    pub message: MessageId,
    pub repository: Arc<Repository>,
    pub repository_id: i32,
    pub draft: Draft,
    notice: Option<MessageId>,
}
impl App {
    pub async fn audit(&self, text: impl Into<String>) {
        ui::audit(
            &self.bot,
            self.config.staff_chat,
            self.config.log_topic,
            text,
        )
        .await;
    }
    fn authorized(&self, message: &Message) -> bool {
        message.chat.id.0 == self.config.staff_chat
            && message
                .thread_id
                .is_some_and(|id| id.0.0 == self.config.post_topic)
    }
}
pub async fn run(config: Config, http: reqwest::Client, pool: PgPool) -> Result<()> {
    // Same HTTP pool and redirect policy; no retry adapter around channel copies.
    let bot = Bot::with_client(&config.bot_token, http.clone());
    bot.delete_webhook().await?;
    bot.set_my_commands([BotCommand::new("start", "About Android Repository")])
        .await?;
    bot.set_my_commands([
        BotCommand::new("start", "About Android Repository"),
        BotCommand::new("post", "Create a repository draft"),
        BotCommand::new("cancel", "Cancel your draft"),
        BotCommand::new("reconcile", "Resolve an uncertain publication"),
    ])
    .scope(BotCommandScope::Chat {
        chat_id: Recipient::Id(ChatId(config.staff_chat)),
    })
    .await?;
    let app = Arc::new(App {
        bot: bot.clone(),
        config,
        http,
        pool: pool.clone(),
        states: Mutex::new(HashMap::new()),
        render_slots: Arc::new(Semaphore::new(2)),
        work_slots: Semaphore::new(4),
    });
    let handler: UpdateHandler<Error> = dptree::entry()
        .branch(
            Update::filter_message()
                .filter_command::<handlers::Command>()
                .endpoint(handlers::command),
        )
        .branch(Update::filter_callback_query().endpoint(handlers::callback));
    let mut dispatcher = Dispatcher::builder(bot.clone(), handler)
        .dependencies(dptree::deps![app.clone()])
        .distribution_function(|update: &Update| update.from().map(|user| user.id))
        .worker_queue_size(16)
        .default_handler(|_| async {})
        .error_handler(Arc::new(|error: Error| async move {
            tracing::warn!(error = %error, "Update failed");
        }))
        .build();
    let listener = Polling::builder(bot)
        .timeout(std::time::Duration::from_secs(10))
        .limit(20)
        .build();
    let token = dispatcher.shutdown_token();
    let signal = tokio::spawn(async move {
        #[cfg(unix)]
        {
            let mut terminate =
                tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
            tokio::select! { result = tokio::signal::ctrl_c() => result?, _ = terminate.recv() => {} }
        }
        #[cfg(not(unix))]
        tokio::signal::ctrl_c().await?;
        tracing::info!("Stopping admission and draining Telegram work");
        // get_me may still be running during startup. Wait until the dispatcher
        // starts, so a signal cannot be lost in that small window.
        loop {
            if let Ok(completion) = token.shutdown() {
                completion.await;
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        Ok::<_, std::io::Error>(())
    });
    app.audit("Bot started.").await;
    let result = dispatcher
        .try_dispatch_with_listener(
            listener,
            Arc::new(|_: teloxide::RequestError| async {
                tracing::warn!("Telegram polling failed; retrying with backoff");
            }),
        )
        .await;
    signal.abort();
    let _ = signal.await;
    app.audit("Bot stopped after draining admitted work.").await;
    pool.close().await;
    result.map_err(Into::into)
}
