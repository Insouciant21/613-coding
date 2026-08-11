from __future__ import annotations

from collections.abc import Iterator
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from sdk_fakes import (
    FakeChunk,
    FakeCompletion,
    FakeFunction,
    FakeMessage,
    FakeSDKClient,
    FakeStream,
    FakeToolCall,
    FakeToolDelta,
)

from coding613.adapters.llm.openai_compatible import (
    OpenAICompatibleLLM,
    ProviderAuthenticationError,
    ProviderHTTPError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from coding613.application.progress import ProviderCancelledError
from coding613.domain.actions import FinishAction, ToolCall
from coding613.ports.llm import ModelContext, ModelMessage, ToolDefinition


class _CloseAwareStream:
    def __init__(self) -> None:
        self._release = Event()
        self.iteration_finished = Event()
        self.closed = False

    def __iter__(self) -> Iterator[object]:
        self._release.wait(timeout=1.0)
        self.iteration_finished.set()
        return iter(())

    def close(self) -> None:
        self.closed = True
        self._release.set()


def test_openai_adapter_maps_sdk_request_and_tool_response() -> None:
    client = FakeSDKClient(
        completion=FakeCompletion(
            FakeMessage(
                content="",
                tool_calls=(FakeToolCall("call-1", "read_file", '{"path":"a.py"}'),),
            )
        )
    )
    provider = OpenAICompatibleLLM(
        base_url="https://provider.invalid/v1", model="test-model", client=client
    )
    context = ModelContext(
        run_id=uuid4(),
        task="read a.py",
        messages=(ModelMessage(role="user", content="read a.py"),),
    )
    definition = ToolDefinition(
        name="read_file", description="Read file", input_schema={"type": "object"}
    )

    response = provider.complete(context, (definition,))

    call = client.chat.completions.calls[0]
    assert call["model"] == "test-model"
    assert call["messages"] == [{"role": "user", "content": "read a.py"}]
    assert call["tools"][0]["function"]["parameters"] == {"type": "object"}
    assert response.actions[0].action == ToolCall(
        name="read_file", arguments={"path": "a.py"}
    )
    assert response.provider_metadata["tool_call_ids"] == ["call-1"]


def test_openai_adapter_uses_context_model_override() -> None:
    client = FakeSDKClient(completion=FakeCompletion(FakeMessage(content="ok")))
    provider = OpenAICompatibleLLM(
        base_url="https://provider.invalid/v1", model="configured-model", client=client
    )

    provider.complete(
        ModelContext(run_id=uuid4(), task="task", metadata={"model": "gpt-test"}),
        (),
    )

    assert client.chat.completions.calls[0]["model"] == "gpt-test"


def test_openai_adapter_sends_configured_output_limit() -> None:
    client = FakeSDKClient(completion=FakeCompletion(FakeMessage(content="ok")))
    provider = OpenAICompatibleLLM(
        "https://provider.invalid", "model", client, max_output_tokens=1234
    )

    provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert client.chat.completions.calls[0]["max_tokens"] == 1234


def test_openai_adapter_sends_non_default_reasoning_effort() -> None:
    client = FakeSDKClient(completion=FakeCompletion(FakeMessage(content="ok")))
    provider = OpenAICompatibleLLM(
        "https://provider.invalid", "model", client, reasoning_effort="high"
    )

    provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert client.chat.completions.calls[0]["reasoning_effort"] == "high"


def test_openai_adapter_forwards_provider_specific_reasoning_effort() -> None:
    client = FakeSDKClient(completion=FakeCompletion(FakeMessage(content="ok")))
    provider = OpenAICompatibleLLM(
        "https://provider.invalid", "model", client, reasoning_effort="xhigh"
    )

    provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert client.chat.completions.calls[0]["reasoning_effort"] == "xhigh"


def test_openai_adapter_records_numeric_usage_metadata() -> None:
    completion = FakeCompletion(FakeMessage(content="ok"))
    completion.usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=8,
        total_tokens=18,
        prompt_cache_hit_tokens=7,
        prompt_cache_miss_tokens=3,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
    )
    client = FakeSDKClient(completion=completion)
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    response = provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert response.provider_metadata["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 8,
        "total_tokens": 18,
        "prompt_cache_hit_tokens": 7,
        "prompt_cache_miss_tokens": 3,
        "reasoning_tokens": 5,
    }


