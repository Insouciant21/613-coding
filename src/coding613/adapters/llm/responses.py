"""OpenAI Responses API adapter for one harness-owned model call."""

from __future__ import annotations

import json
import shlex
import time
from collections.abc import Callable, Iterator, Sequence
from queue import Empty, Queue
from threading import Thread
from typing import Any, Protocol

from coding613.application.progress import ProviderCancelledError
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.ports.llm import LLMResponse, ModelContext, ToolDefinition

from .openai_compatible import (
    OpenAICompatibleLLM,
    ProviderError,
    ProviderHTTPError,
    ProviderResponseError,
    ProviderTimeoutError,
)

_CLIENT_SIDE_OUTPUT_TYPES = frozenset({"shell_call", "local_shell_call", "apply_patch_call"})


class ResponsesClient(Protocol):
    """Minimal SDK client surface required by the Responses adapter."""

    @property
    def responses(self) -> Any: ...

    def close(self) -> None: ...


class ResponsesLLM:
    """Translate one Responses API request into the project LLM port.

    The harness deliberately calls the SDK's low-level ``responses.create``
    method itself. It does not use the SDK's hosted agent loop or tool runner.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        client: ResponsesClient,
        *,
        timeout_seconds: float = 60.0,
        max_output_tokens: int = 1536,
        reasoning_effort: str = "low",
        clock: Callable[[], float] = time.monotonic,
        prompt_cache_explicit: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self._clock = clock
        self._prompt_cache_explicit = prompt_cache_explicit

    def complete(
        self, context: ModelContext, tools: Sequence[ToolDefinition]
    ) -> LLMResponse:
        try:
            response = self._client.responses.create(
                **self._request(context, tools),
            )
        except ProviderError:
            raise
        except Exception as error:
            raise OpenAICompatibleLLM._map_sdk_error(error) from error
        return self._parse_response(response)

    def complete_stream(
        self,
        context: ModelContext,
        tools: Sequence[ToolDefinition],
        on_text_delta: Callable[[str], None],
        cancelled: Callable[[], bool],
    ) -> LLMResponse:
        started_at = self._clock()
        stream: Any = None
        stream_closed = [False]
        cleanup_errors: list[Exception] = []
        primary_error: BaseException | None = None
        try:
            if cancelled():
                raise ProviderCancelledError("provider stream was cancelled")
            stream = self._client.responses.create(
                **self._request(context, tools),
                stream=True,
                stream_options={"include_usage": True},
            )
            text_parts: list[str] = []
            calls: dict[str, dict[str, Any]] = {}
            call_order: dict[str, int] = {}
            hosted_items: dict[str, dict[str, Any]] = {}
            hosted_order: dict[str, int] = {}
            usage: Any = None
            saw_event = False
            for event in self._stream_events(
                stream, started_at, cancelled, stream_closed, cleanup_errors
            ):
                saw_event = True
                event_type = self._field(event, "type")
                if event_type == "response.output_text.delta":
                    delta = self._field(event, "delta")
                    if not isinstance(delta, str):
                        raise ProviderResponseError("provider stream text delta must be a string")
                    text_parts.append(delta)
                    on_text_delta(delta)
                elif event_type in {
                    "response.output_item.added",
                    "response.output_item.done",
                }:
                    self._remember_hosted_item(
                        self._field(event, "item"), hosted_items, hosted_order
                    )
                    self._remember_function_item(
                        self._field(event, "item"), calls, call_order
                    )
                elif event_type == "response.function_call_arguments.delta":
                    item_id = self._field(event, "item_id")
                    if not isinstance(item_id, str) or not item_id:
                        raise ProviderResponseError(
                            "provider stream function call item id is missing"
                        )
                    delta = self._field(event, "delta")
                    if not isinstance(delta, str):
                        raise ProviderResponseError(
                            "provider stream function arguments must be a string"
                        )
                    target = calls.get(item_id)
                    if target is None:
                        target = calls[item_id] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                        call_order[item_id] = len(call_order)
                    target["arguments"] += delta
                elif event_type == "response.function_call_arguments.done":
                    item_id = self._field(event, "item_id")
                    if not isinstance(item_id, str) or not item_id:
                        raise ProviderResponseError(
                            "provider stream function call item id is missing"
                        )
                    target = calls.get(item_id)
                    if target is None:
                        target = calls[item_id] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                        call_order[item_id] = len(call_order)
                    arguments = self._field(event, "arguments")
                    name = self._field(event, "name")
                    if not isinstance(arguments, str):
                        raise ProviderResponseError(
                            "provider stream function call is incomplete"
                        )
                    # Some Responses-compatible providers (including
                    # DeepSeek) emit the function name on
                    # ``output_item.added`` and omit it from the later
                    # ``arguments.done`` event. Keep the earlier name when
                    # the event carries ``null``.
                    if name is not None:
                        if not isinstance(name, str):
                            raise ProviderResponseError(
                                "provider stream function call name must be a string"
                            )
                        target["name"] = name
                    target["arguments"] = arguments
                elif event_type == "response.completed":
                    completed = self._field(event, "response")
                    usage = self._field(completed, "usage")
                    for item in self._field(completed, "output") or ():
                        self._remember_hosted_item(item, hosted_items, hosted_order)
                elif event_type in {"response.failed", "error"}:
                    raise ProviderHTTPError("provider stream failed")
            self._check_stream_limits(started_at, cancelled)
            if not saw_event:
                raise ProviderResponseError("provider stream returned no events")
            output: list[dict[str, Any]] = []
            if text_parts:
                output.append(
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "".join(text_parts)}],
                    }
                )
            for key in sorted(call_order, key=call_order.__getitem__):
                value = calls[key]
                if not value["id"]:
                    raise ProviderResponseError(
                        "provider stream function call has no call id"
                    )
                if not value["name"] or not isinstance(value["arguments"], str):
                    raise ProviderResponseError("provider stream function call is incomplete")
                output.append(
                    {
                        "type": "function_call",
                        "call_id": value["id"],
                        "name": value["name"],
                        "arguments": value["arguments"],
                    }
                )
            for key in sorted(hosted_order, key=hosted_order.__getitem__):
                output.append(hosted_items[key])
            return self._parse_response(
                {"output": output, "usage": usage}
            )
        except (ProviderError, ProviderCancelledError) as error:
            primary_error = error
            raise
        except Exception as error:
            mapped = OpenAICompatibleLLM._map_sdk_error(error)
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

    def _stream_events(
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
                for event in stream:
                    events.put(("event", event))
            except Exception as error:  # noqa: BLE001 - preserve provider iterator errors
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
                if kind == "event":
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

    @classmethod
    def _remember_function_item(
        cls,
        item: Any,
        calls: dict[str, dict[str, Any]],
        call_order: dict[str, int],
    ) -> None:
        if cls._field(item, "type") != "function_call":
            return
        item_id = cls._field(item, "id")
        if not isinstance(item_id, str) or not item_id:
            raise ProviderResponseError("provider stream function call id is missing")
        target = calls.get(item_id)
        if target is None:
            target = calls[item_id] = {"id": "", "name": "", "arguments": ""}
            call_order[item_id] = len(call_order)
        call_id = cls._field(item, "call_id")
        name = cls._field(item, "name")
        arguments = cls._field(item, "arguments")
        if call_id is not None:
            if not isinstance(call_id, str):
                raise ProviderResponseError("provider stream function call id must be a string")
            target["id"] = call_id
        if name is not None:
            if not isinstance(name, str):
                raise ProviderResponseError("provider stream function call name must be a string")
            target["name"] = name
        if arguments is not None:
            if not isinstance(arguments, str):
                raise ProviderResponseError(
                    "provider stream function arguments must be a string"
                )
            target["arguments"] = arguments

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

    def _request(
        self, context: ModelContext, tools: Sequence[ToolDefinition]
    ) -> dict[str, Any]:
        items = self._input(context)
        request: dict[str, Any] = {
            "model": self._model_for(context),
            "input": items,
            "tools": [self._tool_payload(tool) for tool in tools],
            "max_output_tokens": self._max_output_tokens_for(context),
            "reasoning": {"effort": self._reasoning_effort},
            "store": False,
        }
        boundary = next(
            (i for i, message in enumerate(context.messages) if message.name == "run_ledger"),
            0,
        )
        if self._prompt_cache_explicit and boundary > 0:
            # The option is explicitly enabled per provider/model, never inferred from a name.
            item = items[boundary - 1]
            if item.get("role") in {"system", "user"} and isinstance(item.get("content"), str):
                item["content"] = [{
                    "type": "input_text", "text": item["content"],
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }]
                request["extra_body"] = {"prompt_cache_options": {"mode": "explicit"}}
        return request

    @staticmethod
    def _input(context: ModelContext) -> list[dict[str, Any]]:
        messages = [
            {"role": message.role, "content": message.content}
            for message in context.messages
        ] or [{"role": "user", "content": context.task}]
        continuation = context.metadata.get("responses_input_items")
        if not isinstance(continuation, list):
            return messages
        boundary = next(
            (i for i, message in enumerate(context.messages) if message.name == "run_ledger"),
            len(messages),
        )
        return (
            messages[:boundary]
            + [dict(item) for item in continuation if isinstance(item, dict)]
            + messages[boundary:]
        )

    @staticmethod
    def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
        if tool.transport == "responses_hosted":
            # Copy the payload so a provider/client cannot mutate the domain
            # definition retained by the loop or a later retry.
            if tool.provider_payload is None:
                raise ProviderResponseError(
                    f"hosted tool {tool.name} has no provider payload"
                )
            return dict(tool.provider_payload)
        parameters = {
            key: value for key, value in tool.input_schema.items() if key != "$id"
        }
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
        }

    @classmethod
    def _remember_hosted_item(
        cls,
        item: Any,
        items: dict[str, dict[str, Any]],
        order: dict[str, int],
    ) -> None:
        item_type = cls._field(item, "type")
        if item_type not in _CLIENT_SIDE_OUTPUT_TYPES:
            return
        item_id = cls._field(item, "id") or cls._field(item, "call_id")
        if not isinstance(item_id, str) or not item_id:
            return
        if item_id not in items:
            order[item_id] = len(order)
        value = cls._jsonable(item)
        if isinstance(value, dict):
            items[item_id] = value

    @classmethod
    def _client_action(cls, item_type: str, item: Any) -> ToolCall:
        call_id = cls._field(item, "call_id")
        if not isinstance(call_id, str) or not call_id:
            call_id = cls._field(item, "id")
        if not isinstance(call_id, str) or not call_id:
            raise ProviderResponseError(f"{item_type} has no call id")
        metadata = {
            "provider": "responses",
            "call_id": call_id,
            "item_type": item_type,
        }
        if item_type == "local_shell_call":
            action = cls._field(item, "action")
            command = cls._field(action, "command")
            if not isinstance(command, (list, tuple)) or not command:
                raise ProviderResponseError("local shell call command must be a non-empty argv")
            arguments: dict[str, Any] = {"argv": [str(value) for value in command]}
            timeout_ms = cls._field(action, "timeout_ms")
            if type(timeout_ms) is int and timeout_ms > 0:
                arguments["timeout_seconds"] = timeout_ms / 1000
            working_directory = cls._field(action, "working_directory")
            if isinstance(working_directory, str) and working_directory:
                arguments["cwd"] = working_directory
            return ToolCall(
                name="run_command",
                arguments=arguments,
                provider_metadata=metadata,
            )
        if item_type == "shell_call":
            action = cls._field(item, "action")
            commands = cls._field(action, "commands")
            if not isinstance(commands, (list, tuple)) or not commands:
                raise ProviderResponseError("shell call commands must be a non-empty array")
            normalized: list[dict[str, Any]] = []
            for command in commands:
                if isinstance(command, str):
                    try:
                        argv_values: Sequence[Any] = shlex.split(command)
                    except ValueError as error:
                        raise ProviderResponseError(
                            "shell call command has invalid quoting"
                        ) from error
                else:
                    argv_values = (
                        command if isinstance(command, (list, tuple)) else [command]
                    )
                if not argv_values or not all(
                    isinstance(value, str) and value for value in argv_values
                ):
                    raise ProviderResponseError("shell call command must be a non-empty argv")
                normalized.append({"argv": list(argv_values)})
            timeout_ms = cls._field(action, "timeout_ms")
            max_output_length = cls._field(action, "max_output_length")
            if type(timeout_ms) is int and timeout_ms > 0:
                for command in normalized:
                    command["timeout_seconds"] = timeout_ms / 1000
            if type(max_output_length) is int and max_output_length > 0:
                for command in normalized:
                    command["max_output_bytes"] = max_output_length
            return ToolCall(
                name="run_shell",
                arguments={"commands": normalized},
                provider_metadata=metadata,
            )
        if item_type == "apply_patch_call":
            operation = cls._jsonable(cls._field(item, "operation"))
            if not isinstance(operation, dict):
                raise ProviderResponseError("apply patch call operation must be an object")
            return ToolCall(
                name="apply_patch",
                arguments={"operation": operation},
                provider_metadata=metadata,
            )
        raise ProviderResponseError(f"unsupported client-side Responses item: {item_type}")

    @classmethod
    def _parse_response(cls, response: Any) -> LLMResponse:
        output = cls._field(response, "output")
        if not isinstance(output, (list, tuple)):
            raise ProviderResponseError("provider response has no output items")

        content_parts: list[str] = []
        actions: list[ActionEnvelope] = []
        call_ids: list[str] = []
        hosted_calls: list[dict[str, str]] = []
        output_items: list[dict[str, Any]] = []
        for item in output:
            item_type = cls._field(item, "type")
            if item_type == "message":
                content_parts.extend(cls._message_text(item))
                continue
            if item_type != "function_call":
                if isinstance(item_type, str) and item_type in _CLIENT_SIDE_OUTPUT_TYPES:
                    action = cls._client_action(item_type, item)
                    actions.append(ActionEnvelope(action=action))
                    call_ids.append(str(action.provider_metadata["call_id"]))
                    value = cls._jsonable(item)
                    if isinstance(value, dict):
                        output_items.append(value)
                if isinstance(item_type, str) and item_type.endswith("_call"):
                    hosted: dict[str, str] = {"type": item_type}
                    for field in ("id", "call_id", "status"):
                        value = cls._field(item, field)
                        if isinstance(value, str) and value:
                            hosted[field] = value
                    hosted_calls.append(hosted)
                continue
            try:
                call_id = cls._field(item, "call_id")
                name = cls._field(item, "name")
                arguments_text = cls._field(item, "arguments")
                if not isinstance(call_id, str) or not call_id:
                    raise TypeError("function call id must be a non-empty string")
                if not isinstance(name, str) or not name:
                    raise TypeError("function call name must be a non-empty string")
                if not isinstance(arguments_text, str):
                    raise TypeError("function call arguments must be a string")
                arguments = json.loads(arguments_text)
                if not isinstance(arguments, dict):
                    raise TypeError("function call arguments must be an object")
                function_action: FinishAction | ToolCall = (
                    FinishAction.model_validate(arguments)
                    if name == "finish"
                    else ToolCall(name=name, arguments=arguments)
                )
                actions.append(ActionEnvelope(action=function_action))
                call_ids.append(call_id)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise ProviderResponseError(
                    "provider returned an invalid function call"
                ) from error

        if not content_parts:
            output_text = cls._field(response, "output_text")
            if isinstance(output_text, str):
                content_parts.append(output_text)
        metadata: dict[str, Any] = {"tool_call_ids": call_ids}
        if hosted_calls:
            metadata["hosted_tool_calls"] = hosted_calls
        if output_items:
            metadata["output_items"] = output_items
        response_id = cls._field(response, "id")
        if isinstance(response_id, str) and response_id:
            metadata["response_id"] = response_id
        result = LLMResponse(
            content="".join(content_parts),
            actions=tuple(actions),
            provider_metadata=metadata,
        )
        return OpenAICompatibleLLM._with_usage(result, cls._field(response, "usage"))

    @classmethod
    def _message_text(cls, item: Any) -> list[str]:
        content = cls._field(item, "content")
        if isinstance(content, str):
            return [content]
        if not isinstance(content, (list, tuple)):
            return []
        parts: list[str] = []
        for part in content:
            if cls._field(part, "type") != "output_text":
                continue
            text = cls._field(part, "text")
            if not isinstance(text, str):
                raise ProviderResponseError("provider output text must be a string")
            parts.append(text)
        return parts

    @staticmethod
    def _field(value: Any, name: str) -> Any:
        if isinstance(value, dict):
            return value.get(name)
        return getattr(value, name, None)

    @classmethod
    def _jsonable(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): cls._jsonable(nested) for key, nested in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._jsonable(item) for item in value]
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            try:
                return cls._jsonable(dump(mode="json"))
            except TypeError:
                return cls._jsonable(dump())
        if hasattr(value, "__dict__"):
            return cls._jsonable(vars(value))
        return str(value)
