from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from coding613.application.events import (
    JsonOutputSerializer,
    StreamJsonSerializer,
    TextOutputSerializer,
)
from coding613.domain.models import (
    FeedbackKind,
    PermissionMode,
    ResourceUsage,
    RunState,
    StopReason,
)
from coding613.domain.session_events import EventType, RunEnvelope, SessionEvent


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


def test_verbose_text_includes_validation_feedback_approvals_and_usage() -> None:
    envelope = RunEnvelope(
        session_id=uuid4(),
        run_id=uuid4(),
        status=RunState.FAILED,
        stop_reason=StopReason.VALIDATION_FAILED,
        validation_evidence=(
            {"command": ["pytest"], "stdout": "1 failed", "stderr": ""},
        ),
        approvals=(uuid4(),),
        completion_blockers=(FeedbackKind.TEST_FAILURE,),
        resource_usage=ResourceUsage(model_calls=2, wall_time_seconds=1.5),
    )

    rendered = TextOutputSerializer().render(envelope, verbose=True)

    assert "validation_evidence=" in rendered
    assert "completion_blockers=test_failure" in rendered
    assert "approvals=1" in rendered
    assert "model_calls" in rendered


def test_run_serializers_report_bypass_mode() -> None:
    envelope = RunEnvelope(
        session_id=uuid4(),
        run_id=uuid4(),
        status=RunState.COMPLETED,
        stop_reason=StopReason.SUCCESS,
        permission_mode=PermissionMode.BYPASS,
        resource_usage=ResourceUsage(),
    )

    assert '"permission_mode":"bypass"' in JsonOutputSerializer().render(envelope)
    assert "permission_mode=bypass" in TextOutputSerializer().render(envelope)
