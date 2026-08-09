"""Application helpers for optional streaming and ephemeral progress."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import Event

from coding613.ports.llm import (
    LLMProvider,
    LLMResponse,
    ModelContext,
    StreamingLLMProvider,
    ToolDefinition,
)


class ProviderCancelledError(RuntimeError):
    """Raised when a provider stream is cancelled by the application."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        self._event.clear()


def complete_with_progress(
    provider: LLMProvider,
    context: ModelContext,
    tools: Sequence[ToolDefinition],
    on_text_delta: Callable[[str], None],
    cancelled: Callable[[], bool],
) -> LLMResponse:
    if isinstance(provider, StreamingLLMProvider):
        return provider.complete_stream(context, tools, on_text_delta, cancelled)
    response = provider.complete(context, tools)
    if response.content:
        on_text_delta(response.content)
    return response
