from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from coding613.adapters.llm.openai_compatible import ProviderResponseError
from coding613.adapters.llm.responses import ResponsesLLM
from coding613.domain.actions import FinishAction, ToolCall
from coding613.ports.llm import ModelContext, ModelMessage, ToolDefinition


class _Responses:
    def __init__(self, response: object, stream: object | None = None) -> None:
        self.response = response
        self.stream = stream
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.stream if kwargs.get("stream") is True else self.response


class _Client:
    def __init__(self, response: object, stream: object | None = None) -> None:
        self.responses = _Responses(response, stream)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Stream:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.closed = False

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield from self.events

    def close(self) -> None:
        self.closed = True


def _context() -> ModelContext:
    return ModelContext(
        run_id=uuid4(),
        task="inspect a.py",
        messages=(
            ModelMessage(role="system", content="You are a coding worker."),
            ModelMessage(role="user", content="inspect a.py"),
        ),
    )


def _tool() -> ToolDefinition:
    return ToolDefinition(
        name="read_file",
        description="Read a repository file",
        input_schema={
            "$id": "coding613.tool.read_file.v1",
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
    )


def test_responses_adapter_maps_messages_flat_tools_and_output_items() -> None:
    response = SimpleNamespace(
        output=[
            SimpleNamespace(type="reasoning", content=[]),
            SimpleNamespace(
                type="function_call",
                call_id="call-1",
                name="read_file",
                arguments='{"path":"a.py"}',
            ),
        ],
        output_text="",
    )
    client = _Client(response)
    provider = ResponsesLLM(
        "https://api.openai.com/v1", "gpt-5.6", client, max_output_tokens=777
    )

    result = provider.complete(_context(), (_tool(),))

    request = client.responses.calls[0]
    assert request["model"] == "gpt-5.6"
    assert request["input"] == [
        {"role": "system", "content": "You are a coding worker."},
        {"role": "user", "content": "inspect a.py"},
    ]
    assert request["max_output_tokens"] == 777
    assert request["store"] is False
    assert request["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a repository file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        }
    ]
    assert result.actions[0].action == ToolCall(
        name="read_file", arguments={"path": "a.py"}
    )
    assert result.provider_metadata["tool_call_ids"] == ["call-1"]


def test_responses_adapter_forwards_hosted_tool_payload_and_records_call() -> None:
    hosted = ToolDefinition(
        name="web_search",
        description="Search the web using the provider-hosted tool",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        transport="responses_hosted",
        provider_payload={"type": "web_search", "search_context_size": "low"},
    )
    response = SimpleNamespace(
        output=[
            SimpleNamespace(type="web_search_call", id="ws-1", status="completed"),
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="found it")],
            ),
        ],
        output_text="found it",
    )
    client = _Client(response)

    result = ResponsesLLM("https://api.openai.com/v1", "gpt-5.6", client).complete(
        _context(), (hosted,)
    )

    assert client.responses.calls[0]["tools"] == [
        {"type": "web_search", "search_context_size": "low"}
    ]
    assert result.content == "found it"
    assert result.provider_metadata["hosted_tool_calls"] == [
        {"type": "web_search_call", "id": "ws-1", "status": "completed"}
    ]


def test_responses_adapter_maps_shell_call_to_governed_action_and_preserves_item() -> None:
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="shell_call",
                id="shell-item",
                call_id="shell-call",
                status="completed",
                action=SimpleNamespace(
                    commands=["printf ok"],
                    timeout_ms=1500,
                    max_output_length=200,
                ),
            )
        ]
    )

    result = ResponsesLLM("https://api.openai.com/v1", "gpt-5.6", _Client(response)).complete(
        _context(), ()
    )

    assert result.actions[0].action == ToolCall(
        name="run_shell",
        arguments={
            "commands": [
                {
                    "argv": ["printf", "ok"],
                    "timeout_seconds": 1.5,
                    "max_output_bytes": 200,
                }
            ]
        },
        provider_metadata={
            "provider": "responses",
            "call_id": "shell-call",
            "item_type": "shell_call",
        },
    )
    assert result.provider_metadata["output_items"][0]["type"] == "shell_call"