def test_openai_adapter_omits_local_schema_id_without_mutating_definition() -> None:
    client = FakeSDKClient(completion=FakeCompletion(FakeMessage(content="ok")))
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)
    definition = ToolDefinition(
        name="apply_patch",
        description="Apply patch",
        input_schema={"$id": "coding613.tool.apply_patch.v1", "type": "object"},
    )

    provider.complete(ModelContext(run_id=uuid4(), task="patch"), (definition,))

    assert client.chat.completions.calls[0]["tools"][0]["function"]["parameters"] == {
        "type": "object"
    }
    assert definition.input_schema["$id"] == "coding613.tool.apply_patch.v1"


def test_openai_adapter_rejects_invalid_response() -> None:
    client = FakeSDKClient()
    client.chat.completions.completion = SimpleNamespace(choices=[])
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    with pytest.raises(ProviderResponseError):
        provider.complete(ModelContext(run_id=uuid4(), task="task"), ())


@pytest.mark.parametrize("message", [None, "text", []])
def test_openai_adapter_rejects_non_object_response_messages(message: object) -> None:
    client = FakeSDKClient()
    client.chat.completions.completion = SimpleNamespace(
        choices=[SimpleNamespace(message=message)]
    )
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    with pytest.raises(ProviderResponseError):
        provider.complete(ModelContext(run_id=uuid4(), task="task"), ())


def test_openai_adapter_maps_finish_tool_call() -> None:
    client = FakeSDKClient(
        completion=FakeCompletion(
            FakeMessage(
                content="",
                tool_calls=(FakeToolCall("call-finish", "finish", '{"summary":"verified"}'),),
            )
        )
    )
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    response = provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert response.actions[0].action == FinishAction(summary="verified")


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://provider.invalid/v1/chat/completions")


@pytest.mark.parametrize(
    ("error", "error_type"),
    [
        (APITimeoutError(_request()), ProviderTimeoutError),
        (APIConnectionError(request=_request()), ProviderHTTPError),
        (
            AuthenticationError(
                "bad auth", response=httpx.Response(401, request=_request()), body=None
            ),
            ProviderAuthenticationError,
        ),
        (
            PermissionDeniedError(
                "forbidden", response=httpx.Response(403, request=_request()), body=None
            ),
            ProviderAuthenticationError,
        ),
        (
            RateLimitError(
                "rate limit", response=httpx.Response(429, request=_request()), body=None
            ),
            ProviderRateLimitError,
        ),
        (
            APIStatusError(
                "bad request",
                response=httpx.Response(400, request=_request()),
                body={"error": {"message": "invalid request"}},
            ),
            ProviderRequestError,
        ),
    ],
)
def test_openai_adapter_maps_sdk_errors(
    error: Exception, error_type: type[Exception]
) -> None:
    client = FakeSDKClient(error=error)
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    with pytest.raises(error_type):
        provider.complete(ModelContext(run_id=uuid4(), task="task"), ())


def test_openai_adapter_streams_sdk_text_and_split_tool_arguments() -> None:
    stream = FakeStream(
        [
            FakeChunk(content="hel"),
            FakeChunk(
                content="lo",
                tool_call=FakeToolDelta("call-1", "read_file", '{"pa'),
            ),
            FakeChunk(tool_call=FakeToolDelta(None, None, 'th":"a.py"}')),
        ]
    )
    client = FakeSDKClient(stream=stream)
    provider = OpenAICompatibleLLM(
        "https://provider.invalid/v1", "model", client, max_output_tokens=1234
    )
    deltas: list[str] = []

    response = provider.complete_stream(
        ModelContext(run_id=uuid4(), task="read a.py"),
        (ToolDefinition(name="read_file", description="Read", input_schema={"type": "object"}),),
        deltas.append,
        lambda: False,
    )

    assert deltas == ["hel", "lo"]
    assert response.content == "hello"
    assert response.actions[0].action == ToolCall(
        name="read_file", arguments={"path": "a.py"}
    )
    assert response.provider_metadata["tool_call_ids"] == ["call-1"]
    assert stream.closed is True
    assert client.chat.completions.calls[0]["stream"] is True
    assert client.chat.completions.calls[0]["max_tokens"] == 1234
    assert client.chat.completions.calls[0]["stream_options"] == {"include_usage": True}


def test_openai_adapter_records_stream_usage_chunk() -> None:
    usage_chunk = FakeChunk()
    usage_chunk.usage = SimpleNamespace(
        prompt_tokens=4,
        completion_tokens=2,
        total_tokens=6,
        prompt_cache_hit_tokens=3,
        prompt_cache_miss_tokens=1,
    )
    stream = FakeStream([FakeChunk(content="ok"), usage_chunk])
    client = FakeSDKClient(stream=stream)
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    response = provider.complete_stream(
        ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False
    )

    assert response.provider_metadata["usage"]["prompt_cache_hit_tokens"] == 3


