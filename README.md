# Android Repository Bot

A Rust Telegram bot that turns public GitHub/GitLab evidence into reviewed
Android Repository channel posts. Staff load a repository, review a generated
English caption and 1920 × 1080 banner, then explicitly confirm publication.

One binary owns the HTTP connection pool, SQLite pool, bounded rendering
work and teloxide dispatcher in a single Rust module tree.

## Build and run

Install [Rust through rustup](https://www.rust-lang.org/tools/install).
`rust-toolchain.toml` pins Rust 1.99.1 with Clippy and rustfmt. Native builds need a C/C++ compiler, CMake and pkg-config for the
TLS dependencies and bundled SQLite.

```bash
cargo build --release --locked
cp config.example.toml config.toml
chmod 600 config.toml
# Fill in your Telegram, OpenCode and SQLite file settings.
cargo run --release --locked -- check-config
cargo run --release --locked -- migrate
cargo run --release --locked -- run
```

Omitting the subcommand defaults to `run`. `check-config` does not contact any service;
`migrate` requires only `database_url`. Commands load `config.toml` from the
working directory. Use `--config /path/to/config.toml` before or after the
subcommand to select another file. Settings come only from TOML; `.env` and
process environment variables are not loaded.

Choose a writable local SQLite file path; its parent directory must exist.
`migrate` creates the file if missing. Run migrations successfully before starting
the bot. Assets and SQL migrations are embedded in
the executable; preserve the bundled asset licenses when distributing it.

Read-only provider inspection and offline rendering are available without bot,
model or database credentials:

```bash
cargo run --release --locked -- inspect https://github.com/AntennaPod/AntennaPod \
  --output /tmp/evidence.json
cargo run --release --locked -- render-banner --title AntennaPod \
  --repository AntennaPod/AntennaPod --stack 'Java · GPL-3.0 · Podcast' \
  --output /tmp/banner.png
```

`inspect` reads public provider APIs and writes evidence locally. It uses the
optional provider token if configured; it never invokes AI or Telegram.
`render-banner` always uses the bundled offline artwork.

## Configuration

| TOML key | Required for polling | Default | Purpose |
| --- | --- | --- | --- |
| `bot_token` | yes | — | Telegram bot credential |
| `staff_chat_id` | yes | — | Staff supergroup, nonzero ID |
| `post_topic_id` | yes | — | Positive staff workflow topic ID |
| `log_topic_id` | yes | — | Positive topic ID for best-effort audits |
| `channel_id` | yes | — | Target channel, nonzero ID |
| `opencode_zen_api_key` | yes | — | OpenCode Console API credential |
| `database_url` | yes | — | Persistent file URL, e.g. `sqlite://androidrepo.db` |
| `log_level` | no | `INFO` | `CRITICAL`, `ERROR`, `WARNING`/`WARN`, `INFO`, `DEBUG` |
| `opencode_zen_model` | no | `mimo-v2.6-flash-free` | Model with Chat Completions tool calling |
| `github_token` | no | — | Optional GitHub API token |
| `gitlab_token` | no | — | Optional GitLab API token |

Generation uses the OpenCode endpoint
`https://opencode.ai/inference/openai/v1/chat/completions`. Choose a model that
supports that API and tool calls; models exposed only through Responses or
Anthropic Messages are not interchangeable. Free model availability is temporary;
consult the [provider's current model documentation](https://opencode.ai/v2/docs/console/models/).

Copy [`config.example.toml`](config.example.toml) to `config.toml`. IDs are TOML
integers; credentials, URLs, model names and log levels are strings. Unknown keys,
invalid types and malformed TOML are rejected. Blank optional tokens are ignored.
`inspect` also works when the default file is absent; an explicit `--config` path
must exist. `render-banner` does not load configuration. SQLite relative paths
resolve from the working directory, including when `--config` points elsewhere.

Never commit a populated configuration file or log credentials, raw external
errors or private chat text. The default `config.toml` is ignored by Git; keep
custom configuration paths outside the repository.

## Staff workflow

- `/start` is public. `/post`, `/cancel`, `/reconcile` and callbacks require the
  configured staff chat and post topic. Commands must have an identified user.
- `/post https://github.com/owner/repository` or a nested GitLab repository root
  loads public evidence. An invalid URL leaves the current draft intact.
- **Regenerate** keeps the previous usable draft on failure. A replacement
  becomes active before the previous message is deleted.
- **Publish** opens confirmation. **Publish now** copies to the channel;
  **Back** keeps the draft. **Cancel** and `/cancel` clear the owned session.
- Draft and missing-download controls are bound to their owner and exact active
  message. Restarting discards drafts, but never publication history or recovery
  reservations.
- Missing README content produces a notice. Missing download evidence requires
  a separate staff decision before generating without a Download button.

Only HTTPS repository roots are accepted. Credentials, custom or explicit
ports, encoded/dot paths, query strings, fragments and provider subresources are
rejected. API credentials are scoped to their provider; public visibility is
checked even when authenticated. Stable provider IDs and observed aliases are
stored in SQLite.

README links are parsed as CommonMark and inert HTML. Code, hidden markup and
image sources are excluded. The model selects inspected IDs, never final URLs.
Donation links cannot become optional post links; Download must resolve to a
verified release, Android app store or package repository.

Generation has four outcomes: draft, affirmatively non-Android project,
insufficient evidence, or missing-download warning. It permits at most three
requests, 2,048 output tokens each, 6,144 total, within 120 seconds. Evidence
fields and collections are bounded, README text is limited to 50,000 characters,
and escaped evidence JSON to 80,000. Drafts require distinct features and tags,
plain text, eligible link selections and a 950-character text budget. The final
caption is also checked against 1,024 UTF-16 units.

## Publication recovery

A committed `copying` reservation precedes the only channel-copy request.
SQLite `BEGIN IMMEDIATE` transactions acquire the writer lock before reading
publication state; a unique open-operation index also prevents duplicate
reservations. The cooldown is three calendar months in UTC, clamped to the last
valid day of the destination month.
An expired lease means **unresolved delivery**, never permission to copy again.

The receipt and completed publication are committed atomically. If storing them
fails, the bot records a receipt and compensation lease before attempting to
delete the channel copy. Confirmed deletion releases the reservation. Failed or
ambiguous deletion retains a blocking operation or a conservatively recorded
publication. Both copy and compensation leases prevent concurrent staff
reconciliation while an external effect is in flight.

After inspecting the channel, staff can resolve an uncertain operation:

```text
/reconcile <operation-id> absent
/reconcile <operation-id> <channel-message-id> <ISO-8601-publication-time>
```

Example timestamp: `2026-10-22T18:00:00-03:00`. Use the actual visible message and
its actual publication time. Reconciliation never sends another channel copy.
The bot supplies the operation ID and any known receipt in its recovery notice.

## Code organization

```text
src/
├── main.rs                 # CLI, configuration and resource composition
├── config.rs               # TOML settings; secrets have no Debug representation
├── error.rs                # safe errors without external response bodies
├── http.rs                 # shared pool, bounded reads and GET retries
├── bot/
│   ├── mod.rs              # teloxide dispatcher, per-user state, shutdown
│   ├── handlers.rs         # admission, commands and callback transitions
│   ├── drafts.rs           # evidence → generation → banner → review message
│   ├── publication.rs      # Telegram delivery, persistence and compensation
│   └── ui.rs               # caption, keyboards and message helpers
├── repositories/
│   ├── mod.rs              # normalized evidence values and provider selection
│   ├── reference.rs        # strict URL parsing
│   ├── client.rs           # shared provider policy and normalization
│   ├── github.rs           # GitHub metadata and README format
│   ├── gitlab.rs           # GitLab namespaces and branch-aware README paths
│   └── links.rs            # inert CommonMark/HTML link extraction
├── generation/             # output validation, evidence prompt, tool-call client
├── media/                  # NASA fetch, bounded decoding, renderer, licensed assets
└── db/                     # registration and transactional publication transitions
migrations/                 # embedded SQLite SQLx revisions
```

`bot/` contains Telegram-facing behavior; providers, generation and rendering do
not depend on Telegram. Database functions do not perform channel effects.
`bot/publication.rs` coordinates that boundary and `db/publications.rs` owns SQL
state transitions. The split keeps delivery recovery reviewable without creating
repository interfaces, service containers or generic workflow engines.

The dispatcher serializes updates by user. State mutexes protect only short map
operations, never network calls. Up to four draft jobs and two render jobs run
concurrently. HTTP requests share a connection pool; independent repository
resources load concurrently. Image decoding and rendering use `spawn_blocking`.
SIGINT/SIGTERM stop polling and drain dispatcher work before the database closes.
Allow sufficient shutdown grace time: forced termination leaves unfinished
reservations blocked for reconciliation.

## Database upgrade

SQLite uses WAL journaling, `synchronous=FULL`, foreign keys and a ten-second
busy timeout. All writers acquire `BEGIN IMMEDIATE` before reading state. Keep
the database on a local persistent filesystem with reliable file locks; multiple
bot processes must use the same file on the same host. Do not share it over a
network filesystem. Database URLs must use `sqlite://` with a nonempty file path;
in-memory databases and URL query options are rejected so reservations survive
restarts. Relative paths resolve from the process working directory; prefer an
absolute path in deployments.

Stop and drain the bot before backing up the database. With every connection
closed, preserve the database and any remaining `-wal`/`-shm` sidecars together.
For a live backup, use SQLite's backup API rather than copying the main file.

Run `migrate` before starting the bot. The embedded initial migration creates
the SQLite schema with JSON tag arrays and UTC timestamp text. The bot has no
production database yet, so the former PostgreSQL/Alembic baseline has been
replaced. No PostgreSQL server or data import is required for a fresh installation.
Any local PostgreSQL development data is not imported automatically.

After deployment, never edit an applied SQL revision; add a new migration under
`migrations/`. No credentials or media assets change.

The baseline stores the following records. Draft sessions remain in memory and
are not restored after a restart.

| Table | Purpose and identity |
| --- | --- |
| `repository_apps` | Stable project identity, unique by provider and provider repository ID; current path and first/last observation times |
| `repository_aliases` | Observed paths for a project, unique by project, full name and URL |
| `post_attempts` | Cooldown refusals with requesting user, attempted path and blocked-until time |
| `published_posts` | Completed publication title, JSON tags, actor, UTC timestamp and unique channel/message receipt |
| `publication_operations` | Copy/compensation ownership, recovery state and receipt; at most one open operation per project |

The rustdoc for `db::publications` lists state transitions and each function's
lease, receipt and reconciliation preconditions. SQL constraints remain defined
by the embedded migration, rather than by a separate schema representation.

## Maintainer documentation

Generate the internal reference with the pinned toolchain:

```bash
cargo doc --locked --no-deps
# Open target/doc/androidrepo_bot/index.html, or use:
cargo doc --locked --no-deps --open
```

This is a private binary crate, so Cargo documents private items by default.
The landing page explains resource ownership and links to all modules. Module
pages describe trust boundaries; item pages cover types, fields, variants,
helpers, errors and publication cancellation requirements. CLI examples use
shell blocks because these modules are not an externally importable library.
The build/run and offline commands above provide operational examples.

Follow the [Rustdoc Book](https://doc.rust-lang.org/rustdoc/how-to-write-documentation.html)
and the [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/documentation.html)
when changing these contracts:

- Use `//!` for crate/module overviews and `///` for items. Start with a short
  summary, then explain behavior, units, side effects and caller obligations.
- Link related Rust items with intra-doc links. Disambiguate functions/modules
  and enums/macros when their names overlap.
- Document fallible operations under `# Errors`; add `# Panics` for known panic
  preconditions. Document cancellation where dropping a future affects durable
  work. Unsafe code remains forbidden, so no unsafe API contracts are needed.
- Give meaningful examples at the relevant workflow boundary. Mark shell and
  non-Rust examples with their actual language. If adding Rust examples, keep
  them compilable and use `?` for errors; do not hide broken examples with
  `ignore` or add test suites without explicit authorization.
- Update the affected contract alongside implementation changes. Keep
  credentials, private text and populated configuration out of documentation.

Clippy rejects missing documentation even on private items. Rustdoc rejects
broken intra-doc links, invalid HTML tags and bare URLs. To additionally treat
every documentation warning as an error, run:

```bash
RUSTDOCFLAGS='-D warnings' cargo doc --locked --no-deps
```

## Verification and performance

```bash
cargo metadata --locked --format-version 1 --no-deps > /dev/null
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo build --release --locked
cargo doc --locked --no-deps
pre-commit run --all-files
```

Install `pre-commit` as a development tool if needed; it is not a bot dependency.
There is no Rust test suite. [AGENTS.md](AGENTS.md) lists project constraints and
verification commands; domain-specific manual scenarios live in the repository
[skills](.agents/skills/).

Release builds use thin LTO and one codegen unit. Connection reuse, bounded
concurrency and one-pass image compositing target the useful work in this bot.
Network/model latency still dominates post creation. No end-to-end speedup over
previous releases is claimed without comparable measurements.

## Assets and licensing

The application is AGPL-3.0-or-later. Bundled font, Android robot and fallback
artwork are unchanged; their source/license inventory is in
[`src/media/assets/README.md`](src/media/assets/README.md). Every banner retains
Android attribution and a NASA or generated-artwork credit.
