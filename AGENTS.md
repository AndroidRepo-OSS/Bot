# Repository Guidelines

## Project Structure & Module Organization

Runtime code uses a `src` layout under `src/androidrepo_bot/`. `app.py` is the composition root; `posts/` contains Telegram workflows, `repositories/` handles GitHub/GitLab data, `generation/` owns AI prompting and validation, `media/` renders banners and packages assets, and `db/` contains SQLAlchemy persistence plus Alembic migrations. Root-level files define packaging (`pyproject.toml`), linting (`ruff.toml`), migrations (`alembic.ini`), and containers (`Dockerfile`, `docker-compose.yaml`). Place tests in `tests/`, mirroring package paths.

## Build, Test, and Development Commands

- `uv sync --locked --all-groups`: install the locked Python 3.14 environment.
- `uv run ruff format --check .`: verify formatting without changing files.
- `uv run ruff check .`: run the configured lint rules.
- `uv run pyright`: perform strict static type checking.
- `uv run pre-commit run --all-files`: run repository-wide hygiene checks.
- `uv build`: build the wheel and source distribution.
- `docker compose up --build bot`: start PostgreSQL, apply migrations, and run the bot.
- `uv run androidrepo-bot`: run locally after configuring PostgreSQL and `.env`.

No test suite or test-runner dependency is currently tracked. Until one is added, lint, type, pre-commit, and build checks are the required verification baseline.

## Coding Style & Naming Conventions

Use four-space indentation, explicit type annotations, and asynchronous APIs for network or database work. Ruff enforces a 120-character line limit, import ordering, modern Python syntax, and numerous correctness rules. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants. Prefer absolute package imports and `structlog.get_logger()` for application logging.

## Commit & Pull Request Guidelines

Use Conventional Commits for every commit, following the
`<type>[optional scope][optional !]: <description>` format. Prefer common types such as `feat`, `fix`, `docs`, `refactor`,
`test`, `build`, `ci`, and `chore` (for example, `fix(repositories): validate GitLab subgroup URLs`). Keep descriptions
short, imperative, and lowercase, and keep unrelated changes in separate commits. Mark breaking changes with `!` and
explain them in a `BREAKING CHANGE:` footer. Pull requests should explain behavior and risks, link relevant issues, list
verification commands, and include screenshots for Telegram UI or banner changes. Call out schema, environment, or
asset-license changes explicitly.

## Security & Configuration

Copy `.env.example` to `.env`; never commit secrets or private Telegram content. Redact tokens, authorization headers, database credentials, and secret-bearing URLs from logs, fixtures, issues, and screenshots. Apply schema changes through committed Alembic revisions rather than editing databases manually.
