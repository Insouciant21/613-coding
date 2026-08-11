"""Low-level Anthropic Messages API adapter.

The harness owns the agent loop and tool dispatch.  This module only translates
one model call to the official Anthropic SDK, mirroring the OpenAI adapters.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from coding613.application.progress import ProviderCancelledError
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.redaction import redact_text
from coding613.ports.llm import LLMResponse, ModelContext, ToolDefinition

from .openai_compatible import (
    OpenAICompatibleLLM,
    ProviderAuthenticationError,
    ProviderError,
    ProviderHTTPError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)


class AnthropicMessagesClient(Protocol):
    @property
    def messages(self) -> Any: ...

    def close(self) -> None: ...


class AnthropicLLM:
    """Translate one context into an Anthropic ``messages.create`` call."""

    def __init__(
        self,
        base_url: str | None,
        model: str,
        client: AnthropicMessagesClient,
        *,
        timeout_seconds: float = 60.0,
        max_output_tokens: int = 1536,
        reasoning_effort: str = "low",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._model = model
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self._clock = clock

    def complete(
        self, context: ModelContext, tools: Sequence[ToolDefinition]
    ) -> LLMResponse:
        try:
            response = self._client.messages.create(**self._request(context, tools))
        except ProviderError:
            raise
        except Exception as error:
            raise self._map_error(error) from error
        return self._parse_response(response)

    def complete_stream(
        self,
        context: ModelContext,
        tools: Sequence[ToolDefinition],
        on_text_delta: Callable[[str], None],
        cancelled: Callable[[], bool],
    ) -> LLMResponse:
        """Use the SDK stream helper when available, with a safe sync fallback."""

        started = self._clock()
        if cancelled():
            raise ProviderCancelledError("provider stream was cancelled")
        stream_factory = getattr(self._client.messages, "stream", None)
        if not callable(stream_factory):
            response = self.complete(context, tools)
            if response.content:
                on_text_delta(response.content)
            return response

        stream: Any = None
        try:
            stream = stream_factory(**self._request(context, tools))
            with stream as events:
                for text in getattr(events, "text_stream", ()):
                    if cancelled():
                        raise ProviderCancelledError("provider stream was cancelled")
                    if self._clock() - started >= self._timeout_seconds:
                        raise ProviderTimeoutError("provider stream exceeded its deadline")
                    if isinstance(text, str) and text:
                        on_text_delta(text)
                final = getattr(events, "get_final_message", lambda: None)()
            if final is None:
                raise ProviderResponseError("provider stream returned no final message")
            return self._parse_response(final)
        except ProviderError:
            raise
        except ProviderCancelledError:
            raise
        except Exception as error:
            raise self._map_error(error) from error
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as error:  # noqa: BLE001 - cleanup cannot mask result
                    del error

    def close(self) -> None:
        self._client.close()

    def _request(
        self, context: ModelContext, tools: Sequence[ToolDefinition]
    ) -> dict[str, Any]:
        system, messages = self._messages(context)
        request: dict[str, Any] = {
            "model": self._model_for(context),
            "messages": messages,
            "max_tokens": self._max_output_tokens_for(context),
        }
        if system:
            request["system"] = system
        if tools:
            request["tools"] = [self._tool_payload(tool) for tool in tools]
        thinking = self._thinking()
        if thinking is not None:
            request["thinking"] = thinking
        return request

    def _thinking(self) -> dict[str, Any] | None:
        if self._reasoning_effort.lower() in {"low", "off", "none", "disabled"}:
            return None
        # Anthropic requires the thinking budget to be below max_tokens.
        budget = min(max(1024, self._max_output_tokens // 2), self._max_output_tokens - 1)
        if budget < 1024:
            return None
        return {"type": "enabled", "budget_tokens": budget}

    def _model_for(self, context: ModelContext) -> str:
        override = context.metadata.get("model")
        if isinstance(override, str) and 0 < len(override.strip()) <= 256:
            return override.strip()
        return self._model

    def _max_output_tokens_for(self, context: ModelContext) -> int:
        override = context.metadata.get("max_output_tokens")
        if type(override) is int and override > 0:
            return min(self._max_output_tokens, override)
        return self._max_output_tokens

    @staticmethod
    def _messages(context: ModelContext) -> tuple[str, list[dict[str, str]]]:
        raw = OpenAICompatibleLLM._messages(context)
        systems = [item["content"] for item in raw if item["role"] == "system"]
        messages: list[dict[str, str]] = []
        for item in raw:
            role = item["role"]
            if role == "system":
                continue
            # Anthropic Messages accepts user/assistant turns.  Tool output is
            # represented as a user turn because dispatch remains harness-owned.
            messages.append(
                {"role": "assistant" if role == "assistant" else "user", "content": item["content"]}
            )
        if not messages:
            messages = [{"role": "user", "content": context.task}]
        return "\n\n".join(redact_text(item) for item in systems), messages

    @staticmethod
    def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": {
                key: value for key, value in tool.input_schema.items() if key != "$id"
            },
        }

    @classmethod
    def _parse_response(cls, response: Any) -> LLMResponse:
        blocks = cls._field(response, "content")
        if not isinstance(blocks, (list, tuple)):
            raise ProviderResponseError("provider response has no content blocks")
        text_parts: list[str] = []
        actions: list[ActionEnvelope] = []
        call_ids: list[str] = []
        for block in blocks:
            block_type = cls._field(block, "type")
            if block_type == "text":
                value = cls._field(block, "text")
                if isinstance(value, str):
                    text_parts.append(value)
                continue
            if block_type != "tool_use":
                continue
            name = cls._field(block, "name")
            arguments = cls._field(block, "input")
            call_id = cls._field(block, "id")
            if not isinstance(name, str) or not name:
                raise ProviderResponseError("provider tool call name is missing")
            if not isinstance(arguments, dict):
                raise ProviderResponseError("provider tool call input must be an object")
            if not isinstance(call_id, str) or not call_id:
                raise ProviderResponseError("provider tool call id is missing")
            action = (
                FinishAction.model_validate(arguments)
                if name == "finish"
                else ToolCall(name=name, arguments=arguments)
            )
            actions.append(ActionEnvelope(action=action))
            call_ids.append(call_id)
        result = LLMResponse(
            content="".join(text_parts),
            actions=tuple(actions),
            provider_metadata={"tool_call_ids": call_ids},
        )
        return OpenAICompatibleLLM._with_usage(result, cls._field(response, "usage"))

    @staticmethod
    def _field(value: Any, name: str) -> Any:
        if isinstance(value, dict):
            return value.get(name)
        return getattr(value, name, None)

    @staticmethod
    def _map_error(error: Exception) -> ProviderError:
        name = type(error).__name__.lower()
        if "timeout" in name:
            return ProviderTimeoutError("provider request timed out")
        if "auth" in name or "permission" in name:
            return ProviderAuthenticationError("provider rejected authentication")
        if "rate" in name or "overloaded" in name:
            return ProviderRateLimitError("provider rate limit exceeded")
        if "api" in name or "connection" in name or "http" in name:
            return ProviderHTTPError("provider request failed")
        return ProviderHTTPError("provider transport failed")


__all__ = ["AnthropicLLM", "AnthropicMessagesClient"]
