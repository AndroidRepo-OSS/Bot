//! Staff workflow state, resource ownership and the draining Telegram dispatcher.
//!
//! [`run`] serializes commands and callbacks by user. [`State`] is authoritative for
//! owner/message/phase admission; callbacks carry only intent. Draft preparation
//! is bounded separately from CPU rendering. Shutdown retains admitted publication
//! futures until their persistence/recovery work finishes, then closes SQLite.

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
use sqlx::SqlitePool;
use std::{collections::HashMap, sync::Arc};
use teloxide::{
    dispatching::UpdateHandler,
    prelude::*,
    types::{BotCommand, BotCommandScope, MessageId, Recipient},
    update_listeners::Polling,
};
use tokio::sync::{Mutex, Semaphore};

/// Resources and bounded work owned by the polling lifecycle.
///
/// The dispatcher serializes updates by user. State locks cover short map accesses
/// only; network and database operations run outside those locks. Secrets in the
/// configuration deliberately prevent deriving `Debug` for this context.
pub struct App {
    /// Telegram API client sharing the HTTP pool.
    pub bot: Bot,
    /// Validated configuration and provider credentials.
    pub config: Config,
    /// Shared redirect-disabled HTTP client.
    pub http: reqwest::Client,
    /// Shared durable SQLite pool, closed after dispatcher drain.
    pub pool: SqlitePool,
    /// Active per-user state; hold this lock only for short map operations.
    states: Mutex<HashMap<UserId, State>>,
    /// Two permits held through artwork retrieval and blocking rendering.
    render_slots: Arc<Semaphore>,
    /// Four permits limiting draft creation and regeneration.
    work_slots: Semaphore,
}
/// Active per-user workflow phase; callback payloads alone grant no authority.
#[derive(Clone)]
enum State {
    /// Await an explicit owner decision before proceeding without a Download button.
    AwaitingDownloadApproval {
        /// User who may answer the missing-download prompt.
        owner: UserId,
        /// Active missing-download approval message.
        message: MessageId,
        /// Repository to refetch after explicit approval.
        reference: RepositoryRef,
    },
    /// Review a usable draft or confirm its publication.
    Draft {
        /// Usable review message with validated content and evidence.
        session: Arc<DraftSession>,
        /// Whether Publish now/Back controls are currently admitted.
        confirming: bool,
    },
}
impl State {
    /// Return the only message whose workflow controls may currently be admitted.
    fn message(&self) -> MessageId {
        match self {
            Self::AwaitingDownloadApproval { message, .. } => *message,
            Self::Draft { session, .. } => session.message,
        }
    }
}
/// Usable review message and its matching evidence snapshot, draft and owner.
///
/// Shared snapshots survive awaits without holding the state mutex. The database
/// repository ID refers to stable provider identity, rather than only the URL path.
#[derive(Clone)]
pub struct DraftSession {
    /// User ID allowed to operate this draft.
    pub owner: UserId,
    /// Active review photo message in the staff chat.
    pub message: MessageId,
    /// Evidence snapshot used to resolve every selected destination.
    pub repository: Arc<Repository>,
    /// Stable local repository identity returned by registration.
    pub repository_id: i32,
    /// Validated content corresponding to the review message.
    pub draft: Draft,
    /// Optional staff message warning that README evidence was absent.
    notice: Option<MessageId>,
}
impl App {
    /// Send a best-effort staff audit through [`ui::audit`].
    ///
    /// Callers must supply safe categories and numeric context, never private evidence
    /// or credentials. Failure logs a safe warning and does not abort the workflow.
    pub async fn audit(&self, text: impl Into<String>) {
        ui::audit(
            &self.bot,
            self.config.staff_chat,
            self.config.log_topic,
            text,
        )
        .await;
    }
    /// Check staff chat and workflow topic; caller separately requires an identified user.
    fn authorized(&self, message: &Message) -> bool {
        message.chat.id.0 == self.config.staff_chat
            && message
                .thread_id
                .is_some_and(|id| id.0.0 == self.config.post_topic)
    }
}
/// Signal subscriptions installed before startup can perform external effects.
pub struct ShutdownSignals {
    /// Registered interrupt receiver, including interrupts received during startup.
    #[cfg(unix)]
    interrupt: tokio::signal::unix::Signal,
    /// Registered termination receiver.
    #[cfg(unix)]
    terminate: tokio::signal::unix::Signal,
    /// Registered Windows console interrupt receiver.
    #[cfg(windows)]
    interrupt: tokio::signal::windows::CtrlC,
}
impl ShutdownSignals {
    /// Register process signals before database and Telegram initialization.
    ///
    /// # Errors
    ///
    /// Returns a sanitized I/O error if signal registration fails.
    pub fn register() -> Result<Self> {
        Ok(Self {
            #[cfg(unix)]
            interrupt: tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt())?,
            #[cfg(unix)]
            terminate: tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?,
            #[cfg(windows)]
            interrupt: tokio::signal::windows::ctrl_c()?,
        })
    }
    /// Wait for a signal; a closed subscription also requests a safe drain.
    async fn wait(&mut self) -> Result<()> {
        #[cfg(unix)]
        let received = tokio::select! {
            value = self.interrupt.recv() => value,
            value = self.terminate.recv() => value,
        };
        #[cfg(windows)]
        let received = self.interrupt.recv().await;
        received.ok_or(Error::Io)
    }
}
/// Configure Telegram commands and poll until dispatcher shutdown completes.
///
/// Owns a single polling loop, four draft-work slots and two render slots. Commands
/// and callbacks share per-user isolation. SIGINT/SIGTERM stop polling and drain
/// admitted work, including publication futures, before closing the SQLite pool.
/// Startup deletes the webhook and updates command menus through Telegram.
///
/// # Errors
///
/// Returns sanitized Telegram errors when startup or dispatcher initialization
/// fails, or an I/O error after draining if a signal subscription closes.
/// Individual workflow failures are reported through safe application errors.
pub async fn run(
    config: Config,
    http: reqwest::Client,
    pool: SqlitePool,
    mut signals: ShutdownSignals,
) -> Result<()> {
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
    app.audit("Bot started.").await;
    let dispatch = dispatcher.try_dispatch_with_listener(
        listener,
        Arc::new(|_: teloxide::RequestError| async {
            tracing::warn!("Telegram polling failed; retrying with backoff");
        }),
    );
    tokio::pin!(dispatch);
    let mut signal_result = Ok(());
    let result = tokio::select! {
        result = &mut dispatch => result,
        result = signals.wait() => {
            signal_result = result;
            if signal_result.is_err() {
                tracing::warn!("Signal subscription failed; draining Telegram work");
            } else {
                tracing::info!("Stopping admission and draining Telegram work");
            }
            // get_me runs before dispatch starts. Keep polling dispatch while waiting
            // for the shutdown token to accept the request; never drop admitted work.
            let shutdown = async {
                loop {
                    if let Ok(completion) = token.shutdown() {
                        completion.await;
                        break;
                    }
                    tokio::time::sleep(std::time::Duration::from_millis(20)).await;
                }
            };
            tokio::select! {
                result = &mut dispatch => result,
                () = shutdown => dispatch.await,
            }
        }
    };
    app.audit("Bot stopped after draining admitted work.").await;
    pool.close().await;
    result.map_err(Error::from)?;
    signal_result
}
