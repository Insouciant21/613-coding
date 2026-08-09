from __future__ import annotations

from uuid import uuid4

import pytest

from coding613.adapters.llm.mock import MockScriptExhausted, ScriptedLLM
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
