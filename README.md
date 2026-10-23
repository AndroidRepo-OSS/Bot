# Android Repository Bot

A Rust Telegram bot that turns public GitHub/GitLab evidence into reviewed
Android Repository channel posts. Staff load a repository, review a generated
English caption and 1920 × 1080 banner, then explicitly confirm publication.

One binary owns the HTTP connection pool, PostgreSQL pool, bounded rendering
work and teloxide dispatcher in a single Rust module tree.

## Build and run

Install [Rust through rustup](https://www.rust-lang.org/tools/install) and provide
a reachable PostgreSQL server. `rust-toolchain.toml` pins Rust 1.99.1 with Clippy
and rustfmt. Native builds need a C/C++ compiler, CMake and pkg-config for the
TLS dependencies.

```bash
cargo build --release --locked
cp .env.example .env
# Fill in your Telegram, OpenCode and reachable PostgreSQL settings.
cargo run --release --locked -- check-config
cargo run --release --locked -- migrate
cargo run --release --locked -- run
```

No subcommand defaults to `run`. `check-config` does not contact any service;
`migrate` requires only `AR_DATABASE_URL`. Both read `.env`, with process
environment values taking precedence.

Create the PostgreSQL database and user before running `migrate`. Run migrations
successfully before starting the bot. Assets and SQL migrations are embedded in
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

| Variable | Required for polling | Default | Purpose |
| --- | --- | --- | --- |
| `AR_BOT_TOKEN` | yes | — | Telegram bot credential |
| `AR_STAFF_CHAT_ID` | yes | — | Staff supergroup, nonzero ID |
| `AR_POST_TOPIC_ID` | yes | — | Positive staff workflow topic ID |
| `AR_LOG_TOPIC_ID` | yes | — | Positive topic ID for best-effort audits |
| `AR_CHANNEL_ID` | yes | — | Target channel, nonzero ID |
| `AR_OPENCODE_ZEN_API_KEY` | yes | — | OpenCode Console API credential |
| `AR_DATABASE_URL` | yes | — | `postgresql://` or `postgres://` URL |
| `AR_LOG_LEVEL` | no | `INFO` | `CRITICAL`, `ERROR`, `WARNING`/`WARN`, `INFO`, `DEBUG` |
| `AR_OPENCODE_ZEN_MODEL` | no | `mimo-v2.6-flash-free` | Model with Chat Completions tool calling |
| `AR_GITHUB_TOKEN` | no | — | Optional GitHub API token |
| `AR_GITLAB_TOKEN` | no | — | Optional GitLab API token |

The `AR_OPENCODE_ZEN_*` names are retained for existing deployments. Generation
uses the current OpenCode endpoint
`https://opencode.ai/inference/openai/v1/chat/completions`. Choose a model that
supports that API and tool calls; models exposed only through Responses or
Anthropic Messages are not interchangeable. Free model availability is temporary;
consult the [provider's current model documentation](https://opencode.ai/v2/docs/console/models/).

Never commit `.env` or log credentials, raw external errors or private chat text.

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
stored in PostgreSQL.

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
Repository advisory locks and a unique open-operation index serialize bot
instances. The cooldown is three PostgreSQL calendar months, calculated in UTC.
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
├── config.rs               # AR_* settings; secrets have no Debug representation
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
migrations/                 # embedded SQLx revisions
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

Stop the bot and back up PostgreSQL before migration. Existing installations
with Alembic history must first reach `20260812_0003` using the previous release.
The Rust baseline adopts that version without recreating tables or deleting
history. Fresh databases get the same baseline. Unknown or older schemas are
rejected. The next SQL migration permits compensation leases on the existing
operation table; no credentials or media assets change.

Historical Alembic sources are available in Git history. The Rust binary embeds
and applies numbered SQL files through SQLx. Its existing SQL revisions retain
database adoption metadata for compatibility with deployed databases.
Never edit a deployed SQL revision; add a new migration. Rollback to an old
binary requires draining/reconciling operations first because the old bot does
not understand active compensation leases.

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
There is no Rust test suite. See [manual validation](docs/validation.md) for the
performed checks and how to repeat the relevant scenarios safely.

Release builds use thin LTO and one codegen unit. Connection reuse, bounded
concurrency and one-pass image compositing target the useful work in this bot.
Network/model latency still dominates post creation. No end-to-end speedup over
previous releases is claimed without comparable measurements. Source references and
architecture decisions are recorded in [rewrite notes](docs/rewrite.md).

## Assets and licensing

The application is AGPL-3.0-or-later. Bundled font, Android robot and fallback
artwork are unchanged; their source/license inventory is in
[`src/media/assets/README.md`](src/media/assets/README.md). Every banner retains
Android attribution and a NASA or generated-artwork credit.
