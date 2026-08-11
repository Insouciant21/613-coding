from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sdk_fakes import (
    FakeChunk,
    FakeCompletion,
    FakeMessage,
    FakeSDKClient,
    FakeStream,
    empty_completion,
)

import coding613.adapters.llm.credentialed as credentialed_module
from coding613.adapters.llm.credentialed import (
    CredentialedOpenAICompatibleLLM,
    CredentialedResponsesLLM,
    ProviderCredentialError,
)
from coding613.ports.llm import ModelContext, ModelMessage


class _Reader:
    def __init__(self, value: str | None) -> None:
        self.value = value
        self.calls: list[str] = []

    def read_secret(self, provider: str) -> str:
        self.calls.append(provider)
        if self.value is None:
            raise RuntimeError("missing secret")
        return self.value


def test_credentialed_provider_reads_key_lazily_and_reuses_sdk_client() -> None:
    reader = _Reader("sk-test-secret")
    client_creations: list[tuple[str, str, float]] = []
    client = FakeSDKClient(
        completion=FakeCompletion(
            FakeMessage(content="ok")
        )
    )

    def factory(api_key: str, base_url: str, timeout: float) -> FakeSDKClient:
        client_creations.append((api_key, base_url, timeout))
        return client

    provider = CredentialedOpenAICompatibleLLM(
        provider="openai",
        base_url="https://api.example.test/v1",
        model="coding-model",
        read_secret=reader.read_secret,
        client_factory=factory,
        timeout_seconds=12.0,
    )
    context = ModelContext(
        run_id=uuid4(),
        task="task",
        messages=(ModelMessage(role="user", content="task"),),
    )

    assert reader.calls == []
    provider.complete(context, ())
    provider.complete(context, ())

    assert reader.calls == ["openai"]
    assert client_creations == [("sk-test-secret", "https://api.example.test/v1", 12.0)]
    assert len(client.chat.completions.calls) == 2


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
    assert error.value.__cause__ is None


def test_credentialed_provider_closes_client_when_delegate_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSDKClient()

    def fail_delegate(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("sk-client-secret")

    monkeypatch.setattr(credentialed_module, "OpenAICompatibleLLM", fail_delegate)
    provider = CredentialedOpenAICompatibleLLM(
        provider="openai",
        base_url="https://api.example.test/v1",
        model="coding-model",
        read_secret=lambda _: "sk-client-secret",
        client_factory=lambda *_: client,
    )

    with pytest.raises(ProviderCredentialError) as error:
        provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert "sk-client-secret" not in str(error.value)
    assert error.value.__cause__ is None
    assert client.closed is True


def test_credentialed_provider_delegates_streaming_lazily() -> None:
    reader = _Reader("sk-test-secret")
    client_creations = 0
    client = FakeSDKClient(stream=FakeStream((FakeChunk(content="stream"),)))

    def factory(api_key: str, base_url: str, timeout: float) -> FakeSDKClient:
        nonlocal client_creations
        client_creations += 1
        assert (api_key, base_url, timeout) == (
            "sk-test-secret",
            "https://api.example.test/v1",
            60.0,
        )
        return client

    provider = CredentialedOpenAICompatibleLLM(
        provider="openai",
        base_url="https://api.example.test/v1",
        model="coding-model",
        read_secret=reader.read_secret,
        client_factory=factory,
    )
    deltas: list[str] = []

    response = provider.complete_stream(
        ModelContext(run_id=uuid4(), task="first"), (), deltas.append, lambda: False
    )

    assert response.content == "stream"
    assert deltas == ["stream"]
    assert reader.calls == ["openai"]
    assert client_creations == 1


def test_credentialed_provider_closes_sdk_client() -> None:
    client = FakeSDKClient(completion=empty_completion())
    provider = CredentialedOpenAICompatibleLLM(
        provider="openai",
        base_url="https://api.example.test/v1",
        model="coding-model",
        read_secret=lambda _: "secret",
        client_factory=lambda *_: client,
    )

    provider.complete(ModelContext(run_id=uuid4(), task="task"), ())
    provider.close()

    assert client.closed is True


def test_credentialed_responses_provider_uses_responses_surface_lazily() -> None:
    reader = _Reader("sk-responses-secret")

    class _Responses:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def create(self, **kwargs: object) -> SimpleNamespace:
            self.calls.append(kwargs)
            return SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", text="ok")],
                    )
                ]
            )

    class _ResponsesClient:
        def __init__(self) -> None:
            self.responses = _Responses()
            self.closed = False

        def close(self) -> None:
            self.closed = True

    client = _ResponsesClient()
    provider = CredentialedResponsesLLM(
        provider="openai",
        base_url="https://api.example.test/v1",
        model="coding-model",
        read_secret=reader.read_secret,
        client_factory=lambda *_: client,  # type: ignore[arg-type]
        streaming=True,
    )

    response = provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert response.content == "ok"
    assert provider.streaming_enabled is True
    assert reader.calls == ["openai"]
    assert len(client.responses.calls) == 1


def test_default_client_uses_sdk_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    client = FakeSDKClient()

    def fake_openai(**kwargs: object) -> FakeSDKClient:
        captured.update(kwargs)
        return client

    monkeypatch.setattr(credentialed_module, "OpenAI", fake_openai)

    result = credentialed_module._default_client(
        "sk-test-secret", "https://api.example.test/v1", 12.0
    )

    assert result is client
    assert captured == {
        "api_key": "sk-test-secret",
        "base_url": "https://api.example.test/v1",
        "timeout": 12.0,
        "max_retries": 0,
    }
