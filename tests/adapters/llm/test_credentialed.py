from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import httpx
import pytest

from coding613.adapters.llm.credentialed import (
    CredentialedOpenAICompatibleLLM,
    ProviderCredentialError,
)
from coding613.domain.actions import ToolCall
from coding613.ports.llm import ModelContext, ToolDefinition


class _Reader:
    def __init__(self, value: str | None) -> None:
        self.value = value
        self.calls: list[str] = []

    def read_secret(self, provider: str) -> str:
        self.calls.append(provider)
        if self.value is None:
            raise RuntimeError("missing secret")
        return self.value


def test_credentialed_provider_reads_key_lazily_and_sends_auth_header() -> None:
    reader = _Reader("sk-test-secret")
    captured: dict[str, str] = {}

    def factory(headers: dict[str, str], timeout: float) -> httpx.Client:
        captured.update(headers)
        assert timeout == 12.0

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer sk-test-secret"
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

        return httpx.Client(headers=headers, transport=httpx.MockTransport(handler))

    provider = CredentialedOpenAICompatibleLLM(
        provider="openai",
        base_url="https://api.example.test/v1",
        model="coding-model",
        read_secret=reader.read_secret,
        client_factory=factory,
        timeout_seconds=12.0,
    )
    context = ModelContext(run_id=uuid4(), task="read a.py")
    tools: Sequence[ToolDefinition] = (
        ToolDefinition(name="read_file", description="Read", input_schema={"type": "object"}),
    )

    assert reader.calls == []
    response = provider.complete(context, tools)

    assert reader.calls == ["openai"]
    assert captured["Authorization"] == "Bearer sk-test-secret"
    assert response.actions[0].action == ToolCall(
        name="read_file", arguments={"path": "a.py"}
    )


def test_credentialed_provider_does_not_expose_missing_secret() -> None:
    provider = CredentialedOpenAICompatibleLLM(
        provider="openai",
        base_url="https://api.example.test/v1",
        model="coding-model",
        read_secret=lambda provider: (_ for _ in ()).throw(RuntimeError("secret-value")),
    )

    with pytest.raises(ProviderCredentialError) as error:
        provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert "secret-value" not in str(error.value)
