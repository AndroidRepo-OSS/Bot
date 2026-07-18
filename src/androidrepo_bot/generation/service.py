from asyncio import timeout
from collections.abc import Mapping
from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from pydantic_ai import Agent, InlineDefsJsonSchemaTransformer, ModelSettings, ToolOutput, UsageLimits
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from androidrepo_bot.errors import GenerationError
from androidrepo_bot.generation.prompt import POST_INSTRUCTIONS, build_generation_prompt
from androidrepo_bot.generation.schema import GeneratedPost
from androidrepo_bot.generation.validation import validate_generated_post
from androidrepo_bot.posts.models import PostDraft, PostLink
from androidrepo_bot.repositories.models import REPOSITORY_LINK_ID, RepositoryDetails

if TYPE_CHECKING:
    from pydantic_ai import RunUsage
    from pydantic_ai.models import Model

DEFAULT_MODEL_NAME = "deepseek-v4-flash"
_GENERATION_TIMEOUT_SECONDS = 120.0
OUTPUT_RETRIES = 2
MODEL_REQUEST_LIMIT = OUTPUT_RETRIES + 1
_MAXIMUM_DRAFT_LINKS = 5
_ZEN_API_BASE_URL = "https://opencode.ai/zen/v1"

logger = structlog.get_logger(__name__)

type PostAgent = Agent[RepositoryDetails, GeneratedPost]
type _LogValue = str | int | float | bool | None
type _LogContext = Mapping[str, _LogValue]


def create_zen_model(*, api_key: str, model_name: str) -> OpenAIChatModel:
    provider = OpenAIProvider(api_key=api_key, base_url=_ZEN_API_BASE_URL)
    profile = OpenAIModelProfile(
        supports_json_schema_output=False,
        supports_json_object_output=False,
        supports_inline_system_prompts=False,
        default_structured_output_mode="tool",
        json_schema_transformer=InlineDefsJsonSchemaTransformer,
        openai_supports_strict_tool_definition=False,
        openai_supports_tool_choice_required=False,
        openai_chat_supports_multiple_system_messages=False,
    )
    return OpenAIChatModel(model_name, provider=provider, profile=profile)


def create_post_agent(model: Model) -> PostAgent:
    agent = Agent[RepositoryDetails, GeneratedPost](
        model,
        name="android_repository_post",
        description="Generate one grounded Android Repository channel post.",
        deps_type=RepositoryDetails,
        output_type=ToolOutput(
            GeneratedPost, name="return_post_draft", description="Return the complete evidence-grounded post draft."
        ),
        instructions=POST_INSTRUCTIONS,
        model_settings=ModelSettings(temperature=0.2),
        retries={"output": OUTPUT_RETRIES},
    )
    agent.output_validator(validate_generated_post)
    return agent


class GenerationService:
    def __init__(self, *, agent: PostAgent) -> None:
        self._agent = agent

    async def generate(self, repository: RepositoryDetails, /) -> PostDraft:
        log_context: _LogContext = {
            "operation": "generation",
            "provider": repository.ref.provider.value,
            "repository": repository.ref.full_name,
            "timeout_seconds": _GENERATION_TIMEOUT_SECONDS,
        }
        started_at = perf_counter()
        logger.info(
            "Post AI operation started",
            **log_context,
            has_readme=repository.readme is not None,
            has_release=repository.release is not None,
            language_count=len(repository.languages),
            link_count=len(repository.links),
        )

        try:
            draft, usage = await self._generate_draft(repository, log_context)
        except Exception as error:
            logger.warning(
                "Post AI operation failed",
                **log_context,
                duration_seconds=perf_counter() - started_at,
                error_type=type(error).__name__,
                exc_info=True,
            )
            msg = "The post generation agent could not produce a draft"
            raise GenerationError(msg) from error

        logger.info(
            "Post AI operation completed",
            **log_context,
            duration_seconds=perf_counter() - started_at,
            model_requests=usage.requests,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            feature_count=len(draft.features),
            link_count=len(draft.links),
            tag_count=len(draft.tags),
        )
        return draft

    async def _generate_draft(
        self, repository: RepositoryDetails, log_context: _LogContext
    ) -> tuple[PostDraft, RunUsage]:
        stage_started_at = perf_counter()
        generation_prompt = build_generation_prompt(repository)
        logger.debug(
            "Post AI evidence prompt prepared", **log_context, duration_seconds=perf_counter() - stage_started_at
        )

        stage_started_at = perf_counter()
        async with timeout(_GENERATION_TIMEOUT_SECONDS):
            result = await self._agent.run(
                generation_prompt,
                deps=repository,
                model_settings=ModelSettings(timeout=_GENERATION_TIMEOUT_SECONDS),
                usage_limits=UsageLimits(request_limit=MODEL_REQUEST_LIMIT),
                metadata={"provider": repository.ref.provider.value, "repository": repository.ref.full_name},
            )
        logger.debug("Post AI model run completed", **log_context, duration_seconds=perf_counter() - stage_started_at)

        stage_started_at = perf_counter()
        draft = resolve_draft(repository, result.output)
        logger.debug(
            "Post AI draft resolved",
            **log_context,
            duration_seconds=perf_counter() - stage_started_at,
            feature_count=len(draft.features),
            link_count=len(draft.links),
            tag_count=len(draft.tags),
        )
        return draft, result.usage


def resolve_draft(repository: RepositoryDetails, generated: GeneratedPost) -> PostDraft:
    links_by_url: dict[str, PostLink] = {}
    repository_link = repository.link_by_id(REPOSITORY_LINK_ID)
    if repository_link is not None:
        links_by_url[repository_link.url] = PostLink(label=repository_link.label, url=repository_link.url)

    for selected_link in generated.links:
        if selected_link.id == REPOSITORY_LINK_ID:
            continue
        verified_link = repository.link_by_id(selected_link.id)
        if verified_link is None:
            continue
        links_by_url.setdefault(verified_link.url, PostLink(label=selected_link.label, url=verified_link.url))

    return PostDraft(
        title=generated.project_name,
        summary=generated.summary,
        features=generated.features,
        links=tuple(links_by_url.values())[:_MAXIMUM_DRAFT_LINKS],
        tags=generated.tags,
    )
