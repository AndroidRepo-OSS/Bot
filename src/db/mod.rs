//! Durable SQLite persistence with explicit, serialized write transactions.
mod publications;
use crate::{
    error::{Error, Result},
    repositories::{Repository, RepositoryRef},
};
pub use publications::{
    Delivery, Intent, Receipt, Reservation, begin_compensation, complete, eligibility,
    finish_compensation, mark_delivery, reconcile_absent, reserve,
};
use sqlx::{
    ConnectOptions, SqlitePool,
    sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous},
};
use std::{str::FromStr, time::Duration};

/// Only file-backed SQLite URLs are supported: recovery must survive restarts.
pub fn options(url: &str) -> Result<SqliteConnectOptions> {
    let path = url
        .strip_prefix("sqlite://")
        .filter(|path| !path.is_empty() && !path.contains(['?', '#']) && *path != ":memory:")
        .ok_or(Error::Config(
            "database_url must use sqlite:// with a persistent file path",
        ))?;
    let options = SqliteConnectOptions::from_str(url).map_err(|_| Error::Config("database_url"))?;
    let filename = options.get_filename().to_string_lossy();
    if filename.is_empty()
        || filename == ":memory:"
        || filename.starts_with("file:")
        || path.contains('\0')
    {
        return Err(Error::Config(
            "database_url must name a persistent SQLite file",
        ));
    }
    Ok(options
        .create_if_missing(true)
        .foreign_keys(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full)
        .busy_timeout(Duration::from_secs(10))
        .disable_statement_logging())
}

pub async fn connect(url: &str) -> Result<SqlitePool> {
    Ok(SqlitePoolOptions::new()
        .max_connections(8)
        .acquire_timeout(Duration::from_secs(15))
        .connect_with(options(url)?)
        .await?)
}
pub async fn migrate(pool: &SqlitePool) -> Result<()> {
    sqlx::migrate!()
        .run(pool)
        .await
        .map_err(|_| Error::Database)
}
pub async fn verify(pool: &SqlitePool) -> Result<()> {
    let applied: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM _sqlx_migrations WHERE version = 202610220001 AND success)",
    )
    .fetch_one(pool)
    .await?;
    if !applied {
        return Err(Error::Invalid(
            "Run androidrepo-bot migrate before starting the bot.",
        ));
    }
    Ok(())
}

pub async fn register(
    pool: &SqlitePool,
    repository: &Repository,
    requested: &RepositoryRef,
) -> Result<i32> {
    let mut tx = pool.begin_with("BEGIN IMMEDIATE").await?;
    let reference = &repository.reference;
    let id = sqlx::query_scalar("INSERT INTO repository_apps (provider, provider_repository_id, current_namespace, current_name, current_url, display_name, first_seen_at, last_seen_at)
        VALUES (?1,?2,?3,?4,?5,?6,strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT (provider,provider_repository_id) DO UPDATE SET
        current_namespace=EXCLUDED.current_namespace, current_name=EXCLUDED.current_name, current_url=EXCLUDED.current_url, display_name=EXCLUDED.display_name,
        first_seen_at=MIN(repository_apps.first_seen_at,EXCLUDED.first_seen_at), last_seen_at=MAX(repository_apps.last_seen_at,EXCLUDED.last_seen_at) RETURNING id")
        .bind(reference.provider.name()).bind(&repository.provider_id).bind(&reference.namespace).bind(&reference.name).bind(reference.url()).bind(&repository.display_name).fetch_one(&mut *tx).await?;
    for alias in [requested, reference] {
        sqlx::query("INSERT INTO repository_aliases (repository_app_id, namespace, name, full_name, url, observed_at) VALUES (?1,?2,?3,?4,?5,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            ON CONFLICT (repository_app_id,full_name,url) DO UPDATE SET observed_at=MAX(repository_aliases.observed_at,EXCLUDED.observed_at)")
            .bind(id).bind(&alias.namespace).bind(&alias.name).bind(alias.full_name()).bind(alias.url()).execute(&mut *tx).await?;
    }
    tx.commit().await?;
    Ok(id)
}
