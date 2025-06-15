# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import asyncio
import logging

from openai import AsyncOpenAI
from pydantic import ValidationError

from .models import AIGeneratedContent

logger = logging.getLogger(__name__)


class OpenAIClient:
    def __init__(
        self, api_key: str, model: str = "openai/gpt-4.1", base_url: str | None = None
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def __aenter__(self) -> OpenAIClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._client.close()

    @staticmethod
    def _create_system_prompt() -> str:
        return (
            "You are an Android content curator. Create user-focused descriptions "
            "for Android apps, tools, and utilities.\n\n"
            "Focus on:\n"
            "- What problems it solves for users\n"
            "- Key user benefits (not technical details)\n"
            "- Who would find it useful\n\n"
            "Guidelines:\n"
            "- enhanced_description: 2-3 sentences, user benefits focused\n"
            '- relevant_tags: 5-7 tags using underscores (e.g., "media_player")\n'
            "- key_features: 3-4 user-facing features\n"
            "- important_links: Only include download, documentation, or official website links\n"
            "- Exclude GitHub URLs if they are for the project being analyzed\n"
            "- No #android or #androidrepo tags"
        )

    @staticmethod
    def _create_user_prompt(
        project_name: str,
        description: str | None,
        readme_content: str | None,
        topics: list[str],
    ) -> str:
        context_parts = [f"Project: {project_name}"]

        if description:
            context_parts.append(f"Description: {description}")

        if topics:
            context_parts.append(f"Tags: {', '.join(topics)}")

        if readme_content:
            truncated_readme = (
                readme_content[:2000] + "..." if len(readme_content) > 2000 else readme_content
            )
            context_parts.append(f"Documentation: {truncated_readme}")

        return "\n\n".join(context_parts)

    async def enhance_repository_content(
        self,
        repo_name: str,
        description: str | None = None,
        readme_content: str | None = None,
        topics: list[str] | None = None,
        max_retries: int = 3,
    ) -> AIGeneratedContent:
        topics = topics or []

        system_prompt = self._create_system_prompt()
        user_prompt = self._create_user_prompt(
            project_name=repo_name,
            description=description,
            readme_content=readme_content,
            topics=topics,
        )

        for attempt in range(max_retries):
            try:
                logger.info(
                    "Requesting content enhancement from OpenAI for %s (attempt %d/%d)",
                    repo_name,
                    attempt + 1,
                    max_retries,
                )

                response = await self._client.beta.chat.completions.parse(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=1000,
                    temperature=0.2,
                    response_format=AIGeneratedContent,
                )

                if response.choices[0].message.refusal:
                    refusal = response.choices[0].message.refusal
                    logger.warning("OpenAI refused to generate content: %s", refusal)
                    msg = f"OpenAI refused to generate content: {refusal}"
                    raise ValueError(msg)

                parsed_response = response.choices[0].message.parsed
                if not parsed_response:
                    msg = "Empty or unparseable response from OpenAI"
                    raise ValueError(msg)

                logger.debug("AI response: %s", parsed_response)
                return parsed_response

            except ValidationError as e:
                logger.error("Invalid data structure from OpenAI: %s", e)
                if attempt == max_retries - 1:
                    msg = (
                        f"OpenAI returned invalid data structure after {max_retries} attempts: {e}"
                    )
                    raise ValueError(msg) from e

                await asyncio.sleep(2**attempt)
                continue

            except Exception as e:
                logger.error("OpenAI API error for %s (attempt %d): %s", repo_name, attempt + 1, e)
                if attempt == max_retries - 1:
                    raise

                await asyncio.sleep(2**attempt)
                continue

        msg = f"Failed to enhance content for {repo_name} after {max_retries} attempts"
        raise RuntimeError(msg)
