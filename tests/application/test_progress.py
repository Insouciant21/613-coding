from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from coding613.adapters.llm.mock import ScriptedLLM, ScriptedStreamingLLM
from coding613.application.progress import (
    CancellationToken,
    ProviderCancelledError,
    complete_with_progress,
)
from coding613.ports.llm import LLMResponse, ModelContext
from coding613.ports.progress import NullProgressSink, ProgressKind, RunProgress


def test_run_progress_is_immutable_and_null_sink_is_noop() -> None:
    update = RunProgress(
        run_id=uuid4(),
        kind=ProgressKind.STATE,
        payload={"state": "running", "details": {"attempt": 1}, "items": ["first"]},
    )
    with pytest.raises(ValidationError):
        update.kind = ProgressKind.ERROR
    with pytest.raises(TypeError):
        update.payload["details"]["attempt"] = 2
    with pytest.raises(AttributeError):
        update.payload["items"].append("second")
    with pytest.raises(TypeError):
        update.payload |= {"new": "value"}
    NullProgressSink().publish(update)


def test_cancellation_token_is_thread_safe_and_resettable() -> None:
    token = CancellationToken()
    assert not token.is_cancelled()
    token.cancel()
    assert token.is_cancelled()
    token.reset()
    assert not token.is_cancelled()


def test_complete_with_progress_falls_back_and_emits_content() -> None:
    response = LLMResponse(content="fallback")
    deltas: list[str] = []
    provider = ScriptedLLM((response,))
    result = complete_with_progress(
        provider, ModelContext(run_id=uuid4(), task="task"), (), deltas.append, lambda: False
    )
    assert result == response
    assert deltas == ["fallback"]


def test_complete_with_progress_uses_streaming_provider() -> None:
    response = LLMResponse(content="done")
    deltas: list[str] = []
    provider = ScriptedStreamingLLM(("hel", "lo"), response)
    result = complete_with_progress(
        provider, ModelContext(run_id=uuid4(), task="task"), (), deltas.append, lambda: False
    )
    assert result == response
    assert deltas == ["hel", "lo"]


def test_streaming_provider_raises_at_cancellation_boundary() -> None:
    token = CancellationToken()
    provider = ScriptedStreamingLLM(("before", "after"), LLMResponse(content="done"))
    deltas: list[str] = []

    def on_delta(value: str) -> None:
        deltas.append(value)
        token.cancel()

    with pytest.raises(ProviderCancelledError):
        complete_with_progress(
            provider, ModelContext(run_id=uuid4(), task="task"), (), on_delta, token.is_cancelled
        )
    assert deltas == ["before"]
