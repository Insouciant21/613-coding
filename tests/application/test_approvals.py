from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from coding_harness.application.approvals import (
    ApprovalDecision,
    ApprovalService,
    StaleApprovalError,
)
from coding_harness.domain.actions import ToolCall
from coding_harness.ports.policy import PolicyDecision, PolicyEffect


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


def ask(call: ToolCall) -> PolicyDecision:
    return PolicyDecision(
        effect=PolicyEffect.ASK,
        rule_id="mode.strict.write",
        reason="approval required",
        action=call,
    )


def test_approval_is_exact_and_consumed_once() -> None:
    clock = Clock()
    service = ApprovalService(run_id=uuid4(), clock=clock)
    call = ToolCall(name="edit_file", arguments={"path": "a.py", "content": "pass"})
    request = service.request(ask(call))
    assert request.run_id == service.run_id
    resolution = service.resolve(request.id, ApprovalDecision.APPROVE)
    assert resolution.decision is ApprovalDecision.APPROVE
    assert not service.consume(
        ToolCall(name="edit_file", arguments={"path": "b.py", "content": "pass"})
    )
    assert service.consume(call)
    assert not service.consume(call)


def test_stale_approval_cannot_be_resolved() -> None:
    clock = Clock()
    service = ApprovalService(run_id=uuid4(), clock=clock, ttl=timedelta(seconds=5))
    request = service.request(
        ask(ToolCall(name="network_request", arguments={"url": "https://example.invalid"}))
    )
    clock.now += timedelta(seconds=6)
    with pytest.raises(StaleApprovalError):
        service.resolve(request.id, ApprovalDecision.APPROVE)


def test_rejection_never_authorizes_action() -> None:
    service = ApprovalService(run_id=uuid4())
    call = ToolCall(name="git_commit", arguments={"message": "msg"})
    request = service.request(ask(call))
    service.resolve(request.id, ApprovalDecision.REJECT)
    assert not service.consume(call)
