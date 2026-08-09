"""Persistence ports for authoritative harness state."""

from typing import Protocol
from uuid import UUID

from coding613.domain.events import Event
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import (
    ApprovalRequest,
    ApprovalStatus,
    IterationRecord,
    LoopSession,
    Run,
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


class InteractiveSessionStore(Protocol):
    def create_interactive_session(self, session: InteractiveSession) -> None: ...

    def get_interactive_session(self, session_id: UUID) -> InteractiveSession | None: ...

    def list_interactive_sessions(
        self, project_id: UUID, limit: int = 50
    ) -> list[InteractiveSession]: ...

    def list_runs_for_session(self, session_id: UUID) -> list[Run]: ...
