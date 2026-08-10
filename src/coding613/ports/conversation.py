"""Application port shared by terminal adapters."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from coding613.application.progress import CancellationToken
from coding613.domain.conversation import PromptRequest
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import Run, RunSummary
from coding613.ports.progress import ProgressSink


class ConversationServicePort(Protocol):
    def create_session(self, title: str | None = None) -> InteractiveSession: ...

    def submit(self, request: PromptRequest) -> Run: ...

    def execute(
        self,
        run_id: UUID,
        sink: ProgressSink,
        cancellation: CancellationToken,
    ) -> RunSummary: ...

    def snapshot(self, session_id: UUID) -> Any: ...

    def sessions(self) -> list[InteractiveSession]: ...
