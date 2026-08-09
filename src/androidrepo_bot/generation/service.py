from asyncio import timeout
from collections.abc import Mapping
from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from pydantic_ai import Agent, InlineDefsJsonSchemaTransformer, ModelSettings, ToolOutput, UsageLimits
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from androidrepo_bot.errors import GenerationError, MissingDownloadSourceError, NotAndroidProjectError
from androidrepo_bot.generation.prompt import POST_INSTRUCTIONS, build_generation_prompt
from androidrepo_bot.generation.schema import GeneratedOutput, GeneratedPost, MissingDownloadSource, NotAndroidProject
from androidrepo_bot.generation.types import GenerationContext
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

type PostAgent = Agent[GenerationContext, GeneratedOutput]
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
    agent = Agent[GenerationContext, GeneratedOutput](
        model,
        name="android_repository_post",
        description="Generate one grounded Android Repository channel post.",
        deps_type=GenerationContext,
        output_type=[
            ToolOutput(
                GeneratedPost, name="return_post_draft", description="Return the complete evidence-grounded post draft."
            ),
            ToolOutput(
                NotAndroidProject,
                name="not_android_project",
                description="Return an error when the evidence does not directly support Android relevance.",
            ),
            ToolOutput(
                MissingDownloadSource,
                name="missing_download_source",
                description="Return a warning when no official install or release download source is available.",
            ),
        ],
        instructions=POST_INSTRUCTIONS,
        model_settings=ModelSettings(temperature=0.2),
        retries={"output": OUTPUT_RETRIES},
    )
    agent.output_validator(validate_generated_post)
    return agent


class GenerationService:
    def __init__(self, *, agent: PostAgent) -> None:
        self._agent = agent

    async def generate(self, repository: RepositoryDetails, /, *, allow_missing_download: bool = False) -> PostDraft:
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
            output, usage = await self._generate_output(
                repository, log_context, allow_missing_download=allow_missing_download
            )
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

        if isinstance(output, NotAndroidProject):
            raise NotAndroidProjectError(output.reason)
        if isinstance(output, MissingDownloadSource):
            raise MissingDownloadSourceError(output.reason)

        draft = resolve_draft(repository, output)

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

    async def _generate_output(
        self, repository: RepositoryDetails, log_context: _LogContext, *, allow_missing_download: bool
    ) -> tuple[GeneratedOutput, RunUsage]:
        stage_started_at = perf_counter()
        generation_prompt = build_generation_prompt(repository, allow_missing_download=allow_missing_download)
        logger.debug(
            "Post AI evidence prompt prepared", **log_context, duration_seconds=perf_counter() - stage_started_at
        )

        stage_started_at = perf_counter()
        async with timeout(_GENERATION_TIMEOUT_SECONDS):
            result = await self._agent.run(
                generation_prompt,
                deps=GenerationContext(repository=repository, allow_missing_download=allow_missing_download),
                model_settings=ModelSettings(timeout=_GENERATION_TIMEOUT_SECONDS),
                usage_limits=UsageLimits(request_limit=MODEL_REQUEST_LIMIT),
                metadata={"provider": repository.ref.provider.value, "repository": repository.ref.full_name},
            )
        logger.debug("Post AI model run completed", **log_context, duration_seconds=perf_counter() - stage_started_at)

        stage_started_at = perf_counter()
        logger.debug(
            "Post AI output resolved",
            **log_context,
            duration_seconds=perf_counter() - stage_started_at,
            output_type=type(result.output).__name__,
        )
        return result.output, result.usage


def resolve_draft(repository: RepositoryDetails, generated: GeneratedPost) -> PostDraft:
    download_link = (
        repository.link_by_id(generated.download_link_id) if generated.download_link_id is not None else None
    )
    if generated.download_link_id is not None and download_link is None:
        msg = "Generated download link must resolve to a verified repository destination"
        raise ValueError(msg)

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
        download_url=download_link.url if download_link is not None else None,
        tags=generated.tags,
    )
