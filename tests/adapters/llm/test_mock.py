from __future__ import annotations

from uuid import uuid4

import pytest

from coding613.adapters.llm.mock import MockScriptExhausted, ScriptedLLM, ScriptedStreamingLLM
from coding613.ports.llm import LLMResponse, ModelContext, ModelMessage


def test_scripted_llm_returns_in_order_and_captures_deep_snapshots() -> None:
    first = LLMResponse(content="first")
    second = LLMResponse(content="second")
    provider = ScriptedLLM((first, second))
    context = ModelContext(
        run_id=uuid4(), task="fix bug", messages=(ModelMessage(role="user", content="one"),)
    )
    assert provider.complete(context, ()) == first
    context.metadata["changed"] = True
    assert provider.complete(context, ()) == second
    assert provider.contexts[0].metadata == {}
    assert provider.contexts[1].metadata == {"changed": True}


def test_scripted_llm_raises_after_script_is_exhausted() -> None:
    provider = ScriptedLLM((LLMResponse(content="only"),))
    context = ModelContext(run_id=uuid4(), task="task")
    provider.complete(context, ())
    with pytest.raises(MockScriptExhausted):
        provider.complete(context, ())


def test_scripted_streaming_llm_emits_deltas_before_response() -> None:
    provider = ScriptedStreamingLLM(("one", "two"), LLMResponse(content="onetwo"))
    deltas: list[str] = []
    response = provider.complete_stream(
        ModelContext(run_id=uuid4(), task="task"), (), deltas.append, lambda: False
    )
    assert deltas == ["one", "two"]
    assert response == LLMResponse(content="onetwo")
