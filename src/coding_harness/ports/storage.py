"""Persistence ports for authoritative harness state."""

from typing import Protocol
from uuid import UUID

from coding_harness.domain.events import Event


class EventStore(Protocol):
    def append(self, event: Event) -> None: ...

    def list_for_run(self, run_id: UUID) -> list[Event]: ...
