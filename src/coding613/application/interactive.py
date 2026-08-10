"""Persisted interactive-session workflows shared by the TUI and CLI."""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from coding613.application.progress import CancellationToken
from coding613.application.run_service import RunRequest, RunService
from coding613.domain.conversation import PromptRequest, RunOptions
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import IterationRecord, PermissionMode, Run, RunSummary
from coding613.domain.models_base import DomainModel
from coding613.domain.redaction import redact_text
from coding613.ports.progress import ProgressSink


class InteractiveStore(Protocol):
    def create_interactive_session(self, session: InteractiveSession) -> None: ...

    def get_interactive_session(self, session_id: UUID) -> InteractiveSession | None: ...

    def list_runs_for_session(self, session_id: UUID) -> list[Run]: ...

    def list_interactive_sessions(
        self, project_id: UUID, limit: int = 50
    ) -> list[InteractiveSession]: ...

    def list_iterations(self, run_id: UUID) -> list[IterationRecord]: ...


class TranscriptEntry(DomainModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1)
    run_id: UUID


class InteractiveSnapshot(DomainModel):
    session: InteractiveSession
    runs: tuple[Run, ...]
    active_run: Run | None = None
    transcript: tuple[TranscriptEntry, ...]


class ConversationWorkflow(Protocol):
    def create_session(self, title: str | None = None) -> InteractiveSession: ...

    def submit(self, request: PromptRequest) -> Run: ...

    def execute(
        self,
        run_id: UUID,
        sink: ProgressSink,
        cancellation: CancellationToken,
    ) -> RunSummary: ...

    def snapshot(self, session_id: UUID) -> InteractiveSnapshot: ...

    def sessions(self) -> list[InteractiveSession]: ...


class ConversationInteractiveAdapter:
    """Keep the old interactive shape while delegating every operation to conversation."""

    def __init__(self, conversation: ConversationWorkflow, project_id: UUID) -> None:
        self._conversation = conversation
        self._project_id = project_id

    def create(self, title: str | None = None) -> InteractiveSession:
        return self._conversation.create_session(title)

    def submit(
        self,
        session_id: UUID,
        message: str,
        permission_mode: PermissionMode | None = None,
        options: RunOptions | None = None,
    ) -> Run:
        return self._conversation.submit(
            PromptRequest(
                project_id=self._project_id,
                session_id=session_id,
                text=message,
                permission_mode=permission_mode,
                options=options or RunOptions(),
            )
        )

    def execute(
        self,
        run_id: UUID,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> RunSummary:
        return self._conversation.execute(run_id, progress, cancellation)

    def resume_session(self, session_id: UUID) -> InteractiveSnapshot:
        return self._conversation.snapshot(session_id)

    def list_sessions(self) -> list[InteractiveSession]:
        return self._conversation.sessions()



def transcript_for_runs(store: InteractiveStore, runs: list[Run]) -> tuple[TranscriptEntry, ...]:
    transcript: list[TranscriptEntry] = []
    for run in runs:
        transcript.append(TranscriptEntry(role="user", text=redact_text(run.task), run_id=run.id))
        final_text = ""
        for iteration in store.list_iterations(run.id):
            if iteration.model_response is None:
                continue
            content = iteration.model_response.get("content")
            if isinstance(content, str) and content.strip():
                final_text = redact_text(content).strip()
        if final_text:
            transcript.append(
                TranscriptEntry(role="assistant", text=final_text, run_id=run.id)
            )
    return tuple(transcript)


class InteractiveSessionService:
    def __init__(
        self,
        project_id: UUID,
        store: InteractiveStore,
        runs: RunService,
    ) -> None:
        self._project_id = project_id
        self._store = store
        self._runs = runs

    def create(self, title: str | None = None) -> InteractiveSession:
        session = InteractiveSession(project_id=self._project_id, title=title)
        self._store.create_interactive_session(session)
        return session

    def submit(
        self,
        session_id: UUID,
        message: str,
        permission_mode: PermissionMode | None = None,
        options: RunOptions | None = None,
    ) -> Run:
        if not message.strip():
            raise ValueError("message must not be blank")
        if len(message) > 100_000:
            raise ValueError("message exceeds 100000 characters")
        session = self._require_session(session_id)
        return self._runs.create_run(
            RunRequest(
                task=message,
                project_id=session.project_id,
                session_id=session.id,
                permission_mode=permission_mode,
                options=options or RunOptions(),
            )
        )

    def execute(
        self,
        run_id: UUID,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> RunSummary:
        return self._runs.resume(
            run_id,
            progress=progress,
            cancellation=cancellation,
        )

    def resume_session(self, session_id: UUID) -> InteractiveSnapshot:
        session = self._require_session(session_id)
        runs = self._store.list_runs_for_session(session.id)
        active_run = next((run for run in reversed(runs) if not run.state.is_terminal), None)
        return InteractiveSnapshot(
            session=session,
            runs=tuple(runs),
            active_run=active_run,
            transcript=transcript_for_runs(self._store, runs),
        )

    def list_sessions(self) -> list[InteractiveSession]:
        return self._store.list_interactive_sessions(self._project_id)

    def _require_session(self, session_id: UUID) -> InteractiveSession:
        session = self._store.get_interactive_session(session_id)
        if session is None or session.project_id != self._project_id:
            raise KeyError(f"unknown interactive session: {session_id}")
        return session
