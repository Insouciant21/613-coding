"""Deterministic scripted LLM used by tests and offline demonstrations."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from coding_harness.ports.llm import LLMResponse, ModelContext, ToolDefinition


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
