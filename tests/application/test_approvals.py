from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from coding_harness.application.approvals import (
    ApprovalDecision,
    ApprovalService,
    StaleApprovalError,
)
from coding_harness.domain.actions import ToolCall
from coding_harness.domain.models import ApprovalRequest, ApprovalStatus
from coding_harness.ports.policy import PolicyDecision, PolicyEffect


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


class ApprovalRecords:
    def __init__(self) -> None:
        self.requests: dict[UUID, ApprovalRequest] = {}

    def save_approval(self, request: ApprovalRequest) -> None:
        self.requests[request.id] = request

    def get_approval(self, request_id: UUID) -> ApprovalRequest | None:
        return self.requests.get(request_id)

    def list_approvals(self, run_id: UUID) -> list[ApprovalRequest]:
        return [request for request in self.requests.values() if request.run_id == run_id]


def ask(call: ToolCall) -> PolicyDecision:
    return PolicyDecision(
        effect=PolicyEffect.ASK,
        rule_id="mode.strict.write",
        reason="approval required",
        action=call,
    )


def test_approval_is_exact_and_consumed_once() -> None:
    clock = Clock()
    service = ApprovalService(run_id=uuid4(), store=ApprovalRecords(), clock=clock)
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
    service = ApprovalService(
        run_id=uuid4(),
        store=ApprovalRecords(),
        clock=clock,
        ttl=timedelta(seconds=5),
    )
    request = service.request(
        ask(ToolCall(name="network_request", arguments={"url": "https://example.invalid"}))
    )
    clock.now += timedelta(seconds=6)
    with pytest.raises(StaleApprovalError):
        service.resolve(request.id, ApprovalDecision.APPROVE)
    assert service.get_request(request.id).status is ApprovalStatus.EXPIRED


def test_rejection_never_authorizes_action() -> None:
    service = ApprovalService(run_id=uuid4(), store=ApprovalRecords())
    call = ToolCall(name="git_commit", arguments={"message": "msg"})
    request = service.request(ask(call))
    service.resolve(request.id, ApprovalDecision.REJECT)
    assert not service.consume(call)
