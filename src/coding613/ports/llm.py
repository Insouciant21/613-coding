"""Port and validated values for lower-level LLM providers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field

from coding613.domain.actions import ActionEnvelope
from coding613.domain.models import Feedback
from coding613.domain.models_base import DomainModel


class RetryableProviderError(RuntimeError):
    """A provider failure that the owned loop may retry in the same run."""


class ModelMessage(DomainModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None


class ModelContext(DomainModel):
    run_id: UUID
    task: str = Field(min_length=1)
    messages: tuple[ModelMessage, ...] = ()
    feedback: tuple[Feedback, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolDefinition(DomainModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]


class LLMResponse(DomainModel):
    content: str = ""
    actions: tuple[ActionEnvelope, ...] = ()
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    def complete(
        self, context: ModelContext, tools: Sequence[ToolDefinition]
    ) -> LLMResponse: ...


@runtime_checkable
class StreamingLLMProvider(LLMProvider, Protocol):
    def complete_stream(
        self,
        context: ModelContext,
        tools: Sequence[ToolDefinition],
        on_text_delta: Callable[[str], None],
        cancelled: Callable[[], bool],
    ) -> LLMResponse: ...
