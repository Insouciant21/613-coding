"""Ephemeral progress and cancellation contracts."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from coding613.domain.models_base import DomainModel


class ProgressKind(StrEnum):
    STATE = "state"
    TEXT_DELTA = "text_delta"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    VALIDATION_STARTED = "validation_started"
    VALIDATION_FINISHED = "validation_finished"
    ERROR = "error"


class _FrozenDict(dict[str, Any]):
    """Dict-compatible recursively frozen payload container for progress values."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise TypeError("progress payload is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable  # type: ignore[assignment]
    clear = _immutable
    pop = _immutable
    popitem = _immutable  # type: ignore[assignment]
    setdefault = _immutable
    update = _immutable


def _freeze_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze_payload(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_payload(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_payload(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_payload(item) for item in value)
    return value


class RunProgress(DomainModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True, frozen=True)

    run_id: UUID
    kind: ProgressKind
    text: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def freeze_nested_payload(self) -> RunProgress:
        object.__setattr__(self, "payload", _freeze_payload(self.payload))
        return self


class ProgressSink(Protocol):
    def publish(self, update: RunProgress) -> None: ...


class NullProgressSink:
    def publish(self, update: RunProgress) -> None:
        del update
