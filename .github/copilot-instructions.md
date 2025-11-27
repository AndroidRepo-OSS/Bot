# Copilot Instructions - AndroidRepo Bot

## Project Overview

Telegram bot (aiogram 3.x) for sharing Android projects in the Android Repository channel. Fetches repository metadata from GitHub/GitLab, generates AI-powered summaries via pydantic-ai, and creates promotional banners with Pillow.

## Architecture & Data Flow

```
User Message → Handler → Repository Fetcher → AI Summary Agent → Banner Generator → Telegram Response
                              ↓                      ↓
                      GitHub/GitLab API      OpenAI-compatible API
```

**Key directories:**
- `src/bot/__main__.py` - Entry point with uvloop via `anyio.run(backend_options={"use_uvloop": True})`
- `src/bot/container.py` - DI via Dispatcher's startup/shutdown hooks (not a class container)
- `src/bot/integrations/repositories/` - Abstract `BaseRepositoryFetcher` + platform implementations
- `src/bot/integrations/ai/client.py` - `RepositorySummaryAgent` with pydantic-ai structured output
- `src/bot/services/banner.py` - Pillow-based banner generation with Material Design colors

### Dependency Injection Pattern

Dependencies are injected via `Dispatcher` dict, NOT a container class. See `container.py`:
```python
dp["github_fetcher"] = GitHubRepositoryFetcher(session=session, token=...)
# Access in handlers via parameter name matching the key:
async def handler(message: Message, github_fetcher: GitHubRepositoryFetcher): ...
```

### Async Patterns

- Use `anyio.create_task_group()` for parallel API calls (see `github.py:fetch_repository`)
- Shared `aiohttp.ClientSession` with 30s timeout, created at startup, closed at shutdown
- NEVER use raw `asyncio` - always prefer `anyio` primitives

## Code Conventions

### Required File Header
```python
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations
```

### Class Requirements
- **Always use `__slots__`** on all classes (exceptions included)
- Exception classes: inherit `RuntimeError`, define attributes in `__slots__`
- Line length: 120 chars (see `ruff.toml`)

### Import Rules (enforced by ruff)
- **Absolute imports** for cross-package: `from bot.integrations.ai import ...`
- **Relative imports** only within same package: `from .errors import ...`
- **TYPE_CHECKING blocks** for type-only imports to avoid circular deps

### Pydantic Models
```python
class MyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")  # Always frozen
    field: str = Field(description="Always document fields")
```

### Logging
Use structlog via `from bot.logging import get_logger`:
```python
logger = get_logger(__name__)
await logger.ainfo("Message", key=value)  # Use async logging methods
```

## Development Commands

```bash
uv run python -m bot          # Run bot
uv run ruff check --fix .     # Lint with auto-fix
uv run ruff format .          # Format code
uv run pyright                # Type checking
```

## Adding Features

### New Handler
1. Create `src/bot/handlers/your_handler.py` with `router = Router(name="your_name")`
2. Register in `handlers/__init__.py`: `dp.include_router(your_handler.router)`
3. Inject deps via parameter names matching `dp[]` keys from `container.py`

### New Repository Platform
1. Create `src/bot/integrations/repositories/your_platform.py`
2. Extend `BaseRepositoryFetcher`, implement: `_headers`, `_platform_name`, `fetch_repository()`
3. Add to `container.py` startup hook and export in `__init__.py`

### New AI Agent
1. Create in `src/bot/integrations/ai/` following `client.py` pattern
2. Use `pydantic_ai.Agent` with `output_type=YourModel`, `deps_type=YourDeps`
3. Define structured output model in `models.py`, errors in `errors.py`

## Configuration

All settings via `data/config.env` with `BOT_` prefix. Required vars:
- `BOT_TOKEN` - Telegram bot token
- `BOT_OPENAI_API_KEY` - OpenAI-compatible API key
- `BOT_POST_TOPIC_ID` - Target forum topic ID
- Optional: `BOT_GITHUB_TOKEN`, `BOT_GITLAB_TOKEN`, `BOT_OPENAI_BASE_URL`
