"""Shared conversation workflow consumed by the TUI and root CLI."""

from __future__ import annotations

from uuid import UUID

from coding613.application.interactive import (
    InteractiveSnapshot,
    InteractiveStore,
    transcript_for_runs,
)
from coding613.application.progress import CancellationToken
from coding613.application.run_service import RunRequest, RunService
from coding613.domain.conversation import PromptRequest
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import Run, RunSummary
from coding613.ports.progress import ProgressSink


class ConversationService:
    """Select sessions and delegate execution without owning loop policy."""

    def __init__(self, project_id: UUID, store: InteractiveStore, runs: RunService) -> None:
        self._project_id = project_id
        self._store = store
        self._runs = runs

    def create_session(self, title: str | None = None) -> InteractiveSession:
        session = InteractiveSession(project_id=self._project_id, title=title)
        self._store.create_interactive_session(session)
        return session

    def submit(self, request: PromptRequest) -> Run:
        if request.project_id != self._project_id:
            raise ValueError("prompt project does not match conversation project")
        session = self._select_session(request)
        return self._runs.create_run(
            RunRequest(
                task=request.text,
                project_id=session.project_id,
                session_id=session.id,
                permission_mode=request.permission_mode,
                options=request.options,
            )
        )

    def execute(
        self,
        run_id: UUID,
        sink: ProgressSink,
        cancellation: CancellationToken,
    ) -> RunSummary:
        return self._runs.resume(run_id, progress=sink, cancellation=cancellation)

    def snapshot(self, session_id: UUID) -> InteractiveSnapshot:
        session = self._require_session(session_id)
        runs = self._store.list_runs_for_session(session.id)
        active_run = next((run for run in reversed(runs) if not run.state.is_terminal), None)
        return InteractiveSnapshot(
            session=session,
            runs=tuple(runs),
            active_run=active_run,
            transcript=transcript_for_runs(self._store, runs),
        )

    def sessions(self) -> list[InteractiveSession]:
        return self._store.list_interactive_sessions(self._project_id)

    def _select_session(self, request: PromptRequest) -> InteractiveSession:
        if request.session_id is not None:
            return self._require_session(request.session_id)
        if request.continue_latest:
            sessions = self.sessions()
            if sessions:
                return sessions[0]
        return self.create_session()

    def _require_session(self, session_id: UUID) -> InteractiveSession:
        session = self._store.get_interactive_session(session_id)
        if session is None or session.project_id != self._project_id:
            raise KeyError(f"unknown interactive session: {session_id}")
        return session
