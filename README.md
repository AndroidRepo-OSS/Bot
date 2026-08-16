# Android Repository Bot

Android Repository Bot turns a public GitHub or GitLab repository into a
reviewed Telegram channel post. Staff remain in control: the bot loads and
normalizes repository evidence, generates constrained English copy, renders a
1920 × 1080 PNG banner, and requires explicit confirmation before publication.

The project is one installable Python 3.14 application. Runtime code lives in
`src/androidrepo_bot`, and the `androidrepo-bot` console script and
`python -m androidrepo_bot` use the same entry point.

## What it preserves

- Public GitHub and GitLab repository-root URLs, including nested GitLab
  namespaces.
- Provider-stable repository identity and observed aliases in PostgreSQL.
- A three-calendar-month publication cooldown, based on PostgreSQL calendar
  arithmetic rather than a fixed number of days.
- Evidence-grounded structured generation with verified destination mapping.
- Staff review, regeneration, cancellation, final confirmation, and safe
  publication retry behavior.
- Full HD banners with attributed NASA artwork or a bundled offline fallback.
- Best-effort staff audit messages and structured, secret-redacted process logs.

## Quick start with Docker Compose

Requirements:

- Docker with Compose
- a Telegram bot with access to the configured staff chat, topics, and channel
- an OpenCode Zen API key

Copy the environment template and replace every required placeholder:

```bash
cp .env.example .env
```

Build and start the bot:

```bash
docker compose up --build bot
```

Compose starts PostgreSQL, waits for its health check, runs the dedicated
`migrate` service through `alembic upgrade head`, and starts the bot only after
migrations succeed. Database data remains in the `postgres-data` named volume.
The bot and migration containers run with all Linux capabilities dropped and
`no-new-privileges` enabled; the application image runs as an unprivileged
`androidrepo` user.

To apply migrations without starting the bot:

```bash
docker compose up --build migrate
```

The Compose PostgreSQL service is intentionally not published to the host. Use
the complete Compose stack above, or provide a separately reachable PostgreSQL
server for a host-run bot.

## Local development

Requirements:

