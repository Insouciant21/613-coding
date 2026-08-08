"""Single-call adapter for OpenAI-compatible chat-completions APIs."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx

from coding_harness.domain.actions import ActionEnvelope, ToolCall
from coding_harness.ports.llm import LLMResponse, ModelContext, ToolDefinition


class ProviderError(RuntimeError):
    """Base class for typed provider failures."""


class ProviderTimeoutError(ProviderError):
    pass


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderHTTPError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, model: str, http_client: httpx.Client) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._http_client = http_client

    def complete(
        self, context: ModelContext, tools: Sequence[ToolDefinition]
    ) -> LLMResponse:
        payload = {
            "model": self._model,
            "messages": self._messages(context),
            "tools": [self._tool_payload(tool) for tool in tools],
        }
        try:
            response = self._http_client.post(
                f"{self._base_url}/chat/completions", json=payload
            )
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError("provider request timed out") from error
        except httpx.HTTPError as error:
            raise ProviderHTTPError("provider transport failed") from error

        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError("provider rejected authentication")
        if response.status_code == 429:
            raise ProviderRateLimitError("provider rate limit exceeded")
        if response.is_error:
            raise ProviderHTTPError(f"provider returned HTTP {response.status_code}")
        return self._parse_response(response)

    @staticmethod
    def _messages(context: ModelContext) -> list[dict[str, str]]:
        if context.messages:
            return [
                {"role": message.role, "content": message.content}
                for message in context.messages
            ]
        return [{"role": "user", "content": context.task}]

    @staticmethod
    def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    @classmethod
    def _parse_response(cls, response: httpx.Response) -> LLMResponse:
        try:
            body = response.json()
            choices = body["choices"]
            message = choices[0]["message"]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderResponseError("provider response has no valid choice") from error
        if not isinstance(message, dict):
            raise ProviderResponseError("provider message must be an object")

        actions: list[ActionEnvelope] = []
        call_ids: list[str] = []
        for item in message.get("tool_calls") or []:
            try:
                function = item["function"]
                arguments = json.loads(function["arguments"])
                if not isinstance(arguments, dict):
                    raise TypeError("tool arguments must be an object")
                actions.append(
                    ActionEnvelope(
                        action=ToolCall(name=function["name"], arguments=arguments)
                    )
                )
                call_ids.append(str(item["id"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ProviderResponseError("provider returned an invalid tool call") from error

        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ProviderResponseError("provider content must be a string or null")
        return LLMResponse(
            content=content,
            actions=tuple(actions),
            provider_metadata={"tool_call_ids": call_ids},
        )
