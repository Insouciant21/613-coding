"""OpenAI SDK adapter for OpenAI-compatible chat-completions providers."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Sequence
from queue import Empty, Queue
from threading import Thread
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)

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


class SDKClient(Protocol):
    """Minimal official SDK client surface required by the adapter."""

    @property
    def chat(self) -> Any: ...

    def close(self) -> None: ...


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        client: SDKClient,
        *,
        timeout_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._clock = clock

    def complete(
        self, context: ModelContext, tools: Sequence[ToolDefinition]
    ) -> LLMResponse:
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=self._messages(context),
                tools=[self._tool_payload(tool) for tool in tools],
            )
        except ProviderError:
            raise
        except Exception as error:
            raise self._map_sdk_error(error) from error
        return self._parse_completion(completion)

    def complete_stream(
        self,
        context: ModelContext,
        tools: Sequence[ToolDefinition],
        on_text_delta: Callable[[str], None],
        cancelled: Callable[[], bool],
    ) -> LLMResponse:
        started_at = self._clock()
        stream: Any = None
        primary_error: BaseException | None = None
        try:
            if cancelled():
                raise ProviderCancelledError("provider stream was cancelled")
            stream = self._client.chat.completions.create(
                model=self._model,
                messages=self._messages(context),
                tools=[self._tool_payload(tool) for tool in tools],
                stream=True,
            )
            content_parts: dict[int, list[str]] = {}
            tool_calls: dict[int, dict[str, str]] = {}
            saw_chunk = False
            for chunk in self._stream_chunks(stream, started_at, cancelled):
                saw_chunk = True
                self._accumulate_stream_chunk(chunk, content_parts, tool_calls, on_text_delta)
            self._check_stream_limits(started_at, cancelled)
            if not saw_chunk:
                raise ProviderResponseError("provider stream returned no chunks")
            if any(not value["id"] for value in tool_calls.values()):
                raise ProviderResponseError("provider stream tool call has no id")
            message: dict[str, Any] = {
                "content": "".join(
                    part for index in sorted(content_parts) for part in content_parts[index]
                ),
                "tool_calls": [
                    {
                        "id": value["id"],
                        "type": "function",
                        "function": {
                            "name": value["name"],
                            "arguments": value["arguments"],
                        },
                    }
                    for index, value in sorted(tool_calls.items())
                ],
            }
            return self._parse_message(message)
        except ProviderError as error:
            primary_error = error
            raise
        except ProviderCancelledError as error:
            primary_error = error
            raise
        except Exception as error:
            mapped = self._map_sdk_error(error)
            primary_error = mapped
            raise mapped from error
        finally:
            if stream is not None:
                try:
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                except Exception as cleanup_error:
                    if primary_error is None:
                        raise ProviderHTTPError("provider stream cleanup failed") from cleanup_error

    def close(self) -> None:
        self._client.close()

    def _check_stream_limits(
        self, started_at: float, cancelled: Callable[[], bool]
    ) -> None:
        if self._clock() - started_at >= self._timeout_seconds:
            raise ProviderTimeoutError("provider stream exceeded its deadline")
        if cancelled():
            raise ProviderCancelledError("provider stream was cancelled")

    def _stream_chunks(
        self,
        stream: Any,
        started_at: float,
        cancelled: Callable[[], bool],
    ) -> Iterator[Any]:
        events: Queue[tuple[str, Any]] = Queue()

        def produce() -> None:
            try:
                for chunk in stream:
                    events.put(("chunk", chunk))
            except Exception as error:  # noqa: BLE001 - preserve any provider iterator error
                events.put(("error", error))
            finally:
                events.put(("end", None))

        producer = Thread(target=produce, daemon=True)
        producer.start()
        try:
            while True:
                if cancelled():
                    raise ProviderCancelledError("provider stream was cancelled")
                remaining = self._timeout_seconds - (self._clock() - started_at)
                if remaining <= 0:
                    raise ProviderTimeoutError("provider stream exceeded its deadline")
                try:
                    kind, value = events.get(timeout=remaining)
                except Empty as error:
                    raise ProviderTimeoutError("provider stream exceeded its deadline") from error
                if kind == "chunk":
                    yield value
                    continue
                if kind == "error":
                    if isinstance(value, BaseException):
                        raise value
                    raise ProviderHTTPError("provider stream failed")
                return
        finally:
            producer.join(timeout=0.1)

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
        parameters = {
            key: value for key, value in tool.input_schema.items() if key != "$id"
        }
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": parameters,
            },
        }

    @classmethod
    def _parse_completion(cls, completion: Any) -> LLMResponse:
        choices = cls._field(completion, "choices")
        if not isinstance(choices, (list, tuple)) or not choices:
            raise ProviderResponseError("provider response has no valid choice")
        return cls._parse_message(cls._field(choices[0], "message"))

    @classmethod
    def _parse_message(cls, message: Any) -> LLMResponse:
        if not cls._is_object(message):
            raise ProviderResponseError("provider message must be an object")

        actions: list[ActionEnvelope] = []
        call_ids: list[str] = []
        raw_tool_calls = cls._field(message, "tool_calls")
        if raw_tool_calls is None:
            raw_tool_calls = []
        if not isinstance(raw_tool_calls, (list, tuple)):
            raise ProviderResponseError("provider tool calls must be a list")
        for item in raw_tool_calls:
            try:
                if not cls._is_object(item):
                    raise TypeError("tool call must be an object")
                function = cls._field(item, "function")
                if not cls._is_object(function):
                    raise TypeError("tool call function must be an object")
                call_id = cls._field(item, "id")
                name = cls._field(function, "name")
                arguments_text = cls._field(function, "arguments")
                if not isinstance(call_id, str) or not call_id:
                    raise TypeError("tool call id must be a non-empty string")
                if not isinstance(name, str) or not name:
                    raise TypeError("tool call name must be a non-empty string")
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

        content = cls._field(message, "content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ProviderResponseError("provider content must be a string or null")
        return LLMResponse(
            content=content,
            actions=tuple(actions),
            provider_metadata={"tool_call_ids": call_ids},
        )

    @classmethod
    def _accumulate_stream_chunk(
        cls,
        chunk: Any,
        content_parts: dict[int, list[str]],
        tool_calls: dict[int, dict[str, str]],
        on_text_delta: Callable[[str], None],
    ) -> None:
        choices = cls._field(chunk, "choices")
        if not isinstance(choices, (list, tuple)):
            raise ProviderResponseError("provider stream choices must be a list")
        for choice in choices:
            delta = cls._field(choice, "delta")
            if not cls._is_object(delta):
                raise ProviderResponseError("provider stream delta must be an object")
            text = cls._field(delta, "content")
            if text is not None:
                if not isinstance(text, str):
                    raise ProviderResponseError("provider stream content must be a string")
                index = cls._field(choice, "index")
                if index is None:
                    index = 0
                if type(index) is not int:
                    raise ProviderResponseError("provider stream choice index must be an integer")
                content_parts.setdefault(index, []).append(text)
                on_text_delta(text)
            raw_tool_calls = cls._field(delta, "tool_calls")
            if raw_tool_calls is None:
                continue
            if not isinstance(raw_tool_calls, (list, tuple)):
                raise ProviderResponseError("provider stream tool calls must be a list")
            for call in raw_tool_calls:
                if not cls._is_object(call):
                    raise ProviderResponseError("provider stream tool call must be an object")
                call_index = cls._field(call, "index")
                if type(call_index) is not int:
                    raise ProviderResponseError("provider stream tool call index must be an integer")
                call_type = cls._field(call, "type")
                if call_type is not None and call_type != "function":
                    raise ProviderResponseError("provider stream tool call type must be function")
                function = cls._field(call, "function")
                if function is None:
                    function = object()
                if not cls._is_object(function):
                    raise ProviderResponseError("provider stream tool call function must be an object")
                call_id = cls._field(call, "id")
                name = cls._field(function, "name")
                arguments = cls._field(function, "arguments")
                if call_id is not None and not isinstance(call_id, str):
                    raise ProviderResponseError("provider stream tool call id must be a string")
                if name is not None and not isinstance(name, str):
                    raise ProviderResponseError("provider stream tool call name must be a string")
                if arguments is not None and not isinstance(arguments, str):
                    raise ProviderResponseError("provider stream tool call arguments must be a string")
                target = tool_calls.setdefault(
                    call_index, {"id": "", "name": "", "arguments": ""}
                )
                if call_id:
                    target["id"] = call_id
                if name:
                    target["name"] += name
                if arguments:
                    target["arguments"] += arguments

    @staticmethod
    def _is_object(value: Any) -> bool:
        return isinstance(value, dict) or hasattr(value, "__dict__")

    @staticmethod
    def _field(value: Any, name: str) -> Any:
        if isinstance(value, dict):
            return value.get(name)
        return getattr(value, name, None)

    @staticmethod
    def _map_sdk_error(error: Exception) -> ProviderError:
        if isinstance(error, AuthenticationError):
            return ProviderAuthenticationError("provider rejected authentication")
        if isinstance(error, RateLimitError):
            return ProviderRateLimitError("provider rate limit exceeded")
        if isinstance(error, APITimeoutError):
            return ProviderTimeoutError("provider request timed out")
        if isinstance(error, (APIConnectionError, APIStatusError, APIError, OpenAIError)):
            return ProviderHTTPError("provider request failed")
        return ProviderHTTPError("provider transport failed")