- Python 3.14
- [`uv`](https://docs.astral.sh/uv/)
- PostgreSQL reachable from the host

Install the locked application and all development groups:

```bash
uv sync --locked --all-groups
```

Copy `.env.example` to `.env`, replace the placeholders, and change
`AR_DATABASE_URL` to the host-reachable PostgreSQL URL. Alembic reads
`AR_DATABASE_URL` from the process environment rather than loading `.env`
itself, so apply migrations explicitly:

```bash
AR_DATABASE_URL='postgresql+asyncpg://user:password@localhost:5432/androidrepo' \
  uv run alembic upgrade head
```

Run either supported entry point:

```bash
uv run androidrepo-bot
uv run python -m androidrepo_bot
```

At startup, the application validates settings, opens one shared
`aiohttp.ClientSession`, verifies PostgreSQL connectivity, enters the
PydanticAI agent, registers Telegram commands, and begins polling. Shutdown
stops admission of new work, drains admitted update handlers, emits a
best-effort stop audit, and closes resources through one central
`AsyncExitStack`.

## Configuration

Settings come from `.env` and process environment variables prefixed with
`AR_`; process environment values take precedence. Empty optional token values
are ignored. See [`.env.example`](.env.example) for annotated placeholders.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `AR_BOT_TOKEN` | yes | — | Telegram bot token |
| `AR_STAFF_CHAT_ID` | yes | — | Staff chat admitted to the post workflow |
| `AR_POST_TOPIC_ID` | yes | — | Staff topic for `/post`, `/cancel`, `/reconcile`, and draft callbacks |
| `AR_LOG_TOPIC_ID` | yes | — | Staff topic receiving best-effort operational audits |
| `AR_CHANNEL_ID` | yes | — | Channel receiving confirmed posts |
| `AR_OPENCODE_ZEN_API_KEY` | yes | — | OpenCode Zen generation credential |
| `AR_DATABASE_URL` | yes | — | `postgresql+asyncpg://` runtime database URL |
| `AR_LOG_LEVEL` | no | `INFO` | `CRITICAL`, `ERROR`, `WARNING`, `INFO`, or `DEBUG` |
| `AR_OPENCODE_ZEN_MODEL` | no | `deepseek-v4-flash` | OpenCode Zen model identifier |
| `AR_GITHUB_TOKEN` | no | — | Token for authenticated GitHub API requests |
| `AR_GITLAB_TOKEN` | no | — | Token for authenticated GitLab API requests |

The staff chat and channel IDs must be non-zero, and both topic IDs must be
positive. The database URL must use SQLAlchemy's `postgresql+asyncpg` driver.

Never commit `.env`. Do not put credentials, authorization headers, database
passwords, private chat content, or secret-bearing URLs in logs, screenshots,
issues, or pull requests.

## Telegram behavior

### Access

`/start` is admitted in any chat and links to the source repository, Android
Repository channel, and community. Every other handled update must belong to
the configured staff chat and post topic. Updates outside that scope are
ignored.

Draft state uses aiogram's in-memory storage with per-user-in-chat isolation.
An active draft therefore does not survive a process restart, while repository
identity and publication history remain persistent in PostgreSQL.

### Create and review a draft

1. Send `/post` followed by a public repository-root URL:

   ```text
   /post https://github.com/owner/repository
   /post https://gitlab.com/group/subgroup/repository
   ```

2. With no argument, `/post` shows the expected URL form. An invalid URL gets a
   specific rejection without replacing an active draft.
3. The parser accepts HTTPS GitHub and GitLab roots only. It rejects embedded
   credentials, custom ports, query strings, fragments, encoded or malformed
   paths, GitHub subpaths, and GitLab `/-/` subresources.
4. After a new URL is valid, the bot deactivates the previous owned draft
   controls and replaces its active session.
5. The bot loads normalized provider metadata, README content when available,
   latest-release metadata, languages, license, topics, homepage, and verified
   links. Missing README content is allowed; the resulting draft uses metadata
   only and the bot sends a warning.
6. The provider-stable identity and requested/canonical aliases are upserted.
   The cooldown is checked before generation and banner rendering. A blocked
   request is stored as an audited attempt.
7. The bot generates, validates, renders, and sends a review message with
   **Publish**, **Regenerate**, and **Cancel** controls.

Generation treats every repository string, including README and release text,
as untrusted evidence. Only the first 50,000 README characters are supplied.
The structured result requires a project name, one summary, three to five
distinct features, one to three supported tags, and at most four optional link
selections. The output schema enforces plain text, field bounds, and distinct
values; the service verifies destination IDs, the download decision, and the
950-character generation budget. Editorial guidance such as canonical naming,
semantic link labels, and non-redundant prose stays in the generation prompt.
The agent may make at most three model requests: the initial request and two
output-correction retries. Each complete generation run has a 120-second
deadline.

The model never supplies a destination URL to the final post. It selects stable
IDs from inspected evidence; the service resolves those IDs through the same
repository snapshot and always adds the mandatory repository destination.
Unknown, mandatory-as-optional, and unresolved selections are not mapped.

The final Telegram caption contains the title, italic summary, key features,
verified links, and hashtags, and is checked against Telegram's 1,024-character
photo-caption limit.

### Regenerate, cancel, and publish

- **Regenerate** uses the already loaded repository snapshot. The existing
  usable draft remains active if generation, rendering, or Telegram delivery
  fails. A successful replacement is stored before deletion of the old draft
  is attempted.
- **Cancel** and `/cancel` clear the session and delete the draft and optional
  missing-README notice on a best-effort basis.
- **Publish** first switches to an explicit confirmation screen. **Back**
  returns to the draft without publishing; **Publish now** performs the
  channel copy.
- Callbacks must belong to the session owner and originate from the active
  draft message. Stale, foreign, and malformed callbacks receive an alert and
  cannot mutate or publish the session.

`PublicationWorkflow` reserves one durable publication operation per
repository before copying to the channel. A PostgreSQL transaction-level
advisory lock and a unique open-operation constraint serialize concurrent
attempts across bot instances, while the cooldown is checked under the same
lock. The Telegram receipt and Publication record are then stored atomically.

If that write fails, the workflow persists its compensation intent before
deleting the channel copy. A failed deletion is conservatively recorded as a
Publication so its cooldown applies. An ambiguous delivery or interrupted
compensation keeps the repository unavailable until staff inspect the channel
and resolve the operation with `/reconcile`; reconciliation never performs a
second copy. If Telegram rejects a copy definitively, the Draft remains
available for another attempt.

The staff log topic receives best-effort lifecycle, draft creation/failure,
replacement/cancellation, publication success/failure, and recovery details.
Failure to deliver an audit message does not fail the underlying workflow.

## Architecture

```text
src/androidrepo_bot/
├── app.py              # composition root, Telegram middleware, lifecycle
├── config.py           # validated AR_* settings
├── start.py            # global /start presentation
├── posts/              # composed routes, draft/publication workflows, FSM, and UI
├── repositories/       # URL parsing, shared HTTP policy, GitHub/GitLab
├── generation/         # evidence prompt, output schema, AI orchestration
├── media/              # NASA artwork and packaged banner renderer assets
└── db/                 # SQLAlchemy models, operations, packaged migrations
```

`app.py` directly composes concrete services. Repository and NASA access share
one application-owned HTTP session; PostgreSQL uses operation-scoped async
sessions; the application owns the bot, database engine, and generation-agent
lifecycle. There are no internal workspace distributions or compatibility
layers.

The posts package exposes command and callback routers. Its handlers translate
Telegram updates, while `DraftWorkflow` owns draft preparation and
`PublicationWorkflow` owns the complete publication, compensation, and
reconciliation protocol.
Typed draft sessions live directly in aiogram's in-memory FSM storage through
`state.py`; Telegram-specific session message operations stay in `telegram.py`.

Repository provider responses are bounded, parsed as untrusted JSON, and
validated before normalization. Transient provider failures use bounded
retries, and safe user messages distinguish not-found, rate-limit, timeout, and
temporary-provider failures.

## PostgreSQL and migrations

Alembic configuration is in [`alembic.ini`](alembic.ini). Migration scripts are
packaged under `androidrepo_bot.db.migrations`, alongside the installed
application.

The schema stores:

- provider-stable repository identities and observed aliases
- successful channel publications
- durable publication operations, including unresolved delivery and compensation states
- cooldown-blocked attempts

The current migrations preserve first-seen identity data, normalize aliases,
enforce blocked-attempt and publication-operation state shapes, deduplicate
legacy Publication records, and make channel receipts unique. Do not stamp or
edit a production schema manually; apply committed revisions with:

```bash
AR_DATABASE_URL='postgresql+asyncpg://user:password@host:5432/androidrepo' \
  uv run alembic upgrade head
```

## Banners and asset attribution

The banner renderer attempts to load a curated image from the NASA Image and
Video Library. Remote image downloads are restricted to NASA's HTTPS asset
host, bounded to 12 MiB, and time-limited. Invalid, unavailable, or undecodable
artwork falls back to the packaged black-hole image. Every result is a 1920 ×
1080 RGB PNG and includes visible artwork credit and identifier text.

Bundled assets and their requirements are listed in the
[asset inventory](src/androidrepo_bot/media/assets/README.md):

- The Android robot artwork is based on work created and shared by Google and
  is used under the Creative Commons 3.0 Attribution License terms referenced
  by the Android brand guidelines. The renderer includes the attribution.
- Figtree is redistributed under the SIL Open Font License; its complete
  license text is packaged beside the font.
- `black-hole-fallback.webp` was generated with OpenAI for this repository.

Keep the asset inventory and license files with redistributed builds.

## Development and verification

Run checks from the repository root:

```bash
uv lock --check
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pre-commit run --all-files
uv build
```

Pyright runs in strict mode across runtime code.

The built wheel must contain the complete package, database migrations, banner
assets, and `androidrepo-bot` console-script metadata. The package is marked
`Private :: Do Not Upload`.

## License and support

Copyright (C) 2026 Hitalo M.

This project is licensed under the GNU Affero General Public License, version 3
or later ([AGPL-3.0-or-later](LICENSE)). Modified versions offered for remote
network interaction must provide corresponding source as required by AGPL
section 13.

Use the repository's
[GitHub issues](https://github.com/AndroidRepo-OSS/Bot/issues) for reproducible
bugs and scoped improvements. Never include secrets or private Telegram
content in a report.
