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
    PermissionDeniedError,
    RateLimitError,
)

from coding613.application.progress import ProviderCancelledError
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.redaction import redact_text
from coding613.ports.llm import (
    LLMResponse,
    ModelContext,
    RetryableProviderError,
    ToolDefinition,
)


class ProviderError(RuntimeError):
    """Base class for typed provider failures."""


class ProviderTimeoutError(ProviderError, RetryableProviderError):
    pass


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError, RetryableProviderError):
    pass


class ProviderHTTPError(ProviderError, RetryableProviderError):
    pass


class ProviderRequestError(ProviderError):
    """A non-retryable client request rejected by the provider (HTTP 4xx)."""


class ProviderResponseError(ProviderError, RetryableProviderError):
    pass


class SDKClient(Protocol):
    """Minimal official SDK client surface required by the adapter."""

    @property
    def chat(self) -> Any: ...

    @property
    def responses(self) -> Any: ...

    def close(self) -> None: ...


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        client: SDKClient,
        *,
        timeout_seconds: float = 60.0,
        max_output_tokens: int = 1536,
        reasoning_effort: str = "low",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/")
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
            request: dict[str, Any] = {
                "model": self._model_for(context),
                "messages": self._messages(context),
                "tools": [self._tool_payload(tool) for tool in tools],
                "max_tokens": self._max_output_tokens_for(context),
            }
            if self._reasoning_effort != "low":
                request["reasoning_effort"] = self._reasoning_effort
            completion = self._client.chat.completions.create(**request)
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
        cleanup_errors: list[Exception] = []
        stream_closed = [False]
        try:
            if cancelled():
                raise ProviderCancelledError("provider stream was cancelled")
            request = {
                "model": self._model_for(context),
                "messages": self._messages(context),
                "tools": [self._tool_payload(tool) for tool in tools],
                "max_tokens": self._max_output_tokens_for(context),
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if self._reasoning_effort != "low":
                request["reasoning_effort"] = self._reasoning_effort
            stream = self._client.chat.completions.create(**request)
            content_parts: dict[int, list[str]] = {}
            tool_calls: dict[int, dict[str, str]] = {}
            usage: Any = None
            saw_chunk = False
            for chunk in self._stream_chunks(
                stream, started_at, cancelled, stream_closed, cleanup_errors
            ):
                saw_chunk = True
                chunk_usage = self._field(chunk, "usage")
                if chunk_usage is not None:
                    usage = chunk_usage
                if self._field(chunk, "choices") is None:
                    continue
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
            return self._with_usage(self._parse_message(message), usage)
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
            if stream is not None and not stream_closed[0]:
                cleanup_error = self._close_stream(stream)
                stream_closed[0] = True
                if cleanup_error is not None:
                    cleanup_errors.append(cleanup_error)
            if cleanup_errors and primary_error is None:
                raise ProviderHTTPError("provider stream cleanup failed") from cleanup_errors[0]

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
        stream_closed: list[bool],
        cleanup_errors: list[Exception],
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
            cleanup_error = self._close_stream(stream)
            stream_closed[0] = True
            if cleanup_error is not None:
                cleanup_errors.append(cleanup_error)
            producer.join(timeout=0.1)
            if producer.is_alive():
                cleanup_errors.append(RuntimeError("provider stream reader did not stop"))

    @staticmethod
    def _close_stream(stream: Any) -> Exception | None:
        close = getattr(stream, "close", None)
        if not callable(close):
            return None
        try:
            close()
        except Exception as error:  # noqa: BLE001 - normalize SDK cleanup failures
            return error
        return None

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
    def _messages(context: ModelContext) -> list[dict[str, str]]:
        messages = [
            {"role": message.role, "content": message.content}
            for message in context.messages
        ] or [{"role": "user", "content": context.task}]
        prompt_messages: list[dict[str, str]] = []
        for key in ("system_prompt", "append_system_prompt"):
            value = context.metadata.get(key)
            if isinstance(value, str) and value.strip():
                safe = redact_text(value)
                if not any(
                    message["role"] == "system" and message["content"] == safe
                    for message in messages
                ):
                    prompt_messages.append({"role": "system", "content": safe})
        if prompt_messages:
            insert_at = next(
                (index for index, message in enumerate(messages) if message["role"] != "system"),
                len(messages),
            )
            messages[insert_at:insert_at] = prompt_messages
        return messages

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
        return cls._with_usage(
            cls._parse_message(cls._field(choices[0], "message")),
            cls._field(completion, "usage"),
        )

    @classmethod
    def _with_usage(cls, response: LLMResponse, usage: Any) -> LLMResponse:
        values = cls._usage_metadata(usage)
        if not values:
            return response
        metadata = dict(response.provider_metadata)
        metadata["usage"] = values
        return response.model_copy(update={"provider_metadata": metadata})

    @classmethod
    def _usage_metadata(cls, usage: Any) -> dict[str, int | float]:
        if usage is None:
            return {}
        values: dict[str, int | float] = {}
        for name in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        ):
            value = cls._field(usage, name)
            if type(value) in {int, float}:
                values[name] = value
        # Responses API names the same counters input/output tokens and nests
        # cache/reasoning details. Normalize them to the project vocabulary so
        # usage accounting is independent of the selected provider API.
        input_tokens = cls._field(usage, "input_tokens")
        output_tokens = cls._field(usage, "output_tokens")
        if type(input_tokens) in {int, float}:
            values.setdefault("prompt_tokens", input_tokens)
        if type(output_tokens) in {int, float}:
            values.setdefault("completion_tokens", output_tokens)
        # Anthropic Messages usage names cache counters explicitly.  Keep the
        # normalized vocabulary used by the loop and cost display.
        cache_read = cls._field(usage, "cache_read_input_tokens")
        cache_creation = cls._field(usage, "cache_creation_input_tokens")
        if type(cache_read) in {int, float}:
            values.setdefault("prompt_cache_hit_tokens", cache_read)
        if type(cache_creation) in {int, float}:
            values.setdefault("prompt_cache_miss_tokens", cache_creation)
        responses_input_details = cls._field(usage, "input_tokens_details")
        cached_tokens = cls._field(responses_input_details, "cached_tokens")
        if type(cached_tokens) in {int, float}:
            values.setdefault("prompt_cache_hit_tokens", cached_tokens)
            prompt_tokens = values.get("prompt_tokens")
            if type(prompt_tokens) in {int, float}:
                values.setdefault("prompt_cache_miss_tokens", prompt_tokens - cached_tokens)
        completion_details = cls._field(usage, "completion_tokens_details")
        reasoning_tokens = cls._field(completion_details, "reasoning_tokens")
        responses_output_details = cls._field(usage, "output_tokens_details")
        if type(reasoning_tokens) not in {int, float}:
            reasoning_tokens = cls._field(responses_output_details, "reasoning_tokens")
        if type(reasoning_tokens) in {int, float}:
            values["reasoning_tokens"] = reasoning_tokens
        return values

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
                    function = {}
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
        if isinstance(error, (AuthenticationError, PermissionDeniedError)):
            return ProviderAuthenticationError("provider rejected authentication")
        if isinstance(error, RateLimitError):
            return ProviderRateLimitError("provider rate limit exceeded")
        if isinstance(error, APITimeoutError):
            return ProviderTimeoutError("provider request timed out")
        if isinstance(error, APIStatusError):
            status_code = getattr(error.response, "status_code", None)
            if status_code in {401, 403}:
                return ProviderAuthenticationError("provider rejected authentication")
            if status_code == 429:
                return ProviderRateLimitError("provider rate limit exceeded")
            if isinstance(status_code, int) and 400 <= status_code < 500:
                return ProviderRequestError(
                    f"provider rejected request (HTTP {status_code})"
                )
        if isinstance(error, (APIConnectionError, APIStatusError, APIError, OpenAIError)):
            return ProviderHTTPError("provider request failed")
        return ProviderHTTPError("provider transport failed")