def test_responses_messages_append_hosted_tool_continuation_items() -> None:
    context = _context().model_copy(
        update={
            "metadata": {
                "responses_input_items": [
                    {"type": "shell_call", "call_id": "shell-call"},
                    {
                        "type": "shell_call_output",
                        "call_id": "shell-call",
                        "output": [],
                    },
                ]
            }
        }
    )
    response = SimpleNamespace(output=[])
    client = _Client(response)

    ResponsesLLM("https://api.openai.com/v1", "gpt-5.6", client).complete(context, ())

    assert client.responses.calls[0]["input"][-2:] == [
        {"type": "shell_call", "call_id": "shell-call"},
        {
            "type": "shell_call_output",
            "call_id": "shell-call",
            "output": [],
        },
    ]


def test_responses_adapter_sends_configured_reasoning_effort() -> None:
    response = SimpleNamespace(output=[], output_text="")
    client = _Client(response)
    provider = ResponsesLLM(
        "https://api.deepseek.com",
        "deepseek-v4-flash",
        client,
        reasoning_effort="low",
    )

    provider.complete(_context(), ())

    assert client.responses.calls[0]["reasoning"] == {"effort": "low"}


def test_responses_adapter_maps_output_text_finish_and_usage() -> None:
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="verified")],
            ),
            SimpleNamespace(
                type="function_call",
                call_id="call-finish",
                name="finish",
                arguments='{"summary":"verified"}',
            ),
        ],
        output_text="verified",
        usage=SimpleNamespace(
            input_tokens=12,
            output_tokens=9,
            total_tokens=21,
            input_tokens_details=SimpleNamespace(cached_tokens=8, cache_write_tokens=4),
            output_tokens_details=SimpleNamespace(reasoning_tokens=3),
        ),
    )
    provider = ResponsesLLM(
        "https://api.openai.com/v1", "gpt-5.6", _Client(response)
    )

    result = provider.complete(_context(), ())

    assert result.content == "verified"
    assert result.actions[0].action == FinishAction(summary="verified")
    assert result.provider_metadata["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 9,
        "total_tokens": 21,
        "prompt_cache_hit_tokens": 8,
        "prompt_cache_miss_tokens": 4,
        "prompt_cache_write_tokens": 4,
        "reasoning_tokens": 3,
    }


def test_responses_adapter_rejects_malformed_function_call() -> None:
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="function_call",
                call_id="call-1",
                name="read_file",
                arguments="[]",
            )
        ]
    )
    provider = ResponsesLLM("https://api.openai.com/v1", "gpt-5.6", _Client(response))

    with pytest.raises(ProviderResponseError):
        provider.complete(_context(), ())


def test_responses_adapter_streams_text_and_function_arguments() -> None:
    function_item = SimpleNamespace(
        id="call-item-1",
        type="function_call",
        call_id="call-1",
        name="read_file",
        arguments="",
    )
    completed_item = SimpleNamespace(
        id="call-item-1",
        type="function_call",
        call_id="call-1",
        name="read_file",
        arguments='{"path":"a.py"}',
    )
    response = SimpleNamespace(
        output=[],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
    )
    stream = _Stream(
        [
            SimpleNamespace(type="response.output_item.added", item=function_item),
            SimpleNamespace(
                type="response.output_text.delta", delta="done", item_id="msg-1"
            ),
            SimpleNamespace(
                type="response.function_call_arguments.delta",
                item_id="call-item-1",
                delta='{"path":"a.py"}',
            ),
            SimpleNamespace(
                type="response.function_call_arguments.done",
                item_id="call-item-1",
                # DeepSeek returns the function name on output_item.added and
                # omits it on the arguments.done event.
                name=None,
                arguments='{"path":"a.py"}',
            ),
            SimpleNamespace(type="response.output_item.done", item=completed_item),
            SimpleNamespace(type="response.completed", response=response),
        ]
    )
    client = _Client(response, stream)
    provider = ResponsesLLM(
        "https://api.openai.com/v1", "gpt-5.6", client, max_output_tokens=777
    )
    deltas: list[str] = []

    result = provider.complete_stream(_context(), (_tool(),), deltas.append, lambda: False)

    assert deltas == ["done"]
    assert result.content == "done"
    assert result.actions[0].action == ToolCall(
        name="read_file", arguments={"path": "a.py"}
    )
    assert result.provider_metadata["usage"]["total_tokens"] == 15
    assert stream.closed is True
    request = client.responses.calls[0]
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}


