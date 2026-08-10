"""Event sink boundary for terminal adapters."""

from __future__ import annotations

from typing import Protocol

from coding613.domain.session_events import SessionEvent


class EventSink(Protocol):
    def publish(self, event: SessionEvent) -> None: ...
