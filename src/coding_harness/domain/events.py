"""Versioned, redacted event records."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from .models_base import DomainModel

_SENSITIVE_PARTS = {"credential", "password", "secret", "token"}
_KEY_QUALIFIERS = {"api", "encryption", "private", "secret", "signing"}


def _is_sensitive_key(key: str) -> bool:
    snake_case = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
    parts = set(filter(None, re.split(r"[-_\s]+", snake_case)))
    return bool(parts & _SENSITIVE_PARTS) or ("key" in parts and bool(parts & _KEY_QUALIFIERS))


def redact_payload(value: Any, key: str | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): redact_payload(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_payload(item) for item in value]
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
        timestamp: datetime,
    ) -> Event:
        return cls(
            event_type=event_type,
            run_id=run_id,
            payload=redact_payload(payload),
            timestamp=timestamp,
        )
