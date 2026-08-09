"""Deterministic scripted LLM used by tests and offline demonstrations."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence

from coding613.application.progress import ProviderCancelledError
from coding613.ports.llm import LLMResponse, ModelContext, ToolDefinition


class MockScriptExhausted(RuntimeError):
    """Raised when a scripted provider receives more calls than responses."""


class ScriptedLLM:
    def __init__(self, responses: Sequence[LLMResponse]) -> None:
        self._responses = deque(responses)
        self.contexts: list[ModelContext] = []
        self.tools: list[tuple[ToolDefinition, ...]] = []

    def complete(
        self, context: ModelContext, tools: Sequence[ToolDefinition]
    ) -> LLMResponse:
        self.contexts.append(context.model_copy(deep=True))
        self.tools.append(tuple(tool.model_copy(deep=True) for tool in tools))
        if not self._responses:
            raise MockScriptExhausted("scripted LLM response sequence is exhausted")
        return self._responses.popleft()


class ScriptedStreamingLLM(ScriptedLLM):
    def __init__(self, deltas: Sequence[str], response: LLMResponse) -> None:
        super().__init__((response,))
        self._deltas = tuple(deltas)

    def complete_stream(
        self,
        context: ModelContext,
        tools: Sequence[ToolDefinition],
        on_text_delta: Callable[[str], None],
        cancelled: Callable[[], bool],
    ) -> LLMResponse:
        for delta in self._deltas:
            if cancelled():
                raise ProviderCancelledError("provider stream was cancelled")
            on_text_delta(delta)
        if cancelled():
            raise ProviderCancelledError("provider stream was cancelled")
        return self.complete(context, tools)
