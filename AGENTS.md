# Android Repository Bot

Private Rust 2024 application for staff-reviewed Telegram posts. One binary owns
HTTP/database pools, bounded rendering and the teloxide dispatcher. Prefer direct,
typed code and concrete services within the existing module tree.

## Code and skills

- `src/main.rs`: CLI, settings and resource composition.
- `src/bot/`: Telegram handlers, draft state, UI and publication effects.
- `src/repositories/`, `src/generation/`, `src/media/`: public evidence,
  validated generation and attributed banners; independent of Telegram.
- `src/db/`, `migrations/`: direct SQLx transactions and immutable SQL revisions.

Use the relevant skill in `.agents/skills/` for its domain:

- `androidrepo-evidence`: repository/provider reads, README links, generated
  output validation and NASA artwork handling.
- `androidrepo-telegram`: commands, callback admission, drafts, UI and shutdown.
- `androidrepo-publication`: reservations, delivery, persistence, compensation,
  cooldown and reconciliation; read alongside Telegram guidance when both apply.

## Project constraints

- Only `/start` is public. Other actions require the configured staff chat/topic;
  callbacks are bound to owner, active message and workflow phase.
- Verify public repository visibility even with tokens. Bound external reads,
  disable redirects and resolve post URLs only from inspected evidence IDs.
- Commit a reservation before channel copy; never retry a copy automatically.
  Ambiguous delivery or an expired lease blocks publication until reconciliation.
  Drain admitted work before resource teardown; retain publication futures after
  receiving a Telegram receipt.
- Log safe error categories and numeric operation context. Never log raw external
  errors, request bodies, credentials or private text.
- Keep the pinned toolchain and teloxide Git revision. Inspect official APIs when
  changing dependency usage; update Cargo.toml/Cargo.lock together. Use Tokio for
  I/O, serde at JSON boundaries and bounded `spawn_blocking` for CPU rendering.
- Preserve the existing module boundaries. Add abstractions only for a concrete
  need; avoid generic service layers, global caches and custom allocators. Keep
  unsafe code forbidden and do not suppress lints to hide failures.
- Add migrations for schema changes; never edit deployed revisions. Reflect
  settings changes in `.env.example` and the README configuration table. Preserve
  bundled asset bytes, licenses and rendered attribution.
- Do not add Rust test suites, fixtures or eval datasets unless explicitly asked.
  Use temporary probes, public read-only APIs, offline rendering, isolated
  PostgreSQL and local Telegram stubs. Do not call paid generation or send real
  Telegram messages as incidental verification.

## Verification

For code/dependency changes run:

```bash
cargo metadata --locked --format-version 1 --no-deps > /dev/null
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo build --release --locked
cargo doc --locked --no-deps
pre-commit run --all-files
```

For prose-only changes run pre-commit at minimum. Include new unstaged files
explicitly because `--all-files` checks tracked files. Review formatter changes
and repeat affected checks. Domain skills describe manual scenarios; choose those
relevant to the change. Publication/schema changes require disposable PostgreSQL;
visible changes require rendering and inspection. Report offline limitations.

Summarize behavior, risks and completed verification, including schema,
environment, dependency and asset-license changes. Claim performance improvements
only with comparable measurements. Use Conventional Commits if committing and
keep unrelated user work separate.
