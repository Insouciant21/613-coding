"""Persistence ports for authoritative harness state."""

from typing import Protocol
from uuid import UUID

from coding_harness.domain.events import Event
from coding_harness.domain.models import (
    ApprovalRequest,
    ApprovalStatus,
    IterationRecord,
    LoopSession,
)


class EventStore(Protocol):
    def append(self, event: Event) -> None: ...

    def list_for_run(self, run_id: UUID) -> list[Event]: ...


class ApprovalStore(Protocol):
    def save_approval(self, request: ApprovalRequest) -> None: ...

    def get_approval(self, request_id: UUID) -> ApprovalRequest | None: ...

    def list_approvals(self, run_id: UUID) -> list[ApprovalRequest]: ...

    def compare_and_set_approval(
        self,
        request_id: UUID,
        expected_status: ApprovalStatus,
        replacement: ApprovalRequest,
    ) -> bool: ...


class LoopSessionStore(Protocol):
    def save_loop_session(self, session: LoopSession) -> None: ...

    def get_loop_session(self, run_id: UUID) -> LoopSession | None: ...

    def save_iteration_and_session(
        self,
        iteration: IterationRecord,
        session: LoopSession,
        approval_update: ApprovalRequest | None = None,
    ) -> None: ...
