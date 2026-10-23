# Android Repository Bot

Private Rust 2024 application for staff-reviewed Telegram posts. Prefer direct,
typed code and concrete services; Python is historical context, not an
architecture to reproduce. Keep one binary and a module tree unless a real
boundary justifies another crate.

## Code map

- `src/main.rs`: CLI, configuration and resource composition.
- `src/bot/`: teloxide dispatch/state, commands/callbacks, draft preparation,
  Telegram UI and publication effects.
- `src/repositories/`: strict repository roots, provider-specific fetches,
  normalized evidence and inert README links.
- `src/generation/`: bounded evidence, tool-call output validation and inference.
- `src/media/`: trusted NASA assets, bounded decoding and blocking-pool rendering.
- `src/db/`: SQLx transactions, registration and durable publication transitions.
- `migrations/`: immutable SQL revisions; `legacy-alembic/` is audit-only history.

## Invariants

- Only `/start` is public. Admit other actions only in the configured staff
  chat/topic. Bind callbacks to owner, active message and workflow phase.
- Verify public repository visibility even with tokens. Bound external reads;
  redirects remain disabled. Resolve post URLs from inspected link IDs only.
- Commit a reservation before channel copy. Never automatically retry a copy.
  An expired lease or ambiguous response blocks publication until reconciliation.
- Take the repository advisory lock before an operation row lock. Use the
  database clock after lock waits. Preserve unique open operations/receipts,
  three-calendar-month cooldown and compensation leases.
- Drain admitted dispatcher work before resource teardown. Never cancel/drop the
  publication future after receiving a Telegram receipt.
- Log safe error categories and numeric operation context. Never log raw
  provider/model/Telegram/database errors, request bodies, tokens or private text.

## Implementation

Use the pinned stable toolchain, standard Rust naming, serde at JSON boundaries,
Tokio for I/O, tracing for safe events, and `spawn_blocking` for CPU rendering.
Prefer enums for actual alternatives and borrowing/Arc over cloning evidence.
Do not add generic service traits, adapters, global caches, unsafe code, lint
suppressions or custom allocators without a concrete need.

Keep teloxide pinned to an explicitly inspected Git revision and commit
Cargo.toml/Cargo.lock changes together. Consult current official APIs when
changing dependency usage. New schema changes need a new SQL migration; never
edit deployed migrations. Reflect settings changes in `.env.example` and the
README table. Preserve bundled asset bytes, licenses and rendered attribution.

Do not add Rust test suites, fixtures or eval datasets unless explicitly asked.
Use temporary manual probes, public read-only API checks, offline rendering and
isolated PostgreSQL. Do not call paid generation or send real Telegram messages
as incidental verification.

## Verification

```bash
cargo metadata --locked --format-version 1 --no-deps > /dev/null
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo build --release --locked
cargo doc --locked --no-deps
pre-commit run --all-files
```

For prose-only changes run pre-commit at minimum. Review formatter changes and
repeat affected checks. For publication/schema changes exercise a disposable
PostgreSQL database; disclose offline-only limitations. For visible changes,
render and inspect an example. `docs/validation.md` records manual scenarios.

Summarize behavior, risks and completed verification. Explicitly state schema,
environment, dependency and asset-license changes. Do not claim a speedup without
comparable measurements. Use Conventional Commits if committing; keep unrelated
user work separate.

Use the relevant repository skill in `.agents/skills/` for evidence, Telegram or
publication changes. Instructions follow the official OpenAI
[AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) and
[skills](https://learn.chatgpt.com/docs/build-skills) guidance; keep them focused
on this application's non-obvious boundaries.