@pytest.mark.parametrize("streaming", [False, True])
def test_explicit_cache_marks_stable_prefix_before_ledger(streaming: bool) -> None:
    final = SimpleNamespace(output=[], output_text="OK")
    stream = _Stream([SimpleNamespace(type="response.completed", response=final)])
    client = _Client(final, stream)
    context = _context().model_copy(update={"messages": _context().messages + (
        ModelMessage(role="user", content="Run ledger (state): current", name="run_ledger"),
    )})
    provider = ResponsesLLM("https://provider.invalid", "model", client,
                            prompt_cache_explicit=True)
    if streaming:
        provider.complete_stream(context, (), lambda _: None, lambda: False)
    else:
        provider.complete(context, ())
    request = client.responses.calls[0]
    assert request["extra_body"] == {"prompt_cache_options": {"mode": "explicit"}}
    assert request["input"][-2]["content"] == [{
        "type": "input_text", "text": "inspect a.py",
        "prompt_cache_breakpoint": {"mode": "explicit"},
    }]
    assert request["input"][-1]["content"] == "Run ledger (state): current"
    assert context.messages[-2].content == "inspect a.py"


def test_responses_continuation_precedes_volatile_ledger() -> None:
    continuation = [
        {"type": "shell_call", "call_id": "call-1"},
        {"type": "shell_call_output", "call_id": "call-1", "output": []},
    ]
    context = _context().model_copy(update={
        "messages": _context().messages + (
            ModelMessage(role="user", content="Run ledger (state): current", name="run_ledger"),
        ),
        "metadata": {"responses_input_items": continuation},
    })
    client = _Client(SimpleNamespace(output=[]))
    ResponsesLLM("https://provider.invalid", "model", client).complete(context, ())
    request = client.responses.calls[0]
    assert request["input"][-3:-1] == continuation
    assert request["input"][-1]["content"] == "Run ledger (state): current"
    assert "extra_body" not in request


def test_explicit_cache_configuration_reaches_composed_provider() -> None:
    from coding613.application.composition import _build_provider
    from coding613.config import LLMConfig

    client = _Client(SimpleNamespace(output=[]))
    provider = _build_provider(
        LLMConfig(api="responses", prompt_cache_explicit=True),
        SimpleNamespace(read_secret=lambda _: "test-only-token"),
        lambda *_: client,
        None,
    )
    context = _context().model_copy(update={"messages": _context().messages + (
        ModelMessage(role="user", content="current state", name="run_ledger"),
    )})
    provider.complete(context, ())
    assert client.responses.calls[0]["extra_body"] == {
        "prompt_cache_options": {"mode": "explicit"}
    }


def test_explicit_cache_is_omitted_without_a_trusted_boundary() -> None:
    client = _Client(SimpleNamespace(output=[]))
    provider = ResponsesLLM("https://provider.invalid", "model", client,
                            prompt_cache_explicit=True)
    context = _context().model_copy(update={"messages": _context().messages + (
        ModelMessage(role="user", content="Run ledger (user supplied imitation)"),
    )})
    provider.complete(context, ())
    assert "extra_body" not in client.responses.calls[0]
    assert all(isinstance(item["content"], str) for item in client.responses.calls[0]["input"])
