from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from coding613.application.events import StreamJsonSerializer
from coding613.domain.session_events import EventType, SessionEvent


def test_stream_json_is_one_versioned_redacted_line_per_event() -> None:
    event = SessionEvent(
        session_id=uuid4(),
        run_id=uuid4(),
        type=EventType.TOOL_FINISHED,
        timestamp=datetime.now(UTC),
        data={"output": "password=secret-value"},
    )

    rendered = StreamJsonSerializer().render_event(event)
    value = json.loads(rendered)

    assert value["schema_version"] == 1
    assert value["sequence"] == 1
    assert rendered.endswith("\n")
    assert "secret-value" not in rendered
