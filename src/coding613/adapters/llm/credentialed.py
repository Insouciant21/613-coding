"""Lazy keyring-backed OpenAI SDK provider composition."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from openai import OpenAI

from coding613.ports.llm import LLMResponse, ModelContext, ToolDefinition

from .anthropic import AnthropicLLM, AnthropicMessagesClient
from .openai_compatible import OpenAICompatibleLLM, SDKClient
from .responses import ResponsesLLM


class ProviderCredentialError(RuntimeError):
    """Raised without exposing secret material when a provider key is unavailable."""


SDKClientFactory = Callable[[str, str, float], SDKClient]
AnthropicClientFactory = Callable[[str, str | None, float], AnthropicMessagesClient]
SecretReader = Callable[[str], str]


def _default_client(api_key: str, base_url: str, timeout: float) -> SDKClient:
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0,
    )


def _default_anthropic_client(
    api_key: str, base_url: str | None, timeout: float
) -> AnthropicMessagesClient:
    from anthropic import Anthropic

    if base_url:
        return Anthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
        )
    return Anthropic(api_key=api_key, timeout=timeout, max_retries=0)


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
        max_output_tokens: int = 1536,
        reasoning_effort: str = "low",
        streaming: bool = False,
    ) -> None:
        self._provider = provider
        self._base_url = base_url
        self._model = model
        self._read_secret = read_secret
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self.streaming_enabled = streaming
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
        client: SDKClient | None = None
        try:
            secret = self._read_secret(self._provider)
            if not secret:
                raise ValueError("empty credential")
            client = self._client_factory(secret, self._base_url, self._timeout_seconds)
            return OpenAICompatibleLLM(
                self._base_url,
                self._model,
                client,
                timeout_seconds=self._timeout_seconds,
                max_output_tokens=self._max_output_tokens,
                reasoning_effort=self._reasoning_effort,
            )
        except Exception:  # noqa: BLE001 - hide reader/factory details at the credential boundary
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001 - cleanup cannot replace the generic error
                    client = None
            raise ProviderCredentialError("provider credential is unavailable") from None


class CredentialedResponsesLLM:
    """Lazy keyring-backed provider using ``client.responses.create``."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        read_secret: SecretReader,
        timeout_seconds: float = 60.0,
        client_factory: SDKClientFactory | None = None,
        max_output_tokens: int = 1536,
        reasoning_effort: str = "low",
        streaming: bool = False,
        prompt_cache_explicit: bool = False,
    ) -> None:
        self._provider = provider
        self._base_url = base_url
        self._model = model
        self._read_secret = read_secret
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self.streaming_enabled = streaming
        self._prompt_cache_explicit = prompt_cache_explicit
        self._client_factory = client_factory or _default_client
        self._delegate: ResponsesLLM | None = None

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
        if self._delegate is not None:
            self._delegate.close()

    def _delegate_or_build(self) -> ResponsesLLM:
        delegate = self._delegate
        if delegate is None:
            delegate = self._build_delegate()
            self._delegate = delegate
        return delegate

    def _build_delegate(self) -> ResponsesLLM:
        client: SDKClient | None = None
        try:
            secret = self._read_secret(self._provider)
            if not secret:
                raise ValueError("empty credential")
            client = self._client_factory(secret, self._base_url, self._timeout_seconds)
            return ResponsesLLM(
                self._base_url,
                self._model,
                client,
                timeout_seconds=self._timeout_seconds,
                max_output_tokens=self._max_output_tokens,
                reasoning_effort=self._reasoning_effort,
                prompt_cache_explicit=self._prompt_cache_explicit,
            )
        except Exception:  # noqa: BLE001 - hide reader/factory details at the credential boundary
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001 - cleanup cannot replace the generic error
                    client = None
            raise ProviderCredentialError("provider credential is unavailable") from None


class CredentialedAnthropicLLM:
    """Lazy keyring-backed Anthropic Messages provider."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str | None,
        model: str,
        read_secret: SecretReader,
        timeout_seconds: float = 60.0,
        client_factory: AnthropicClientFactory | None = None,
        max_output_tokens: int = 1536,
        reasoning_effort: str = "low",
        streaming: bool = False,
    ) -> None:
        self._provider = provider
        self._base_url = base_url
        self._model = model
        self._read_secret = read_secret
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self.streaming_enabled = streaming
        self._client_factory = client_factory or _default_anthropic_client
        self._delegate: AnthropicLLM | None = None

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
        if self._delegate is not None:
            self._delegate.close()

    def _delegate_or_build(self) -> AnthropicLLM:
        delegate = self._delegate
        if delegate is None:
            delegate = self._build_delegate()
            self._delegate = delegate
        return delegate

    def _build_delegate(self) -> AnthropicLLM:
        client: AnthropicMessagesClient | None = None
        try:
            secret = self._read_secret(self._provider)
            if not secret:
                raise ValueError("empty credential")
            client = self._client_factory(secret, self._base_url, self._timeout_seconds)
            return AnthropicLLM(
                self._base_url,
                self._model,
                client,
                timeout_seconds=self._timeout_seconds,
                max_output_tokens=self._max_output_tokens,
                reasoning_effort=self._reasoning_effort,
            )
        except Exception:  # noqa: BLE001 - hide reader/factory details at credential boundary
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001 - cleanup cannot replace generic error
                    client = None
            raise ProviderCredentialError("provider credential is unavailable") from None


__all__ = [
    "AnthropicClientFactory",
    "CredentialedAnthropicLLM",
    "CredentialedOpenAICompatibleLLM",
    "CredentialedResponsesLLM",
    "ProviderCredentialError",
    "SDKClientFactory",
]
