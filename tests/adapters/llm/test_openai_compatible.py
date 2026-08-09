from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from coding613.adapters.llm.openai_compatible import (
    OpenAICompatibleLLM,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from coding613.domain.actions import ToolCall
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
