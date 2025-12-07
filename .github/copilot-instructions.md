# Copilot Instructions - AndroidRepo Bot

## Project Overview

Telegram bot (aiogram 3.x) for automating Android project posts in [@AndroidRepo](https://t.me/AndroidRepo). Fetches repository metadata from GitHub/GitLab, generates AI-powered summaries via pydantic-ai (GitHub Models API), and creates promotional banners with Pillow.

## Architecture & Data Flow

```
/post command → URL Parser → Repository Fetcher → AI Agent (Summary/Revision) → Banner Generator → Preview → Publish
                                    ↓                       ↓
                            GitHub/GitLab API       GitHub Models (GPT-4/GPT-5)
```

**Key components:**
- `src/bot/__main__.py` - Entry point with uvloop via `anyio.run(backend="asyncio", backend_options={"use_uvloop": True})`
- `src/bot/container.py` - DI via Dispatcher dict + startup/shutdown hooks (NOT a container class)
- `src/bot/integrations/repositories/fetchers/` - Abstract `BaseRepositoryFetcher` + GitHub/GitLab implementations
- `src/bot/integrations/ai/agents/` - `BaseAgent` + `SummaryAgent`/`RevisionAgent` with pydantic-ai structured outputs
- `src/bot/services/banner.py` - Pillow-based banner generation with Material Design color palette
- `src/bot/modules/post/handlers/` - Command handlers for post workflow (command → edit → publish)
- `src/bot/filters/` - Custom aiogram filters (`ChatFilter`, `TopicFilter`)

## Dependency Injection Pattern

Dependencies are stored in `Dispatcher` dict, NOT a container class. Access via function parameter names matching dict keys:

```python
# In container.py startup hook:
dp["github_fetcher"] = GitHubRepositoryFetcher(session=session, token=settings.resolved_github_token)

# In handlers:
async def handler(message: Message, github_fetcher: GitHubRepositoryFetcher): ...
```

**Available dependencies:** `settings`, `preview_registry`, `summary_agent`, `revision_agent`, `github_fetcher`, `gitlab_fetcher`, `telegram_logger`

## Async Patterns

- **Use `anyio` primitives exclusively** - NEVER use raw `asyncio` (e.g., `asyncio.gather`, `asyncio.create_task`)
- Parallel operations: `async with anyio.create_task_group() as tg: tg.start_soon(...)`
- Shared `aiohttp.ClientSession` with 30s timeout, created at startup, closed at shutdown
- Example: `src/bot/integrations/repositories/fetchers/github.py:fetch_repository()` - parallel API calls for repo metadata + README

## Code Conventions

### Required File Header
Every file MUST start with:
```python
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations
```

### Class Requirements
- **Always use `__slots__`** on all classes (including exceptions and dataclasses)
- Exception classes: inherit `RuntimeError`, define message format in `__init__`
- Line length: 120 chars (enforced by ruff)

Example exception:
```python
class MyError(RuntimeError):
    __slots__ = ("platform", "details")

    def __init__(self, platform: str, *, details: str | None = None) -> None:
        self.platform = platform
        self.details = details
        super().__init__(f"Error on {platform}: {details}")
```

### Documentation Style
- **NO docstrings** - code should be self-documenting through clear naming
- **NO comments** - avoid inline comments unless absolutely necessary for non-obvious logic

### Import Rules (enforced by ruff)
- **Absolute imports** for cross-package: `from bot.integrations.ai import ...`
- **Relative imports** only within same package: `from .errors import ...`
- **TYPE_CHECKING blocks** for type-only imports to avoid circular dependencies
- **type aliases**: use modern syntax `type MyType = ...` (requires Python 3.13+)

```python
if TYPE_CHECKING:
    from bot.integrations.repositories.models import RepositoryInfo

type SummaryOutput = RepositorySummary | RejectedRepository
```

### Pydantic Models
All models MUST be frozen with strict extra handling:
```python
class MyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")  # or extra="forbid" for strict validation
    field: str = Field(description="Always document fields")
```

### Logging
Use structlog with async methods:
```python
from bot.logging import get_logger

logger = get_logger(__name__)
await logger.ainfo("User action", user_id=123, action="post")  # Use async logging methods
await logger.aerror("API failure", platform="GitHub", status=500, error=str(exc))
```

## Development Commands

```bash
uv run python -m bot          # Run bot (add --debug for DEBUG level logs)
uv run ruff check --fix .     # Lint with auto-fix
uv run ruff format .          # Format code
uv run ty check               # Type checking (ty from Astral/uv)
```

## Module Structure & Registration

Modules are isolated feature packages in `src/bot/modules/`. Each module has:
- `__init__.py` - Setup function (e.g., `setup_post()`)
- `handlers/` - Routers for command/callback handling
- `utils/` - Module-specific utilities (models, messages, etc.)

**Registration flow:**
1. `src/bot/modules/__init__.py:register_modules()` - Called from `__main__.py`
2. Module setup function applies filters and registers routers
3. Example: `src/bot/modules/post/__init__.py:setup_post()` applies `ChatFilter`, `TopicFilter`, middleware, and includes routers

## Adding Features

### New Handler
1. Create `src/bot/modules/your_module/handlers/your_handler.py`:
```python
from aiogram import Router
router = Router(name="your-name")

@router.message(...)
async def handler(message: Message, dependency_name: DependencyType): ...
```
2. Include in module setup: `dp.include_router(your_handler.router)`
3. Inject deps via parameter names matching `dp[]` keys

### New Repository Platform
1. Create `src/bot/integrations/repositories/fetchers/your_platform.py`
2. Extend `BaseRepositoryFetcher`, implement abstract properties/methods:
   - `_headers` - HTTP headers (auth, user-agent, etc.)
   - `_platform_name` - Display name for logging/errors
   - `fetch_repository(owner, name)` - Returns `RepositoryInfo`
3. Add to `container.py` startup hook and export in `__init__.py`
4. Use `_make_request()` helper for API calls with automatic error handling

### New AI Agent
1. Create in `src/bot/integrations/ai/agents/your_agent.py`
2. Extend `BaseAgent[TDeps, TOutput]`:
```python
class YourAgent(BaseAgent[YourDeps, YourOutput]):
    def __init__(self, *, api_key: str) -> None:
        super().__init__(api_key=api_key, instructions=YOUR_INSTRUCTIONS)

    @classmethod
    def _get_output_type(cls) -> type[YourOutput]: ...

    @classmethod
    def _get_deps_type(cls) -> type[YourDeps]: ...

    def _register_instructions(self) -> None:
        @self._agent.instructions
        def provide_context(ctx: RunContext[YourDeps]) -> str: ...
```
3. Define models in `models.py`, prompts in `prompts.py`, errors in `errors.py`
4. Agent uses fallback model chain: GPT-5 → GPT-5-mini → GPT-4.1 → GPT-4.1-mini

## Configuration

Settings via `data/config.env` with `BOT_` prefix. See `src/bot/config.py:BotSettings`:

**Required:**
- `BOT_TOKEN` - Telegram bot token
- `BOT_GHMODELS_API_KEY` - GitHub Models API key
- `BOT_POST_CHANNEL_ID` - Target channel ID
- `BOT_POST_TOPIC_ID` - Target forum topic ID
- `BOT_LOGS_TOPIC_ID` - Logs topic ID
- `BOT_ALLOWED_CHAT_ID` - Chat ID where bot accepts commands

**Optional:**
- `BOT_GITHUB_TOKEN` - GitHub PAT for higher rate limits
- `BOT_GITLAB_TOKEN` - GitLab PAT for private repos

## Critical Patterns

### Error Handling
- Repository errors: `RepositoryNotFoundError`, `RepositoryClientError` (with platform, status, details)
- AI errors: `RepositorySummaryError`, `NonAndroidProjectError` (wraps pydantic-ai errors)
- Always log before raising: `await logger.aerror("Context", key=value)`

### State Management
- Uses aiogram FSM with `PostStates` enum
- Preview data stored in `PreviewDebugRegistry` (in-memory) with UUID keys
- Cleanup pattern: `await cleanup_messages(message, [msg1, msg2], state)` - deletes messages and resets state

### Banner Generation
- Material Design color palette (`MATERIAL_COLORS` tuple) - randomly selected per banner
- Fonts: Inter Bold/Regular from `data/` directory
- Layout: gradient background, dynamic font sizing (40-180px), channel logo footer
- Output: PNG bytes via `BytesIO`, no disk writes
