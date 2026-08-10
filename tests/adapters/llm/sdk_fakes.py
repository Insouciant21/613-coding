from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = FakeFunction(name, arguments)


class FakeFunction:
    def __init__(self, name: str | None, arguments: str | None) -> None:
        self.name = name
        self.arguments = arguments


class FakeMessage:
    def __init__(self, content: str | None = "", tool_calls: Iterable[FakeToolCall] = ()) -> None:
        self.content = content
        self.tool_calls = list(tool_calls)


class FakeChoice:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message


class FakeCompletion:
    def __init__(self, message: FakeMessage) -> None:
        self.choices = [FakeChoice(message)]


class FakeToolDelta:
    def __init__(
        self,
        call_id: str | None,
        name: str | None,
        arguments: str | None,
        index: int = 0,
    ) -> None:
        self.index = index
        self.id = call_id
        self.type = "function"
        self.function = FakeFunction(name, arguments)


class FakeDelta:
    def __init__(self, content: str | None = None, tool_calls: Iterable[FakeToolDelta] = ()) -> None:
        self.content = content
        self.tool_calls = list(tool_calls)


class FakeChunkChoice:
    def __init__(self, delta: FakeDelta) -> None:
        self.delta = delta


class FakeChunk:
    def __init__(
        self,
        content: str | None = None,
        tool_call: FakeToolDelta | None = None,
        *,
        index: int = 0,
    ) -> None:
        self.choices = [
            FakeChunkChoice(
                FakeDelta(content=content, tool_calls=(() if tool_call is None else (tool_call,)))
            )
        ]
        self.index = index


class FakeStream:
    def __init__(
        self,
        chunks: Iterable[FakeChunk],
        *,
        iteration_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self._chunks = tuple(chunks)
        self._iteration_error = iteration_error
        self._close_error = close_error
        self.closed = False

    def __iter__(self) -> Iterator[FakeChunk]:
        yield from self._chunks
        if self._iteration_error is not None:
            raise self._iteration_error

    def close(self) -> None:
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


class FakeCompletions:
    def __init__(
        self,
        completion: FakeCompletion | None = None,
        stream: FakeStream | None = None,
        error: Exception | None = None,
    ) -> None:
        self.completion = completion or FakeCompletion(FakeMessage())
        self.stream = stream or FakeStream(())
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeCompletion | FakeStream:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.stream if kwargs.get("stream") is True else self.completion


class FakeChat:
    def __init__(
        self,
        completion: FakeCompletion | None = None,
        stream: FakeStream | None = None,
        error: Exception | None = None,
    ) -> None:
        self.completions = FakeCompletions(
            completion=completion, stream=stream, error=error
        )


class FakeSDKClient:
    def __init__(
        self,
        completion: FakeCompletion | None = None,
        stream: FakeStream | None = None,
        error: Exception | None = None,
    ) -> None:
        self.chat = FakeChat(completion=completion, stream=stream, error=error)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def empty_completion() -> FakeCompletion:
    return FakeCompletion(FakeMessage(content=""))
