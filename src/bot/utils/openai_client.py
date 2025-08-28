# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging
from typing import Self

from httpx import AsyncClient, HTTPStatusError
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from pydantic_ai.settings import ModelSettings
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import AIGeneratedContent

logger = logging.getLogger(__name__)


class RepositoryData(BaseModel):
    model_config = ConfigDict(frozen=True)

    repo_name: str = Field(..., min_length=1, description="Repository name")
    description: str | None = Field(None, description="Repository description")
    readme_content: str | None = Field(None, description="README content")
    topics: list[str] = Field(default_factory=list, description="Repository topics")


class OpenAIClient:
    DEFAULT_MODEL = "openai/gpt-4.1"
    FALLBACK_MODEL = "openai/gpt-4.1-mini"
    MAX_TOKENS = 2000
    README_CONTENT_LIMIT = 5000

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._agent: Agent[RepositoryData, AIGeneratedContent] | None = None
        self._http_client: AsyncClient | None = None
        self._model_settings = ModelSettings(max_tokens=self.MAX_TOKENS, timeout=60.0)

    async def __aenter__(self) -> Self:
        await self._initialize_agent()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    @staticmethod
    def _create_retrying_client() -> AsyncClient:
        def should_retry_status(response):
            if response.status_code in {429, 500, 502, 503, 504}:
                logger.warning(
                    "HTTP %d error from OpenAI API, will retry with backoff", response.status_code
                )
                response.raise_for_status()

        transport = AsyncTenacityTransport(
            config=RetryConfig(
                retry=retry_if_exception_type((HTTPStatusError, ConnectionError)),
                wait=wait_retry_after(
                    fallback_strategy=wait_exponential(multiplier=2, min=2, max=30), max_wait=60
                ),
                stop=stop_after_attempt(5),
                reraise=True,
            ),
            validate_response=should_retry_status,
        )

        return AsyncClient(transport=transport, timeout=60.0)

    async def _initialize_agent(self) -> None:
        if self._agent is not None:
            return

        primary = self._create_model(self.DEFAULT_MODEL)
        secondary = self._create_model(self.FALLBACK_MODEL)
        model = FallbackModel(primary, secondary)

        self._agent = Agent(
            model=model,
            deps_type=RepositoryData,
            output_type=AIGeneratedContent,
            system_prompt=(
                "You are an Android content curator. Create concise, user-focused "
                "descriptions for Android apps, tools, and utilities."
            ),
            model_settings=self._model_settings,
        )

        @self._agent.system_prompt
        def add_content_guidelines(ctx: RunContext[RepositoryData]) -> str:
            return """
Focus on user benefits and practical value. Keep responses under 800 characters total.

Structure your response with:
1. project_name: Extract from README/docs, fallback to repo name if unclear
2. enhanced_description: 2-3 sentences highlighting user benefits and target audience
3. key_features: 3-4 user-centric features
4. important_links: Only direct download/documentation links (exclude GitHub if same project)

Avoid hashtags like #android. Maintain technical precision and clarity.
"""

        @self._agent.system_prompt
        def add_repository_context(ctx: RunContext[RepositoryData]) -> str:
            repo_data = ctx.deps
            context_parts = [f"Repository: {repo_data.repo_name}"]

            if repo_data.description:
                context_parts.append(f"Description: {repo_data.description}")

            if repo_data.topics:
                context_parts.append(f"Topics: {', '.join(repo_data.topics)}")

            return "\n".join(context_parts)

    def _create_model(self, model_name: str) -> OpenAIChatModel:
        if self._http_client is None:
            self._http_client = self._create_retrying_client()
        client = self._http_client

        if self._base_url:
            provider = OpenAIProvider(
                api_key=self._api_key, base_url=self._base_url, http_client=client
            )
            return OpenAIChatModel(model_name, provider=provider)

        provider = OpenAIProvider(api_key=self._api_key, http_client=client)
        return OpenAIChatModel(model_name, provider=provider)

    def _create_user_prompt(self, repo_data: RepositoryData) -> str:
        if repo_data.readme_content:
            content = (
                repo_data.readme_content[: self.README_CONTENT_LIMIT] + "..."
                if len(repo_data.readme_content) > self.README_CONTENT_LIMIT
                else repo_data.readme_content
            )
            return f"Documentation/README: {content}"
        return "Generate content for this Android repository."

    async def enhance_repository_content(
        self,
        repo_name: str,
        description: str | None = None,
        readme_content: str | None = None,
        topics: list[str] | None = None,
    ) -> AIGeneratedContent:
        if self._agent is None:
            await self._initialize_agent()

        repo_data = RepositoryData(
            repo_name=repo_name,
            description=description,
            readme_content=readme_content,
            topics=topics or [],
        )

        user_prompt = self._create_user_prompt(repo_data)

        logger.info("Requesting content enhancement for %s", repo_name)
        result = await self._agent.run(user_prompt, deps=repo_data)  # pyright: ignore[reportOptionalMemberAccess]
        ai_content = result.output
        logger.debug("Generated content: %s", ai_content)
        return ai_content
