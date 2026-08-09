"""Lazy keyring-backed OpenAI-compatible provider composition."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import httpx

from coding613.adapters.llm.openai_compatible import OpenAICompatibleLLM
from coding613.ports.llm import LLMResponse, ModelContext, ToolDefinition


class ProviderCredentialError(RuntimeError):
    """Raised without exposing secret material when a provider key is unavailable."""


ClientFactory = Callable[[dict[str, str], float], httpx.Client]
SecretReader = Callable[[str], str]


def _default_client(headers: dict[str, str], timeout: float) -> httpx.Client:
    return httpx.Client(headers=headers, timeout=timeout)


class CredentialedOpenAICompatibleLLM:
    """Resolve a credential only on first call and keep it out of domain state."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        read_secret: SecretReader,
        timeout_seconds: float = 60.0,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._provider = provider
        self._base_url = base_url
        self._model = model
        self._read_secret = read_secret
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory or _default_client
        self._delegate: OpenAICompatibleLLM | None = None

    def complete(
        self, context: ModelContext, tools: Sequence[ToolDefinition]
    ) -> LLMResponse:
        delegate = self._delegate
        if delegate is None:
            delegate = self._build_delegate()
            self._delegate = delegate
        return delegate.complete(context, tools)

    def complete_stream(
        self,
        context: ModelContext,
        tools: Sequence[ToolDefinition],
        on_text_delta: Callable[[str], None],
        cancelled: Callable[[], bool],
    ) -> LLMResponse:
        delegate = self._delegate
        if delegate is None:
            delegate = self._build_delegate()
            self._delegate = delegate
        return delegate.complete_stream(context, tools, on_text_delta, cancelled)

    def close(self) -> None:
        """Release the ephemeral HTTP client without returning its key material."""

        if self._delegate is not None:
            self._delegate.close()

    def _build_delegate(self) -> OpenAICompatibleLLM:
        try:
            secret = self._read_secret(self._provider)
            if not secret:
                raise ValueError("empty credential")
            client = self._client_factory(
                {"Authorization": f"Bearer {secret}"}, self._timeout_seconds
            )
        except Exception as error:
            raise ProviderCredentialError("provider credential is unavailable") from error
        return OpenAICompatibleLLM(self._base_url, self._model, client)
