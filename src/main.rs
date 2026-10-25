//! Staff-reviewed Telegram posts derived from public repository evidence.
//!
//! This private binary exposes a CLI rather than a reusable library API. The item
//! pages document internal contracts for maintainers; run `cargo doc --no-deps`
//! to browse them. Binary documentation includes private modules and helpers.
//!
//! # Resource ownership
//!
//! [`execute`] reads [`config::FileSettings`] and constructs the shared HTTP/SQLite
//! pools. [`bot::run`] owns polling, per-user workflow state and bounded draft/render
//! work. It drains admitted work on shutdown before closing the database.
//!
//! # Evidence and publication boundaries
//!
//! [`repositories`] verifies public visibility and assembles untrusted evidence.
//! [`generation`] validates structured model output and resolves inspected link IDs.
//! [`media`] produces attributed banners. [`bot`] admits staff actions and coordinates
//! Telegram delivery with [`db`] reservations. A committed copy reservation always
//! precedes delivery; ambiguous delivery blocks until staff reconciliation.
//! [`error`] discards sensitive external diagnostics throughout these boundaries.
//!
//! # CLI examples
//!
//! Validate settings and explicitly apply migrations before polling:
//!
//! ```bash
//! androidrepo-bot --config /path/to/config.toml check-config
//! androidrepo-bot --config /path/to/config.toml migrate
//! androidrepo-bot --config /path/to/config.toml run
//! ```
//!
//! Render without configuration, network access or service credentials:
//!
//! ```bash
//! androidrepo-bot render-banner --title AntennaPod \
//!   --repository AntennaPod/AntennaPod --stack 'Java · GPL-3.0 · Podcast' \
//!   --output /tmp/banner.png
//! ```
//!
//! `inspect <public-repository-url> --output /tmp/evidence.json` uses read-only
//! provider APIs and optional provider credentials, without AI or Telegram calls.
//! See the repository README for all settings, staff commands, recovery procedures,
//! verification commands and bundled asset licenses.

mod bot;
mod config;
mod db;
mod error;
mod generation;
mod http;
mod media;
mod repositories;

use clap::{Parser, Subcommand};
use error::Result;
use std::path::PathBuf;

/// Command-line selection and optional global configuration path.
#[derive(Parser)]
#[command(version, about)]
struct Cli {
    /// TOML configuration file (defaults to config.toml).
    #[arg(long, global = true)]
    config: Option<PathBuf>,
    /// Selected operation; defaults to polling when omitted.
    #[command(subcommand)]
    command: Option<Command>,
}
/// Operational entry points; omitting a subcommand selects [`Self::Run`].
#[derive(Subcommand)]
enum Command {
    /// Poll Telegram (the default when no command is supplied).
    Run,
    /// Apply embedded SQL migrations; requires only database_url.
    Migrate,
    /// Validate configuration without connecting to external services.
    CheckConfig,
    /// Render a local banner without credentials or network access.
    RenderBanner {
        /// Project title displayed on the offline banner.
        #[arg(long)]
        title: String,
        /// Repository name displayed in banner metadata.
        #[arg(long, default_value = "Android Repository")]
        repository: String,
        /// Technology/license text displayed in banner metadata.
        #[arg(long, default_value = "Open-source Android project")]
        stack: String,
        /// Destination path for generated local output.
        #[arg(long)]
        output: PathBuf,
    },
    /// Inspect a public repository without AI generation or Telegram delivery.
    Inspect {
        /// Clean public GitHub or GitLab repository-root URL.
        url: String,
        /// Destination path for generated local output.
        #[arg(long)]
        output: PathBuf,
    },
}
/// Install a sanitized panic hook and convert execution results into process exit codes.
#[tokio::main]
async fn main() -> std::process::ExitCode {
    // Panic hooks must not print dependency panic payloads containing URLs or data.
    std::panic::set_hook(Box::new(|_| {
        eprintln!("Internal panic; process will stop or drain safely.")
    }));
    match execute(Cli::parse()).await {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            std::process::ExitCode::FAILURE
        }
    }
}
/// Compose only the resources required by the selected command.
///
/// Offline rendering bypasses configuration. Inspection may omit the default
/// configuration file; migration requires only a database URL. Polling verifies the
/// baseline and transfers shared resources to [`bot::run`].
///
/// # Errors
///
/// Returns sanitized configuration, file, provider, rendering, database or Telegram
/// errors from the selected command; raw external errors are never printed.
async fn execute(cli: Cli) -> Result<()> {
    let command = cli.command.unwrap_or(Command::Run);
    if let Command::RenderBanner {
        title,
        repository,
        stack,
        output,
    } = command
    {
        let started = std::time::Instant::now();
        let banner = tokio::task::spawn_blocking(move || {
            media::render_offline(media::BannerRequest {
                title,
                repository,
                stack,
            })
        })
        .await
        .map_err(|_| error::Error::Image)??;
        tokio::fs::write(output, &banner.bytes).await?;
        println!(
            "Rendered 1920x1080 PNG: {} bytes in {:?}; artwork {}",
            banner.bytes.len(),
            started.elapsed(),
            banner.artwork
        );
        return Ok(());
    }
    let allow_missing = cli.config.is_none() && matches!(command, Command::Inspect { .. });
    let config_path = cli.config.unwrap_or_else(|| PathBuf::from("config.toml"));
    let settings = config::FileSettings::load(&config_path, allow_missing).await?;
    if matches!(command, Command::Migrate) {
        let pool = db::connect(&settings.database_url()?).await?;
        db::migrate(&pool).await?;
        pool.close().await;
        println!("Database migrations applied.");
        return Ok(());
    }
    if let Command::Inspect { url, output } = command {
        let reference = repositories::RepositoryRef::parse(&url)?;
        let repository = repositories::fetch(
            &http::client()?,
            &reference,
            settings.provider_token(reference.provider).as_deref(),
        )
        .await?;
        tokio::fs::write(output, serde_json::to_vec_pretty(&repository)?).await?;
        println!("Public repository evidence saved.");
        return Ok(());
    }
    let config = settings.config()?;
    // Only application events are enabled: dependency debug logs can contain secrets.
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(format!("off,androidrepo_bot={}", config.log_level))
        .init();
    if matches!(command, Command::CheckConfig) {
        println!("Configuration is valid.");
        return Ok(());
    }
    let signals = bot::ShutdownSignals::register()?;
    let http = http::client()?;
    let pool = db::connect(&config.database_url).await?;
    db::verify(&pool).await?;
    bot::run(config, http, pool, signals).await
}
