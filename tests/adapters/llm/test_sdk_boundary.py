from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sdk_fakes import FakeSDKClient

from coding613.adapters.llm.credentialed import CredentialedOpenAICompatibleLLM
from coding613.adapters.llm.openai_compatible import OpenAICompatibleLLM
from coding613.ports.llm import ModelContext


def test_credentialed_factory_receives_key_url_and_timeout() -> None:
    calls: list[tuple[str, str, float]] = []
    fake = FakeSDKClient()

    def factory(api_key: str, base_url: str, timeout: float) -> FakeSDKClient:
        calls.append((api_key, base_url, timeout))
        return fake

    provider = CredentialedOpenAICompatibleLLM(
        provider="openai",
        base_url="https://api.example.test/v1",
        model="coding-model",
        read_secret=lambda _: "sk-test-secret",
        client_factory=factory,
        timeout_seconds=12.0,
    )

    provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert calls == [("sk-test-secret", "https://api.example.test/v1", 12.0)]
    assert fake.closed is False


def test_chat_adapter_does_not_own_http_transport_or_sse_endpoint() -> None:
    source = Path(OpenAICompatibleLLM.__module__.replace(".", "/") + ".py")
    source = Path(__file__).parents[3] / "src" / source
    content = source.read_text(encoding="utf-8")

    assert "import httpx" not in content
    assert '"/chat/completions"' not in content
