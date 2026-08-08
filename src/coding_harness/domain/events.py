"""Versioned, redacted event records."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from .models_base import DomainModel

_SENSITIVE_KEY = re.compile(r"(?:key|token|secret|password|credential)", re.IGNORECASE)


def _redact(value: Any, key: str | None = None) -> Any:
    if key is not None and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): _redact(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class Event(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    event_type: str = Field(min_length=1, max_length=128)
    run_id: UUID
    payload: dict[str, Any]
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @classmethod
    def new(
        cls,
        event_type: str,
        run_id: UUID,
        payload: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> Event:
        return cls(
            event_type=event_type,
            run_id=run_id,
            payload=_redact(payload),
            timestamp=timestamp or datetime.now(UTC),
        )
