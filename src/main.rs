//! Android Repository Bot: explicit composition and resource lifetime.
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

#[derive(Parser)]
#[command(version, about)]
struct Cli {
    /// TOML configuration file (defaults to config.toml).
    #[arg(long, global = true)]
    config: Option<PathBuf>,
    #[command(subcommand)]
    command: Option<Command>,
}
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
        #[arg(long)]
        title: String,
        #[arg(long, default_value = "Android Repository")]
        repository: String,
        #[arg(long, default_value = "Open-source Android project")]
        stack: String,
        #[arg(long)]
        output: PathBuf,
    },
    /// Inspect a public repository without AI generation or Telegram delivery.
    Inspect {
        url: String,
        #[arg(long)]
        output: PathBuf,
    },
}
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
    let http = http::client()?;
    let pool = db::connect(&config.database_url).await?;
    db::verify(&pool).await?;
    bot::run(config, http, pool).await
}
