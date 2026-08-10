"""Application port shared by terminal adapters."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from coding613.application.progress import CancellationToken
from coding613.domain.conversation import (
    ContextSummary,
    DiagnosticReport,
    PromptRequest,
)
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import Run, RunSummary
from coding613.ports.progress import ProgressSink


class ConversationServicePort(Protocol):
    def create_session(self, title: str | None = None) -> InteractiveSession: ...

    def submit(self, request: PromptRequest) -> Run: ...

    def continue_latest(self, project_id: UUID, message: str | None = None) -> Run: ...

    def compact(self, session_id: UUID) -> ContextSummary: ...

    def diagnostics(self, project_id: UUID) -> DiagnosticReport: ...

    def execute(
        self,
        run_id: UUID,
        sink: ProgressSink,
        cancellation: CancellationToken,
    ) -> RunSummary: ...

    def snapshot(self, session_id: UUID) -> Any: ...

    def sessions(self) -> list[InteractiveSession]: ...
