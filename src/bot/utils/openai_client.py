# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Self

from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from .models import AIGeneratedContent
from .tag_manager import get_tags_for_ai_context, process_ai_generated_tags

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RepositoryData:
    repo_name: str
    description: str | None
    readme_content: str | None
    topics: list[str]


class OpenAIClient:
    DEFAULT_MODEL = "openai/gpt-4.1"
    FALLBACK_MODEL = "openai/gpt-4.1-mini"
    MAX_TOKENS = 1000
    TEMPERATURE = 0.2
    README_CONTENT_LIMIT = 2000

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._agent: Agent[RepositoryData, AIGeneratedContent] | None = None
        self._current_model = self.DEFAULT_MODEL

    async def __aenter__(self) -> Self:
        await self._initialize_agent()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        pass

    async def _initialize_agent(self, model_name: str | None = None) -> None:
        if self._agent is not None and model_name is None:
            return

        if model_name is not None:
            self._current_model = model_name

        standard_tags = await get_tags_for_ai_context()
        system_prompt = self._create_system_prompt(standard_tags)

        model_settings = ModelSettings(max_tokens=self.MAX_TOKENS, temperature=self.TEMPERATURE)

        if self._base_url:
            provider = OpenAIProvider(api_key=self._api_key, base_url=self._base_url)
            model = OpenAIModel(self._current_model, provider=provider)
        else:
            model = OpenAIModel(
                self._current_model, provider=OpenAIProvider(api_key=self._api_key)
            )

        self._agent = Agent(
            model=model,
            deps_type=RepositoryData,
            output_type=AIGeneratedContent,
            system_prompt=system_prompt,
            model_settings=model_settings,
        )

    @staticmethod
    def _create_system_prompt(standard_tags: set[str] | None = None) -> str:
        base_prompt = """You are an Android content curator. Create user-focused descriptions \
for Android apps, tools, and utilities.

Focus on:
- What problems it solves for users
- Key user benefits
- Who would find it useful

Guidelines:
- project_name: The actual project name (not necessarily the repository name)
  - Project Name Guidelines:
    - Identify the actual project name from README, description, or documentation
    - The project name may differ from the repository name (e.g., "Signal" vs "Signal-Android")
    - Look for app names, display names, or branding mentioned in the documentation
    - If uncertain, use the project/repository name as a fallback
- enhanced_description: 2-3 sentences, user benefits focused
- relevant_tags: 5-7 tags using underscores (e.g., "media_player")
- key_features: 3-4 user-facing features
- important_links: Only include download, documentation, or official website links
- Exclude GitHub URLs if they are for the project being analyzed
- No #android or #androidrepo tags

CRITICAL: Keep the total response under 800 characters to fit Telegram image caption limits. \
Be concise while maintaining technical accuracy."""

        if standard_tags:
            tags_list = ", ".join(sorted(standard_tags))
            tag_guidance = f"""

For relevant_tags, prioritize these standard tags when applicable: {tags_list}
You can suggest additional tags if they better describe the app, but prefer standard tags when \
possible."""
            base_prompt += tag_guidance

        return base_prompt

    def _create_user_prompt(self, repo_data: RepositoryData) -> str:
        parts = [f"Repository Name: {repo_data.repo_name}"]

        if repo_data.description:
            parts.append(f"Repository Description: {repo_data.description}")

        if repo_data.topics:
            parts.append(f"Repository Tags: {', '.join(repo_data.topics)}")

        if repo_data.readme_content:
            content = (
                repo_data.readme_content[: self.README_CONTENT_LIMIT] + "..."
                if len(repo_data.readme_content) > self.README_CONTENT_LIMIT
                else repo_data.readme_content
            )
            parts.append(f"Documentation/README: {content}")

        return "\n\n".join(parts)

    async def enhance_repository_content(
        self,
        repo_name: str,
        description: str | None = None,
        readme_content: str | None = None,
        topics: list[str] | None = None,
        max_retries: int = 3,
    ) -> AIGeneratedContent:
        await self._initialize_agent()

        if self._agent is None:
            msg = "Agent not initialized"
            raise RuntimeError(msg)

        topics = topics or []
        repo_data = RepositoryData(
            repo_name=repo_name,
            description=description,
            readme_content=readme_content,
            topics=topics,
        )

        user_prompt = self._create_user_prompt(repo_data)

        try:
            logger.info("Requesting content enhancement for %s", repo_name)

            result = await self._agent.run(user_prompt, deps=repo_data)
            ai_content = result.output

            if ai_content.relevant_tags:
                await process_ai_generated_tags(ai_content.relevant_tags)

            logger.debug("Generated content: %s", ai_content)
            return ai_content

        except UnexpectedModelBehavior as e:
            logger.error("Model behavior error for %s: %s", repo_name, e)

            if max_retries > 1:
                logger.info("Retrying with fallback model for %s", repo_name)
                await self._initialize_agent(self.FALLBACK_MODEL)
                return await self.enhance_repository_content(
                    repo_name, description, readme_content, topics, max_retries - 1
                )
            raise

        except Exception as e:
            logger.error("Unexpected error for %s: %s", repo_name, e)
            raise
