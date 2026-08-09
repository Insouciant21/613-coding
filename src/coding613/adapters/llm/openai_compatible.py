"""Single-call adapter for OpenAI-compatible chat-completions APIs."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from coding613.application.progress import ProviderCancelledError
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.ports.llm import LLMResponse, ModelContext, ToolDefinition


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

    def complete_stream(
        self,
        context: ModelContext,
        tools: Sequence[ToolDefinition],
        on_text_delta: Callable[[str], None],
        cancelled: Callable[[], bool],
    ) -> LLMResponse:
        payload = {
            "model": self._model,
            "messages": self._messages(context),
            "tools": [self._tool_payload(tool) for tool in tools],
            "stream": True,
        }
        try:
            stream = self._http_client.stream(
                "POST", f"{self._base_url}/chat/completions", json=payload
            )
            with stream as response:
                self._raise_for_status(response)
                content_parts: dict[int, list[str]] = {}
                tool_calls: dict[int, dict[str, str]] = {}
                saw_done = False
                for line in response.iter_lines():
                    if cancelled():
                        raise ProviderCancelledError("provider stream was cancelled")
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        saw_done = True
                        break
                    try:
                        chunk = json.loads(data)
                    except (TypeError, ValueError, json.JSONDecodeError) as error:
                        raise ProviderResponseError("provider returned malformed stream data") from error
                    self._accumulate_stream_chunk(chunk, content_parts, tool_calls, on_text_delta)
                if not saw_done:
                    raise ProviderResponseError("provider stream ended before [DONE]")
                if any(not value["id"] for value in tool_calls.values()):
                    raise ProviderResponseError("provider stream tool call has no id")
                message: dict[str, Any] = {
                    "content": "".join(part for index in sorted(content_parts) for part in content_parts[index]),
                    "tool_calls": [
                        {
                            "id": value["id"],
                            "type": "function",
                            "function": {
                                "name": value.get("name", ""),
                                "arguments": value.get("arguments", ""),
                            },
                        }
                        for index, value in sorted(tool_calls.items())
                    ],
                }
                return self._parse_message(message)
        except ProviderError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError("provider request timed out") from error
        except httpx.HTTPError as error:
            raise ProviderHTTPError("provider transport failed") from error

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError("provider rejected authentication")
        if response.status_code == 429:
            raise ProviderRateLimitError("provider rate limit exceeded")
        if response.is_error:
            raise ProviderHTTPError(f"provider returned HTTP {response.status_code}")

    def close(self) -> None:
        self._http_client.close()

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
        return cls._parse_message(message)

    @classmethod
    def _parse_message(cls, message: Any) -> LLMResponse:
        if not isinstance(message, dict):
            raise ProviderResponseError("provider message must be an object")

        actions: list[ActionEnvelope] = []
        call_ids: list[str] = []
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls is None:
            raw_tool_calls = []
        if not isinstance(raw_tool_calls, list):
            raise ProviderResponseError("provider tool calls must be a list")
        for item in raw_tool_calls:
            try:
                if not isinstance(item, dict):
                    raise TypeError("tool call must be an object")
                function = item["function"]
                if not isinstance(function, dict):
                    raise TypeError("tool call function must be an object")
                call_id = item["id"]
                name = function["name"]
                arguments_text = function["arguments"]
                if not isinstance(call_id, str) or not isinstance(name, str):
                    raise TypeError("tool call identity must be a string")
                if not isinstance(arguments_text, str):
                    raise TypeError("tool call arguments must be a string")
                arguments = json.loads(arguments_text)
                if not isinstance(arguments, dict):
                    raise TypeError("tool arguments must be an object")
                action = (
                    FinishAction.model_validate(arguments)
                    if name == "finish"
                    else ToolCall(name=name, arguments=arguments)
                )
                actions.append(ActionEnvelope(action=action))
                call_ids.append(call_id)
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

    @staticmethod
    def _accumulate_stream_chunk(
        chunk: Any,
        content_parts: dict[int, list[str]],
        tool_calls: dict[int, dict[str, str]],
        on_text_delta: Callable[[str], None],
    ) -> None:
        try:
            choices = chunk["choices"]
        except (KeyError, TypeError) as error:
            raise ProviderResponseError("provider stream chunk has no choices") from error
        if not isinstance(choices, list):
            raise ProviderResponseError("provider stream choices must be a list")
        for choice in choices:
            try:
                if not isinstance(choice, dict):
                    raise TypeError("choice must be an object")
                raw_index = choice.get("index", 0)
                if type(raw_index) is not int:
                    raise TypeError("choice index must be an integer")
                index = raw_index
                delta = choice["delta"]
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                raise ProviderResponseError("provider stream choice is invalid") from error
            if not isinstance(delta, dict):
                raise ProviderResponseError("provider stream delta must be an object")
            text = delta.get("content")
            if text is not None:
                if not isinstance(text, str):
                    raise ProviderResponseError("provider stream content must be a string")
                content_parts.setdefault(index, []).append(text)
                on_text_delta(text)
            raw_tool_calls = delta.get("tool_calls")
            if raw_tool_calls is None:
                continue
            if not isinstance(raw_tool_calls, list):
                raise ProviderResponseError("provider stream tool calls must be a list")
            for call in raw_tool_calls:
                try:
                    if not isinstance(call, dict):
                        raise TypeError("tool call must be an object")
                    raw_call_index = call["index"]
                    if type(raw_call_index) is not int:
                        raise TypeError("tool call index must be an integer")
                    call_index = raw_call_index
                    function = call.get("function")
                    if function is None:
                        function = {}
                    if not isinstance(function, dict):
                        raise TypeError("tool call function must be an object")
                    call_type = call.get("type")
                    if call_type is not None and call_type != "function":
                        raise TypeError("tool call type must be function")
                    call_id = call.get("id")
                    if call_id is not None and not isinstance(call_id, str):
                        raise TypeError("tool call id must be a string")
                    name = function.get("name")
                    if name is not None and not isinstance(name, str):
                        raise TypeError("tool call name must be a string")
                    arguments = function.get("arguments")
                    if arguments is not None and not isinstance(arguments, str):
                        raise TypeError("tool call arguments must be a string")
                except (AttributeError, KeyError, TypeError, ValueError) as error:
                    raise ProviderResponseError("provider stream tool call is invalid") from error
                target = tool_calls.setdefault(call_index, {"id": "", "name": "", "arguments": ""})
                if call_id:
                    target["id"] = call_id
                if name:
                    target["name"] += name
                if arguments:
                    target["arguments"] += arguments
