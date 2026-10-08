# Android Repository Bot

Private Python 3.14 application that turns public GitHub/GitLab evidence into
staff-approved Telegram posts. Read the relevant implementation before editing;
prefer direct, typed code and the existing libraries over generic frameworks.

## Code map

- `app.py`: CLI entry point, composition, and resource ownership.
- `dispatcher.py`: aiogram admission, graceful draining, and safe error reporting.
- `posts/`: command/callback routes, Telegram UI, native FSM, drafts, and publication.
- `repositories/`: provider clients, normalized evidence, URL parsing, and links.
- `http.py`: shared HTTP session and bounded response reads.
- `generation/`: combined output models, prompts, and agent execution functions.
- `media/`: NASA assets, validated media values, Pillow rendering, bundled licenses.
- `db/`: SQLAlchemy transactions and packaged Alembic revisions.

## Invariants

- Admit workflow actions only from the configured staff chat/topic. Bind draft
  and download-confirmation callbacks to their owner and active message.
- Fetch only public repositories. Bound and validate provider/model/Telegram
  input. Generated links resolve from inspected evidence, never model URLs.
- Commit a durable reservation before channel delivery. Preserve receipt,
  cooldown, compensation, reconciliation, and cross-process locking behavior.
  Uncertain delivery must block a second copy until staff reconciliation.
- Drain admitted work before closing HTTP, database, agent, or FSM resources.
  Keep cancellation and external side effects explicit.
- Log safe context and exception types. Never expose tokens, raw provider/model
  errors, private Telegram content, or secret-bearing URLs.

## Implementation

Use Python 3.14 typing, absolute package imports, async I/O, and
`structlog.get_logger()`. Prefer aiogram filters, callback data, middleware,
formatting, flags, and dependency injection. Use Pydantic for input constraints
and immutable dataclasses for internal workflow values where appropriate.

Keep responsibilities at existing boundaries. Remove unused layers and repeated
state rather than adding compatibility adapters. Comment recovery assumptions
and non-obvious constraints. Fix diagnostics at their source; do not introduce
lint/type suppressions or weaken strict checking.

Add/remove dependencies with `uv`; update `pyproject.toml` and `uv.lock`
together. Validate changes against the resolved library versions. New schema
changes require a new Alembic revision; do not edit deployed revisions. Reflect
configuration changes in `.env.example` and the README table. Preserve asset
attribution and license files.

Do not add test suites, fixtures, or eval datasets unless explicitly requested.
Temporary, offline smoke commands are useful when they check behavior beyond
static analysis. Do not run paid generation or send real Telegram messages as
an incidental verification step.

## Verification and handoff

From the repository root, run:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check --no-fix .
uv run pyright
uv run pre-commit run --all-files
uv build
```

For prose/instruction-only edits, run pre-commit at minimum. Review its changes
and repeat affected checks. Do not claim a check passed before it completes.
Use disposable PostgreSQL for database integration when available; disclose
when migration/concurrency verification was limited to offline checks.

Summarize behavior, risks, and actual verification. Explicitly state schema,
environment, dependency, and asset-license changes. Include a rendered example
for visible Telegram/banner changes. Use Conventional Commits if committing;
do not combine unrelated user work.

## Local skills

The repository-maintained skills in `.agents/skills/` cover Telegram workflows,
durable publication, and evidence boundaries. They contain project-specific
constraints; use only the skill relevant to the task. They are local sources,
not vendor skill snapshots.
