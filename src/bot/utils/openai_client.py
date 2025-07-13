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
    MAX_TOKENS = 2000
    TEMPERATURE = 0.2
    README_CONTENT_LIMIT = 5000

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._agent: Agent[RepositoryData, AIGeneratedContent] | None = None
        self._model_settings = ModelSettings(
            max_tokens=self.MAX_TOKENS, temperature=self.TEMPERATURE
        )

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
        current_model = model_name or self.DEFAULT_MODEL

        model = self._create_model(current_model)

        self._agent = Agent(
            model=model,
            deps_type=RepositoryData,
            output_type=AIGeneratedContent,
            system_prompt=self._create_base_system_prompt(),
            model_settings=self._model_settings,
        )

        @self._agent.system_prompt
        async def add_suggested_tags_context() -> str:
            suggested_tags = await get_tags_for_ai_context()
            if not suggested_tags:
                return """

For relevant_tags, you MUST create exactly 5-7 tags using underscores \
(e.g., "media_player", "file_manager"). \
Create meaningful tags that best describe the app's category, functionality, \
and target use cases. \
If you can only think of a few obvious tags, expand with related categories, user types, \
or use cases."""

            tags_list = ", ".join(sorted(suggested_tags))
            return f"""

For relevant_tags, you MUST provide exactly 5-7 tags. Prioritize these existing tags \
when applicable: {tags_list}
If existing tags don't reach 5-7 tags, create new appropriate tags to meet the requirement. \
Use underscores for multi-word tags and ensure all tags are relevant to the app's functionality."""

    def _create_model(self, model_name: str) -> OpenAIModel:
        if self._base_url:
            provider = OpenAIProvider(api_key=self._api_key, base_url=self._base_url)
            return OpenAIModel(model_name, provider=provider)
        return OpenAIModel(model_name, provider=OpenAIProvider(api_key=self._api_key))

    @staticmethod
    def _create_base_system_prompt() -> str:
        return """You are an Android content curator. Create user-focused descriptions \
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
- relevant_tags: EXACTLY 5-7 tags using underscores (e.g., "media_player")
  - REQUIREMENT: You must provide between 5 and 7 tags, never less, never more
  - Mix of category tags (e.g., "communication", "productivity"), feature tags \
(e.g., "offline_support", "material_design"), and user type tags \
(e.g., "power_users", "developers")
- key_features: 3-4 user-facing features
- important_links: Only include download, documentation, or official website links
- Exclude GitHub URLs if they are for the project being analyzed
- No #android or #androidrepo tags

CRITICAL: Keep the total response under 800 characters to fit Telegram image caption limits. \
Be concise while maintaining technical accuracy."""

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
        if self._agent is None:
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
                processed_tags = await process_ai_generated_tags(ai_content.relevant_tags)
                ai_content.relevant_tags = processed_tags

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
