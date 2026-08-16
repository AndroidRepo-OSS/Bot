from asyncio import timeout
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from pydantic_ai import (
    Agent,
    InlineDefsJsonSchemaTransformer,
    ModelRetry,
    ModelSettings,
    RunContext,
    ToolOutput,
    UsageLimits,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from androidrepo_bot.errors import GenerationError, MissingDownloadSourceError, NotAndroidProjectError
from androidrepo_bot.generation.prompt import DRAFT_TEXT_BUDGET, POST_INSTRUCTIONS, build_generation_prompt
from androidrepo_bot.generation.schema import GeneratedOutput, GeneratedPost, MissingDownloadSource, NotAndroidProject
from androidrepo_bot.posts.models import PostDraft, PostLink
from androidrepo_bot.repositories.models import REPOSITORY_LINK_ID, RepositoryDetails

if TYPE_CHECKING:
    from pydantic_ai.models import Model

_GENERATION_TIMEOUT_SECONDS = 120.0
_OUTPUT_RETRIES = 2
_MODEL_REQUEST_LIMIT = _OUTPUT_RETRIES + 1
_ZEN_API_BASE_URL = "https://opencode.ai/zen/v1"

logger = structlog.get_logger(__name__)

type PostAgent = Agent[GenerationContext, GeneratedOutput]


@dataclass(frozen=True, slots=True)
class GenerationContext:
    repository: RepositoryDetails
    allow_missing_download: bool = False


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
        retries={"output": _OUTPUT_RETRIES},
    )
    agent.output_validator(_validate_generated_post)
    return agent


class GenerationService:
    def __init__(self, *, agent: PostAgent) -> None:
        self._agent = agent

    async def generate(self, repository: RepositoryDetails, /, *, allow_missing_download: bool = False) -> PostDraft:
        log_context = {
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

        stage_started_at = perf_counter()
        generation_prompt = build_generation_prompt(repository, allow_missing_download=allow_missing_download)
        logger.debug(
            "Post AI evidence prompt prepared", **log_context, duration_seconds=perf_counter() - stage_started_at
        )

        stage_started_at = perf_counter()
        try:
            async with timeout(_GENERATION_TIMEOUT_SECONDS):
                result = await self._agent.run(
                    generation_prompt,
                    deps=GenerationContext(repository=repository, allow_missing_download=allow_missing_download),
                    model_settings=ModelSettings(timeout=_GENERATION_TIMEOUT_SECONDS),
                    usage_limits=UsageLimits(request_limit=_MODEL_REQUEST_LIMIT),
                    metadata={"provider": repository.ref.provider.value, "repository": repository.ref.full_name},
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

        logger.debug(
            "Post AI model run completed",
            **log_context,
            duration_seconds=perf_counter() - stage_started_at,
            output_type=type(result.output).__name__,
        )
        output = result.output
        if isinstance(output, NotAndroidProject):
            raise NotAndroidProjectError(output.reason)
        if isinstance(output, MissingDownloadSource):
            raise MissingDownloadSourceError(output.reason)

        draft = resolve_draft(repository, output, allow_missing_download=allow_missing_download)

        logger.info(
            "Post AI operation completed",
            **log_context,
            duration_seconds=perf_counter() - started_at,
            model_requests=result.usage.requests,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
            feature_count=len(draft.features),
            link_count=len(draft.links),
            tag_count=len(draft.tags),
        )
        return draft


def resolve_draft(
    repository: RepositoryDetails, generated: GeneratedPost, *, allow_missing_download: bool = False
) -> PostDraft:
    if generated.download_link_id is None and not allow_missing_download:
        msg = "A generated draft without a download source requires explicit approval"
        raise ValueError(msg)
    download_link = (
        repository.link_by_id(generated.download_link_id) if generated.download_link_id is not None else None
    )
    if generated.download_link_id is not None and download_link is None:
        msg = "Generated download link must resolve to a verified repository destination"
        raise ValueError(msg)

    links_by_url: dict[str, PostLink] = {}
    repository_link = repository.repository_link
    links_by_url[repository_link.url] = PostLink(label=repository_link.label, url=repository_link.url)

    for selected_link in generated.links:
        verified_link = repository.link_by_id(selected_link.id)
        if selected_link.id == REPOSITORY_LINK_ID or verified_link is None:
            msg = f"Generated link ID does not resolve to a selectable repository destination: {selected_link.id}"
            raise ValueError(msg)
        links_by_url.setdefault(verified_link.url, PostLink(label=selected_link.label, url=verified_link.url))

    return PostDraft(
        title=generated.project_name,
        summary=generated.summary,
        features=generated.features,
        links=tuple(links_by_url.values()),
        download_url=download_link.url if download_link is not None else None,
        tags=generated.tags,
    )


def _validate_generated_post(ctx: RunContext[GenerationContext], output: GeneratedOutput) -> GeneratedOutput:
    if ctx.partial_output:
        return output
    if isinstance(output, MissingDownloadSource):
        if ctx.deps.allow_missing_download:
            message = "Generate the approved draft with download_link_id set to null."
            raise ModelRetry(message)
        return output
    if not isinstance(output, GeneratedPost):
        return output

    errors = _generated_post_errors(ctx.deps, output)
    if errors:
        raise ModelRetry("Fix the generated draft: " + " ".join(errors))
    return output


def _generated_post_errors(context: GenerationContext, output: GeneratedPost) -> list[str]:
    valid_link_ids = context.repository.selectable_link_ids
    errors: list[str] = []
    if output.download_link_id is None:
        if not context.allow_missing_download:
            errors.append("Return missing_download_source when no official download source is available.")
    elif output.download_link_id not in valid_link_ids:
        errors.append(f"Invalid download link ID: {output.download_link_id}.")

    invalid_link_ids = sorted({link.id for link in output.links} - valid_link_ids)
    if invalid_link_ids:
        errors.append(f"Invalid optional link IDs: {', '.join(invalid_link_ids)}.")

    text_length = _generated_text_length(context.repository, output)
    if text_length > DRAFT_TEXT_BUDGET:
        errors.append(f"Shorten the draft from {text_length} to at most {DRAFT_TEXT_BUDGET} characters.")
    return errors


def _generated_text_length(repository: RepositoryDetails, output: GeneratedPost) -> int:
    values = (
        output.project_name,
        output.summary,
        *output.features,
        *(link.label for link in output.links),
        *(f"#{tag.value}" for tag in output.tags),
    )
    return sum(map(len, values)) + len(repository.repository_link.label)
