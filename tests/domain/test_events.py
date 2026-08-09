from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from coding613.domain.events import Event


def test_event_new_sets_version_uuid_and_redacts_sensitive_payload() -> None:
    event = Event.new(
        "tool.completed",
        uuid4(),
        {
            "api_key": "secret-value",
            "nested": {"password": "pw", "ok": "value", "monkey": "banana"},
        },
        datetime.now(UTC),
    )
    assert event.version == 1
    assert event.id
    assert event.payload["api_key"] == "[REDACTED]"
    assert event.payload["nested"]["password"] == "[REDACTED]"
    assert event.payload["nested"]["ok"] == "value"
    assert event.payload["nested"]["monkey"] == "banana"


def test_event_rejects_naive_timestamp_and_round_trips_json() -> None:
    with pytest.raises(ValidationError):
        Event.new("run.started", uuid4(), {}, datetime.now(UTC).replace(tzinfo=None))
    event = Event.new("run.started", uuid4(), {}, datetime.now(UTC))
    restored = Event.model_validate_json(event.model_dump_json())
    assert restored == event
