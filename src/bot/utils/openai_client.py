# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import asyncio
import json
import logging
import re

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
    def _create_enhancement_prompt(
        project_name: str,
        description: str | None,
        readme_content: str | None,
        topics: list[str],
    ) -> str:
        prompt = f"""You are an expert content curator specializing in Android applications and \
mobile software discovery. Your mission is to help Android users find amazing apps, tools, and \
utilities that enhance their mobile experience.

CHANNEL CONTEXT & AUDIENCE:
- Channel: Android Repository (@AndroidRepo)
- Primary audience: Android users seeking quality apps and useful tools
- Secondary audience: Power users, modders, and Android enthusiasts
- Content focus: Applications, utilities, mods, and tools for end-users
- Style: Clean, professional, user-focused (no emojis, clear descriptions)

PROJECT TO ANALYZE:
Name: {project_name}
Description: {description or "No description provided"}
Topics/Tags: {", ".join(topics) if topics else "None specified"}

README/Documentation Content:
{readme_content or "No documentation available"}

ANALYSIS FRAMEWORK:
1. Identify what problem this solves for Android users
2. Focus on user benefits and practical applications
3. Highlight features that improve user experience or device functionality
4. Determine if it's an app, utility, mod, or tool for end-users
5. Extract any download links, official websites, or demos mentioned

EXAMPLES OF EXCELLENT CHANNEL POSTS:

Example 1 - Media/Entertainment App:
{{
    "enhanced_description": "A powerful media player app that supports all major video and audio \
formats. It offers a sleek interface, advanced playback features, and seamless integration with \
popular streaming services. Perfect for users who want a versatile media experience on their \
Android device.",
    "relevant_tags": ["media", "player", "video", "audio", "streaming"],
    "key_features": ["Supports all formats", "Advanced playback controls", \
"Streaming integration", "Customizable UI"],
    "important_links": [
        {{"title": "Download App",
          "url": "https://play.google.com/store/apps/details?id=com.example.app",
          "type": "download"}},
        {{"title": "Official Website", "url": "https://www.example.com", "type": "website"}},
        {{"title": "User Guide", "url": "https://docs.example.com/user-guide",
          "type": "documentation"}}
    ]
}}

Example 2 - Magisk Module:
{{
    "enhanced_description": "A Magisk module that enhances the Android boot animation with \
a stunning 4K video experience. Perfect for users who want to customize their device's boot \
animation without rooting or complex setups.",
    "relevant_tags": ["magisk", "module", "boot animation", "customization", "4K"],
    "key_features": ["4K video boot animation", "Easy Magisk integration", \
"Customizable settings"],
    "important_links": [
        {{"title": "Download Module", "url": "https://github.com/example/releases",
          "type": "download"}},
        {{"title": "Installation Guide", "url": "https://guide.example.com",
          "type": "documentation"}}
    ]
}}

QUALITY REQUIREMENTS FOR USER-FOCUSED CONTENT:
- enhanced_description: 2-3 sentences explaining what the app/tool does for users and why they \
should care. Focus on practical benefits, not technical implementation.
- relevant_tags: 5-7 tags prioritizing: app category → main function → user benefits
- key_features: 3-4 user-facing features that solve real problems or improve experience
- important_links: Direct download links, official websites, setup guides - what users need to \
get started

GUIDELINES:
- Write for Android users who want to discover useful apps and tools
- Explain benefits in simple terms (avoid technical jargon unless necessary)
- Focus on what problems the app solves or what it enables users to do
- Highlight unique features that set it apart from alternatives
- Consider different user types: casual users, power users, privacy-conscious users
- Mention compatibility requirements if important (root, Android version, etc.)
- Focus on user benefits rather than developer features
- Ensure all information is accurate and based on provided documentation
- Keep descriptions concise but compelling
- Don't include the GitHub repository URL in the output
- Don't include a download link in the output if it's from GitHub Releases
- Don't include '#android' or '#androidrepo' tags in the output
- Use underline as a separator for multi-word tags (e.g., 'media_player', 'video_streaming')
"""
        return prompt.strip()

    async def enhance_repository_content(
        self,
        repo_name: str,
        description: str | None = None,
        readme_content: str | None = None,
        topics: list[str] | None = None,
        max_retries: int = 3,
    ) -> AIGeneratedContent:
        topics = topics or []

        prompt = self._create_enhancement_prompt(
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

                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a specialized Android content curator with deep "
                            "understanding of the mobile app ecosystem and user needs. Your "
                            "expertise lies in identifying valuable Android applications, "
                            "utilities, and tools that solve real user problems. You excel at "
                            "translating technical projects into user-friendly descriptions that "
                            "highlight practical benefits. You always focus on the end-user "
                            "perspective and create precise, structured JSON outputs without "
                            "additional formatting.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=1200,
                    temperature=0.3,
                    top_p=0.9,
                    frequency_penalty=0.1,
                    presence_penalty=0.1,
                )

                content = response.choices[0].message.content
                if not content:
                    msg = "Empty response from OpenAI"
                    raise ValueError(msg)

                try:
                    ai_data = json.loads(content.strip())
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse OpenAI JSON response: %s", content)

                    json_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
                    if json_match:
                        try:
                            ai_data = json.loads(json_match.group(1))
                            logger.info("Successfully extracted JSON from code block")
                        except json.JSONDecodeError:
                            msg = f"Invalid JSON response from OpenAI: {e}"
                            raise ValueError(msg) from e
                    else:
                        msg = f"Invalid JSON response from OpenAI: {e}"
                        raise ValueError(msg) from e

                return AIGeneratedContent(**ai_data)

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
