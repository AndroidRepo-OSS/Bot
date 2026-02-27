# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic_ai import Agent
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.github import GitHubProvider

from bot.logging import get_logger

if TYPE_CHECKING:
    from pydantic_ai import RunContext

logger = get_logger(__name__)


def _describe_schema(schema: object) -> str:
    return getattr(schema, "__name__", str(schema))


class BaseAgent[TDeps, TOutput](ABC):
    __slots__ = ("_agent",)

    _deps_type: ClassVar[type[Any]]
    _instructions: ClassVar[str]
    _model_names: ClassVar[tuple[str, ...]]
    _model_settings: ClassVar[OpenAIChatModelSettings | None] = OpenAIChatModelSettings(openai_reasoning_effort="high")
    _output_type: ClassVar[Any]

    def __init__(self, *, api_key: str) -> None:
        cls = type(self)
        if not cls._model_names:
            msg = f"{cls.__name__} must define at least one model name"
            raise TypeError(msg)

        logger.debug("Initializing AI agent", agent_class=cls.__name__, models=cls._model_names)

        provider = GitHubProvider(api_key=api_key)
        self._agent: Agent[TDeps, TOutput] = Agent(
            model=cls._create_model(provider),
            output_type=cls._output_type,
            deps_type=cls._deps_type,
            instructions=cls._instructions,
            model_settings=cls._model_settings,
        )
        self._register_context_instruction()

        logger.debug(
            "AI agent initialized successfully",
            agent_class=cls.__name__,
            output_type=_describe_schema(cls._output_type),
            deps_type=_describe_schema(cls._deps_type),
        )

    @classmethod
    def _create_model(cls, provider: GitHubProvider) -> FallbackModel:
        return FallbackModel(*(OpenAIChatModel(model_name, provider=provider) for model_name in cls._model_names))

    def _register_context_instruction(self) -> None:
        @self._agent.instructions
        def provide_context(ctx: RunContext[TDeps]) -> str:
            return self.build_context(ctx.deps)

    @abstractmethod
    def build_context(self, deps: TDeps) -> str: ...
