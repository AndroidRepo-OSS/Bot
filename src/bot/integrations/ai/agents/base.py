# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic_ai import Agent
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.github import GitHubProvider

from bot.logging import get_logger

logger = get_logger(__name__)


class BaseAgent[TDeps, TOutput](ABC):
    __slots__ = ("_agent",)

    def __init__(self, *, api_key: str, instructions: str) -> None:
        logger.debug("Initializing AI agent", agent_class=self.__class__.__name__)

        provider = GitHubProvider(api_key=api_key)
        model = self._create_model(provider)

        self._agent: Agent[TDeps, TOutput] = Agent(
            model=model,
            output_type=self._get_output_type(),
            deps_type=self._get_deps_type(),
            instructions=instructions,
            model_settings=OpenAIChatModelSettings(openai_reasoning_effort="high"),
        )
        self._register_instructions()

        logger.debug(
            "AI agent initialized successfully",
            agent_class=self.__class__.__name__,
            output_type=self._get_output_type().__name__,
            deps_type=self._get_deps_type().__name__,
        )

    @classmethod
    @abstractmethod
    def _get_output_type(cls) -> type[TOutput]: ...

    @classmethod
    @abstractmethod
    def _get_deps_type(cls) -> type[TDeps]: ...

    @staticmethod
    def _create_model(provider: GitHubProvider) -> FallbackModel:
        return FallbackModel(
            OpenAIChatModel("openai/gpt-5", provider=provider),
            OpenAIChatModel("openai/gpt-5-mini", provider=provider),
            OpenAIChatModel("openai/gpt-4.1", provider=provider),
            OpenAIChatModel("openai/gpt-4.1-mini", provider=provider),
        )

    @abstractmethod
    def _register_instructions(self) -> None: ...
