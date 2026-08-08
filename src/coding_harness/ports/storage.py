"""Persistence ports for authoritative harness state."""

from typing import Protocol
from uuid import UUID

from coding_harness.domain.events import Event
from coding_harness.domain.models import ApprovalRequest, LoopSession


class EventStore(Protocol):
    def append(self, event: Event) -> None: ...

    def list_for_run(self, run_id: UUID) -> list[Event]: ...


class ApprovalStore(Protocol):
    def save_approval(self, request: ApprovalRequest) -> None: ...

    def get_approval(self, request_id: UUID) -> ApprovalRequest | None: ...

    def list_approvals(self, run_id: UUID) -> list[ApprovalRequest]: ...


class LoopSessionStore(Protocol):
    def save_loop_session(self, session: LoopSession) -> None: ...

    def get_loop_session(self, run_id: UUID) -> LoopSession | None: ...
