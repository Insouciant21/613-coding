"""Lazy keyring-backed OpenAI SDK provider composition."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from openai import OpenAI

from coding613.ports.llm import LLMResponse, ModelContext, ToolDefinition

from .openai_compatible import OpenAICompatibleLLM, SDKClient


class ProviderCredentialError(RuntimeError):
    """Raised without exposing secret material when a provider key is unavailable."""


SDKClientFactory = Callable[[str, str, float], SDKClient]
SecretReader = Callable[[str], str]


def _default_client(api_key: str, base_url: str, timeout: float) -> SDKClient:
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0,
    )


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
        client_factory: SDKClientFactory | None = None,
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
        return self._delegate_or_build().complete(context, tools)

    def complete_stream(
        self,
        context: ModelContext,
        tools: Sequence[ToolDefinition],
        on_text_delta: Callable[[str], None],
        cancelled: Callable[[], bool],
    ) -> LLMResponse:
        return self._delegate_or_build().complete_stream(
            context, tools, on_text_delta, cancelled
        )

    def close(self) -> None:
        """Release the ephemeral SDK client without returning key material."""

        if self._delegate is not None:
            self._delegate.close()

    def _delegate_or_build(self) -> OpenAICompatibleLLM:
        delegate = self._delegate
        if delegate is None:
            delegate = self._build_delegate()
            self._delegate = delegate
        return delegate

    def _build_delegate(self) -> OpenAICompatibleLLM:
        try:
            secret = self._read_secret(self._provider)
            if not secret:
                raise ValueError("empty credential")
            client = self._client_factory(secret, self._base_url, self._timeout_seconds)
        except Exception as error:
            raise ProviderCredentialError("provider credential is unavailable") from error
        return OpenAICompatibleLLM(
            self._base_url,
            self._model,
            client,
            timeout_seconds=self._timeout_seconds,
        )