def test_openai_adapter_rejects_empty_stream() -> None:
    stream = FakeStream(())
    client = FakeSDKClient(stream=stream)
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    with pytest.raises(ProviderResponseError):
        provider.complete_stream(
            ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False
        )
    assert stream.closed is True


def test_openai_adapter_maps_stream_iteration_error_and_closes() -> None:
    error = APIConnectionError(request=_request())
    stream = FakeStream((), iteration_error=error)
    client = FakeSDKClient(stream=stream)
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    with pytest.raises(ProviderHTTPError):
        provider.complete_stream(
            ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False
        )
    assert stream.closed is True


def test_openai_adapter_reports_stream_cleanup_error() -> None:
    stream = FakeStream([FakeChunk(content="ok")], close_error=RuntimeError("close failed"))
    client = FakeSDKClient(stream=stream)
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    with pytest.raises(ProviderHTTPError):
        provider.complete_stream(
            ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False
        )
    assert stream.closed is True


def test_openai_adapter_stream_checks_cancellation_after_text_delta() -> None:
    stream = FakeStream([FakeChunk(content="hello"), FakeChunk(content="world")])
    client = FakeSDKClient(stream=stream)
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)
    cancelled = False

    def on_delta(_: str) -> None:
        nonlocal cancelled
        cancelled = True

    with pytest.raises(ProviderCancelledError):
        provider.complete_stream(
            ModelContext(run_id=uuid4(), task="task"), (), on_delta, lambda: cancelled
        )
    assert stream.closed is True


def test_openai_adapter_enforces_absolute_stream_deadline() -> None:
    moments = iter((0.0, 0.4, 1.1))
    stream = FakeStream([FakeChunk()])
    client = FakeSDKClient(stream=stream)
    provider = OpenAICompatibleLLM(
        "https://provider.invalid", "model", client, timeout_seconds=1.0, clock=lambda: next(moments)
    )

    with pytest.raises(ProviderTimeoutError):
        provider.complete_stream(
            ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False
        )
    assert stream.closed is True


def test_openai_adapter_closes_stream_before_waiting_for_reader_thread() -> None:
    stream = _CloseAwareStream()
    client = FakeSDKClient(stream=stream)  # type: ignore[arg-type]
    provider = OpenAICompatibleLLM(
        "https://provider.invalid", "model", client, timeout_seconds=0.01
    )

    with pytest.raises(ProviderTimeoutError):
        provider.complete_stream(
            ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False
        )

    assert stream.closed is True
    assert stream.iteration_finished.is_set() is True


@pytest.mark.parametrize(
    "tool_calls",
    [
        {},
        [SimpleNamespace(index="0", id="call-1", function=FakeFunction("read_file", "{}"))],
        [SimpleNamespace(index=0, id=1, function=FakeFunction("read_file", "{}"))],
        [SimpleNamespace(index=0, id="call-1", function=FakeFunction(1, "{}"))],
        [SimpleNamespace(index=0, id="call-1", function="read_file")],
    ],
)
def test_openai_adapter_rejects_invalid_stream_tool_call_containers(
    tool_calls: object,
) -> None:
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                index=0,
                delta=SimpleNamespace(content=None, tool_calls=tool_calls),
            )
        ]
    )
    stream = FakeStream((chunk,))
    client = FakeSDKClient(stream=stream)
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    with pytest.raises(ProviderResponseError):
        provider.complete_stream(
            ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False
        )
    assert stream.closed is True


def test_openai_adapter_rejects_stream_tool_call_without_provider_id() -> None:
    stream = FakeStream(
        [FakeChunk(tool_call=FakeToolDelta(None, "read_file", "{}"))]
    )
    client = FakeSDKClient(stream=stream)
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    with pytest.raises(ProviderResponseError):
        provider.complete_stream(
            ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False
        )
    assert stream.closed is True


def test_openai_adapter_accepts_stream_tool_call_without_function_fragment() -> None:
    first = SimpleNamespace(
        choices=[
            SimpleNamespace(
                index=0,
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[SimpleNamespace(index=0, id="call-1", type="function", function=None)],
                ),
            )
        ]
    )
    second = FakeChunk(tool_call=FakeToolDelta(None, "read_file", "{}"))
    stream = FakeStream((first, second))
    client = FakeSDKClient(stream=stream)
    provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)

    response = provider.complete_stream(
        ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False
    )

    assert response.actions[0].action == ToolCall(name="read_file", arguments={})
    assert response.provider_metadata["tool_call_ids"] == ["call-1"]
    assert stream.closed is True
