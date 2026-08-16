# Repository Instructions

## Project Scope

This repository contains a private Python 3.14 Telegram bot that turns public GitHub and GitLab repositories into
staff-reviewed Android Repository channel posts. Staff approval, evidence-grounded copy, duplicate-publication
prevention, and recoverable delivery are core product guarantees.

## Architecture

Runtime code lives in `src/androidrepo_bot/`.

- `app.py`: composition root, middleware, process lifecycle, and dependency wiring.
- `posts/`: Telegram commands, callbacks, typed FSM state, draft preparation, and publication workflow.
- `repositories/`: provider clients, URL parsing, bounded HTTP access, and repository evidence normalization.
- `generation/`: prompt, output schema, and model orchestration.
- `media/`: NASA asset lookup, banner rendering, and packaged assets.
- `db/`: SQLAlchemy models and operations plus packaged Alembic migrations.

Keep provider and Telegram details at their boundaries. Business workflows should depend on normalized data and explicit
outcomes rather than raw HTTP payloads, Telegram updates, or loosely typed dictionaries.

## Product Invariants

- Treat repository content, provider responses, model output, and Telegram input as untrusted. Bound reads, validate
  structure, and reject unsafe URLs or identifiers before use.
- Generated claims must be supported by inspected repository evidence. The model selects stable identifiers; application
  code resolves final URLs from validated evidence.
- Publication must remain durable and idempotent across retries, concurrent bot instances, database failures, and
  ambiguous Telegram delivery. Do not weaken reservation, receipt, compensation, cooldown, or reconciliation behavior.
- A failure after channel delivery must never silently permit a duplicate publication. Preserve enough durable state for
  safe staff reconciliation.
- Draft ownership and staff-chat/topic authorization must be enforced before state changes or publication.
- Logs and staff-facing errors must not expose credentials, authorization headers, private Telegram content, or
  secret-bearing URLs.

## Implementation Conventions

- Use explicit type annotations and asynchronous APIs for network, Telegram, and database I/O.
- Prefer absolute package imports and `structlog.get_logger()` for application logging.
- Keep side effects at module boundaries and make state transitions explicit. Use early returns for invalid or terminal
  states; keep the successful path easy to follow.
- Fix diagnostics at their source. Ruff and Pyright configuration define formatting, lint, and typing behavior.
- Keep changes focused. Avoid unrelated refactors, compatibility layers, or new abstractions without a concrete caller or
  invariant to protect.

## Database, Configuration, and Assets

- Apply schema changes with a new Alembic revision under `src/androidrepo_bot/db/migrations/versions/`. Do not rewrite an
  existing revision that may already be deployed.
- Keep database state transitions transactional. When behavior spans PostgreSQL and Telegram, account explicitly for the
  non-transactional external side effect and its recovery path.
- Add or remove dependencies with `uv` and commit `pyproject.toml` and `uv.lock` together.
- Reflect configuration changes in `.env.example` and the README configuration table. Never commit a real `.env` file.
- Preserve asset license files and update `src/androidrepo_bot/media/assets/README.md` when packaged assets change.

## Verification

Before handing off code, dependency, migration, or build-configuration changes, run the full verification sequence from
the repository root:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check --no-fix .
uv run pyright
uv run pre-commit run --all-files
uv build
```

For instruction-only or prose-only changes, run `uv run pre-commit run --all-files` at minimum. Pre-commit may modify
files; review its diff and rerun affected checks. Do not report a check as passing unless it completed successfully.

Use `docker compose up --build bot` only when integration behavior requires PostgreSQL, migrations, or a running bot.
Local execution uses `uv run androidrepo-bot` after PostgreSQL and `.env` are configured.

## Commits and Handoff

Use Conventional Commits: `<type>[optional scope][optional !]: <imperative lowercase description>`. Keep unrelated work
in separate commits. Mark breaking changes with `!` and a `BREAKING CHANGE:` footer.

Pull requests and handoffs must summarize behavior, risks, and verification. Call out schema, environment, dependency,
and asset-license changes explicitly. Include screenshots for visible Telegram UI or banner changes.
