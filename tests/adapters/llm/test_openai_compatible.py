from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from coding613.adapters.llm.openai_compatible import (
    OpenAICompatibleLLM,
    ProviderAuthenticationError,
    ProviderHTTPError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from coding613.application.progress import ProviderCancelledError
from coding613.domain.actions import FinishAction, ToolCall
from coding613.ports.llm import ModelContext, ModelMessage, ToolDefinition


def test_openai_adapter_maps_request_and_validates_tool_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert payload["model"] == "test-model"
        assert payload["messages"] == [{"role": "user", "content": "read a.py"}]
        assert payload["tools"][0]["function"]["parameters"] == {"type": "object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":"a.py"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleLLM(
            base_url="https://provider.invalid/v1", model="test-model", http_client=client
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
    assert response.actions[0].action == ToolCall(
        name="read_file", arguments={"path": "a.py"}
    )
    assert response.provider_metadata["tool_call_ids"] == ["call-1"]


def test_openai_adapter_rejects_invalid_response() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": []}))
    with httpx.Client(transport=transport) as client:
        provider = OpenAICompatibleLLM(
            base_url="https://provider.invalid", model="test-model", http_client=client
        )
        with pytest.raises(ProviderResponseError):
            provider.complete(ModelContext(run_id=uuid4(), task="task"), ())


@pytest.mark.parametrize("message", [None, "text", []])
def test_openai_adapter_rejects_non_object_response_messages(message: object) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": message}]})
    )
    with httpx.Client(transport=transport) as client:
        provider = OpenAICompatibleLLM(
            base_url="https://provider.invalid", model="test-model", http_client=client
        )
        with pytest.raises(ProviderResponseError):
            provider.complete(ModelContext(run_id=uuid4(), task="task"), ())


def test_openai_adapter_maps_finish_tool_call() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-finish",
                                    "type": "function",
                                    "function": {
                                        "name": "finish",
                                        "arguments": '{"summary":"verified"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            request=request,
        )
    )
    with httpx.Client(transport=transport) as client:
        provider = OpenAICompatibleLLM(
            base_url="https://provider.invalid", model="test-model", http_client=client
        )

        response = provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert response.actions[0].action == FinishAction(summary="verified")


def test_openai_adapter_maps_timeout() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        provider = OpenAICompatibleLLM(
            base_url="https://provider.invalid", model="test-model", http_client=client
        )
        with pytest.raises(ProviderTimeoutError):
            provider.complete(ModelContext(run_id=uuid4(), task="task"), ())


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, ProviderAuthenticationError), (429, ProviderRateLimitError)],
)
def test_openai_adapter_maps_status_errors(
    status: int, error_type: type[Exception]
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, request=request))
    with httpx.Client(transport=transport) as client:
        provider = OpenAICompatibleLLM(
            base_url="https://provider.invalid", model="test-model", http_client=client
        )
        with pytest.raises(error_type):
            provider.complete(ModelContext(run_id=uuid4(), task="task"), ())


def test_openai_adapter_streams_text_and_split_tool_arguments() -> None:
    events = [
        'data: {"choices":[{"index":0,"delta":{"content":"hel"}}]}\n\n',
        'data: {"choices":[{"index":0,"delta":{"content":"lo","tool_calls":[{"index":0,"id":"call-1","function":{"name":"read_file","arguments":"{\\"pa"}}]}}]}\n\n',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"th\\":\\"a.py\\"}"}}]}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(events))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleLLM("https://provider.invalid/v1", "model", client)
        deltas: list[str] = []
        response = provider.complete_stream(
            ModelContext(run_id=uuid4(), task="read a.py"),
            (ToolDefinition(name="read_file", description="Read", input_schema={"type": "object"}),),
            deltas.append,
            lambda: False,
        )
    assert deltas == ["hel", "lo"]
    assert response.content == "hello"
    assert response.actions[0].action == ToolCall(name="read_file", arguments={"path": "a.py"})
    assert response.provider_metadata["tool_call_ids"] == ["call-1"]


@pytest.mark.parametrize(
    "body",
    [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{"}}]}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n',
    ],
)
def test_openai_adapter_rejects_malformed_or_premature_sse(body: str) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body
        )
    )
    with httpx.Client(transport=transport) as client:
        provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)
        with pytest.raises(ProviderResponseError):
            provider.complete_stream(ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False)


def test_openai_adapter_maps_stream_http_failure() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    with httpx.Client(transport=transport) as client:
        provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)
        with pytest.raises(ProviderHTTPError):
            provider.complete_stream(ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False)


def test_openai_adapter_stream_checks_cancellation_between_records() -> None:
    events = (
        'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=events
        )
    )
    cancelled = False

    def on_delta(_: str) -> None:
        nonlocal cancelled
        cancelled = True

    def is_cancelled() -> bool:
        return cancelled

    with httpx.Client(transport=transport) as client:
        provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)
        with pytest.raises(ProviderCancelledError):
            provider.complete_stream(ModelContext(run_id=uuid4(), task="task"), (), on_delta, is_cancelled)


@pytest.mark.parametrize(
    "tool_calls",
    [
        {},
        [{"index": "0", "id": "call-1", "function": {"name": "read_file", "arguments": "{}"}}],
        [{"index": 0, "id": 1, "function": {"name": "read_file", "arguments": "{}"}}],
        [{"index": 0, "id": "call-1", "function": {"name": 1, "arguments": "{}"}}],
        [{"index": 0, "id": "call-1", "function": "read_file"}],
    ],
)
def test_openai_adapter_rejects_invalid_stream_tool_call_containers_and_fragments(
    tool_calls: object,
) -> None:
    event = json.dumps({"choices": [{"delta": {"tool_calls": tool_calls}}]})
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=f"data: {event}\n\ndata: [DONE]\n\n",
            request=request,
        )
    )
    with httpx.Client(transport=transport) as client:
        provider = OpenAICompatibleLLM("https://provider.invalid", "model", client)
        with pytest.raises(ProviderResponseError):
            provider.complete_stream(ModelContext(run_id=uuid4(), task="task"), (), lambda _: None, lambda: False)
