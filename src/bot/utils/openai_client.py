# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import asyncio
import logging

from openai import AsyncOpenAI
from pydantic import ValidationError

from .models import AIGeneratedContent
from .tag_manager import get_tags_for_ai_context, process_ai_generated_tags

logger = logging.getLogger(__name__)


class OpenAIClient:
    DEFAULT_MODEL = "openai/gpt-4.1"
    FALLBACK_MODEL = "openai/gpt-4.1-mini"
    MAX_TOKENS = 1000
    TEMPERATURE = 0.2
    README_CONTENT_LIMIT = 2000

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = self.DEFAULT_MODEL

    async def __aenter__(self) -> OpenAIClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._client.close()

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

    @staticmethod
    def _create_user_prompt(
        project_name: str,
        description: str | None,
        readme_content: str | None,
        topics: list[str],
    ) -> str:
        parts = [f"Repository Name: {project_name}"]

        if description:
            parts.append(f"Repository Description: {description}")

        if topics:
            parts.append(f"Repository Tags: {', '.join(topics)}")

        if readme_content:
            content = (
                readme_content[: OpenAIClient.README_CONTENT_LIMIT] + "..."
                if len(readme_content) > OpenAIClient.README_CONTENT_LIMIT
                else readme_content
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
        topics = topics or []

        standard_tags = await get_tags_for_ai_context()
        system_prompt = self._create_system_prompt(standard_tags)
        user_prompt = self._create_user_prompt(repo_name, description, readme_content, topics)

        models_to_try = self._get_models_to_try()
        original_model = self._model

        for model_index, model in enumerate(models_to_try):
            self._model = model
            model_name = "fallback" if model_index > 0 else "primary"

            logger.info("Trying %s model %s for %s", model_name, model, repo_name)

            try:
                ai_content = await self._attempt_enhancement(
                    system_prompt, user_prompt, repo_name, model_name, max_retries
                )

                if ai_content.relevant_tags:
                    await process_ai_generated_tags(ai_content.relevant_tags)

                return ai_content
            except Exception as e:
                if model_index == len(models_to_try) - 1:
                    raise
                logger.info("Switching to fallback model after errors: %s", e)
            finally:
                self._model = original_model

        msg = f"Failed to enhance content for {repo_name} after trying all models"
        raise RuntimeError(msg)

    def _get_models_to_try(self) -> list[str]:
        models = [self._model]
        if self._model != self.FALLBACK_MODEL:
            models.append(self.FALLBACK_MODEL)
        return models

    async def _attempt_enhancement(
        self,
        system_prompt: str,
        user_prompt: str,
        repo_name: str,
        model_name: str,
        max_retries: int,
    ) -> AIGeneratedContent:
        for attempt in range(max_retries):
            try:
                logger.info(
                    "Requesting content enhancement from OpenAI for %s using %s model "
                    "(attempt %d/%d)",
                    repo_name,
                    model_name,
                    attempt + 1,
                    max_retries,
                )

                response = await self._make_api_request(system_prompt, user_prompt)
                return self._process_response(response)

            except ValidationError as e:
                logger.error("Invalid data structure from OpenAI with %s model: %s", model_name, e)
                if attempt == max_retries - 1:
                    msg = f"OpenAI returned invalid data after {max_retries} attempts: {e}"
                    raise ValueError(msg) from e

            except Exception as e:
                logger.error(
                    "OpenAI API error for %s with %s model (attempt %d): %s",
                    repo_name,
                    model_name,
                    attempt + 1,
                    e,
                )
                if attempt == max_retries - 1:
                    raise

            await self._backoff_delay(attempt)

        msg = f"Failed to enhance content for {repo_name} after {max_retries} attempts"
        raise RuntimeError(msg)

    @staticmethod
    async def _backoff_delay(attempt: int) -> None:
        await asyncio.sleep(2**attempt)

    async def _make_api_request(self, system_prompt: str, user_prompt: str):
        return await self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=self.MAX_TOKENS,
            temperature=self.TEMPERATURE,
            response_format=AIGeneratedContent,
        )

    @staticmethod
    def _process_response(response):
        if response.choices[0].message.refusal:
            refusal = response.choices[0].message.refusal
            logger.warning("OpenAI refused to generate content: %s", refusal)
            msg = f"OpenAI refused to generate content: {refusal}"
            raise ValueError(msg)

        parsed_response = response.choices[0].message.parsed
        if not parsed_response:
            msg = "Empty or unparseable response from OpenAI"
            raise ValueError(msg)

        logger.debug("Generated content: %s", parsed_response)
        return parsed_response
