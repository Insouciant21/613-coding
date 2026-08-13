from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.models import (
    ApprovalRequest,
    ApprovalStatus,
    Feedback,
    FeedbackKind,
    IterationRecord,
    PermissionMode,
    RunState,
    StopReason,
)


def test_enums_expose_governance_and_feedback_values() -> None:
    assert {mode.value for mode in PermissionMode} == {
        "strict",
        "balanced",
        "autonomous",
        "bypass",
    }
    assert {state.value for state in RunState} == {
        "running",
        "waiting_model",
        "waiting_approval",
        "paused",
        "completed",
        "failed",
        "cancelled",
    }
    assert RunState.COMPLETED.is_terminal
    assert not RunState.RUNNING.is_terminal
    assert {kind.value for kind in FeedbackKind} == {
        "pass",
        "test_failure",
        "lint_failure",
        "type_failure",
        "environment_failure",
        "timeout",
        "resource_exhausted",
        "policy_blocked",
        "tool_error",
        "invalid_action",
        "merge_conflict",
        "no_progress",
    }
    assert {reason.value for reason in StopReason} == {
        "success",
        "budget_exhausted",
        "user_requested",
        "cancelled",
        "timeout",
        "approval_required",
        "approval_rejected",
        "validation_failed",
        "no_progress",
        "invalid_action",
        "provider_error",
        "dependency_error",
    }
    assert {status.value for status in ApprovalStatus} == {
        "pending",
        "approved",
        "rejected",
        "expired",
        "executing",
        "consumed",
    }


def test_tool_call_is_strict_and_action_is_discriminated() -> None:
    call = ToolCall(name="read_file", arguments={"path": "README.md"})
    envelope = ActionEnvelope(action=call)
    assert envelope.action.kind == "tool"
    with pytest.raises(ValidationError):
        ToolCall(name="read_file", arguments=["README.md"])  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ToolCall(name="", arguments={})
    assert ActionEnvelope(action=FinishAction(summary="done")).action.kind == "finish"


def test_iteration_requires_reason_for_terminal_state() -> None:
    run_id = uuid4()
    base = {
        "run_id": run_id,
        "iteration": 1,
        "state_before": RunState.RUNNING,
        "state_after": RunState.COMPLETED,
        "timestamp": datetime.now(UTC),
    }
    with pytest.raises(ValidationError):
        IterationRecord(**base)
    record = IterationRecord(**base, stop_reason=StopReason.SUCCESS)
    assert record.state_after.is_terminal


def test_approval_round_trip_preserves_action() -> None:
    request = ApprovalRequest(
        action=ToolCall(name="write_file", arguments={"path": "a.py", "content": "pass"}),
        reason="repository write",
    )
    restored = ApprovalRequest.model_validate_json(request.model_dump_json())
    assert restored.action.name == "write_file"


def test_feedback_requires_nonempty_message() -> None:
    with pytest.raises(ValidationError):
        Feedback(kind=FeedbackKind.TEST_FAILURE, message="")
