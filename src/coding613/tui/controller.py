"""Async-facing adapter between Textual and blocking application services."""

from __future__ import annotations

import asyncio
from queue import Empty, SimpleQueue
from typing import Any, Protocol
from uuid import UUID

from coding613.application.events import ProgressEventBridge, SequencedEventSink
from coding613.application.interactive import InteractiveSnapshot
from coding613.application.progress import CancellationToken
from coding613.domain.conversation import ContextSummary, DiagnosticReport, RunOptions
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import ApprovalRequest, PermissionMode, RunState, RunSummary
from coding613.domain.session_events import SessionEvent
from coding613.ports.events import EventSink
from coding613.ports.progress import ProgressSink, RunProgress


class InteractiveService(Protocol):
    def create(self, title: str | None = None) -> InteractiveSession: ...

    def submit(
        self,
        session_id: UUID,
        message: str,
        permission_mode: PermissionMode | None = None,
        options: RunOptions | None = None,
    ) -> Any: ...

    def execute(
        self,
        run_id: UUID,
        progress: ProgressSink,
        cancellation: CancellationToken,
    ) -> RunSummary: ...

    def resume_session(self, session_id: UUID) -> InteractiveSnapshot: ...

    def list_sessions(self) -> list[InteractiveSession]: ...


class RunActions(Protocol):
    def pause(self, run_id: UUID) -> RunSummary: ...

    def approve(self, request_id: UUID) -> Any: ...

    def reject(self, request_id: UUID) -> Any: ...

    def get_approval(self, request_id: UUID) -> ApprovalRequest: ...

    def get_summary(self, run_id: UUID) -> RunSummary: ...


class ContextActions(Protocol):
    def report(self, session_id: UUID) -> ContextSummary: ...

    def compact(self, session_id: UUID) -> ContextSummary: ...


class DiagnosticActions(Protocol):
    def run(self, project_id: UUID) -> DiagnosticReport: ...


class QueueProgressSink:
    def __init__(self, queue: SimpleQueue[RunProgress]) -> None:
        self._queue = queue

    def publish(self, update: RunProgress) -> None:
        self._queue.put(update)


class QueueEventSink:
    def __init__(self, queue: SimpleQueue[SessionEvent]) -> None:
        self._queue = queue

    def publish(self, event: SessionEvent) -> None:
        self._queue.put(event)


class TuiController:
    def __init__(
        self,
        interactive: InteractiveService,
        runs: RunActions,
        context: ContextActions | None = None,
        diagnostics: DiagnosticActions | None = None,
        project_id: UUID | None = None,
    ) -> None:
        self._interactive = interactive
        self._runs = runs
        self._context = context
        self._diagnostics = diagnostics
        self._project_id = project_id
        self._queue: SimpleQueue[RunProgress] = SimpleQueue()
        self._sink = QueueProgressSink(self._queue)
        self._event_queue: SimpleQueue[SessionEvent] = SimpleQueue()
        self._event_sink: EventSink = SequencedEventSink(QueueEventSink(self._event_queue))
        self._cancellation = CancellationToken()
        self._session_id: UUID | None = None
        self._snapshot: InteractiveSnapshot | None = None
        self._progress_stream_run_id: UUID | None = None
        self._event_stream_run_id: UUID | None = None
        self._progress_stream_terminal = False
        self._event_stream_terminal = False
        self._stream_generation = 0
        self._execution_lock = asyncio.Lock()
        self._pause_lock = asyncio.Lock()
        self._pause_requested_for: UUID | None = None
        self.active_run_id: UUID | None = None
        self.last_summary: RunSummary | None = None

    @property
    def session_id(self) -> UUID | None:
        """Return the session whose transcript and live streams are visible."""

        return self._session_id

    def accepts_progress(self, run_id: UUID) -> bool:
        """Return whether a progress update belongs to the currently visible run."""

        return self._progress_stream_run_id == run_id

    async def submit(
        self,
        message: str,
        permission_mode: PermissionMode | None = None,
        options: RunOptions | None = None,
    ) -> InteractiveSnapshot:
        async with self._execution_lock:
            if self._session_id is None:
                session = await asyncio.to_thread(self._interactive.create)
                self._session_id = session.id
            self._reset_streams()
            session_id = self._session_id
            generation = self._stream_generation
            if options is None or options == RunOptions():
                run = await asyncio.to_thread(
                    self._interactive.submit,
                    session_id,
                    message,
                    permission_mode,
                )
            else:
                run = await asyncio.to_thread(
                    self._interactive.submit,
                    session_id,
                    message,
                    permission_mode,
                    options,
                )
            self.active_run_id = run.id
            self._progress_stream_run_id = run.id
            self._event_stream_run_id = run.id
            self._pause_requested_for = None
            self._cancellation.reset()
            event_sink = self._progress_bridge(run.id)
            summary = await asyncio.to_thread(
                self._interactive.execute,
                run.id,
                event_sink,
                self._cancellation,
            )
            if generation != self._stream_generation or self._session_id != session_id:
                return await self.snapshot()
            self.last_summary = summary
            if summary.status.is_terminal:
                self._progress_stream_terminal = True
                self._event_stream_terminal = True
                self.active_run_id = None
            snapshot = await asyncio.to_thread(
                self._interactive.resume_session, session_id
            )
            return self._set_snapshot(snapshot)

    async def pause(self) -> RunSummary | None:
        async with self._pause_lock:
            if self.active_run_id is None:
                return None
            if self._pause_requested_for == self.active_run_id:
                return None
            self._pause_requested_for = self.active_run_id
            self._cancellation.cancel()
            try:
                return await asyncio.to_thread(self._runs.pause, self.active_run_id)
            except Exception:
                self._pause_requested_for = None
                raise

    async def approve(self, request_id: UUID) -> InteractiveSnapshot | None:
        await asyncio.to_thread(self._runs.approve, request_id)
        return await self._continue_active()

    async def reject(self, request_id: UUID) -> InteractiveSnapshot | None:
        await asyncio.to_thread(self._runs.reject, request_id)
        return await self._continue_active()

    async def get_approval(self, request_id: UUID) -> ApprovalRequest:
        return await asyncio.to_thread(self._runs.get_approval, request_id)

    async def resume(self, selector: str = "latest") -> InteractiveSnapshot:
        sessions = await self.list_sessions()
        if not sessions:
            raise KeyError("no interactive sessions")
        if selector == "latest":
            session = sessions[0]
        else:
            session_id = UUID(selector)
            selected = next((item for item in sessions if item.id == session_id), None)
            if selected is None:
                raise KeyError(f"unknown interactive session: {selector}")
            session = selected
        self._reset_streams()
        self._session_id = session.id
        snapshot = await asyncio.to_thread(
            self._interactive.resume_session, session.id
        )
        self._set_snapshot(snapshot)
        self.active_run_id = (
            snapshot.active_run.id if snapshot.active_run is not None else None
        )
        self._progress_stream_run_id = self.active_run_id
        self._event_stream_run_id = self.active_run_id
        self.last_summary = None
        if snapshot.active_run is not None:
            self.last_summary = await asyncio.to_thread(
                self._runs.get_summary, snapshot.active_run.id
            )
            if snapshot.active_run.state in {
                RunState.PAUSED,
                RunState.RUNNING,
                RunState.WAITING_MODEL,
            }:
                continued = await self._continue_active()
                assert continued is not None
                return continued
        if snapshot.active_run is None:
            self._progress_stream_run_id = None
            self._event_stream_run_id = None
        return snapshot

    async def list_sessions(self) -> list[InteractiveSession]:
        return await asyncio.to_thread(self._interactive.list_sessions)

    async def session_snapshot(self, session_id: UUID) -> InteractiveSnapshot:
        """Read one session for menu metadata without changing the selection."""

        return await asyncio.to_thread(self._interactive.resume_session, session_id)

    async def snapshot(self) -> InteractiveSnapshot:
        if self._session_id is None:
            session = await asyncio.to_thread(self._interactive.create)
            self._session_id = session.id
        snapshot = await asyncio.to_thread(
            self._interactive.resume_session, self._session_id
        )
        return self._set_snapshot(snapshot)

    async def clear(self) -> InteractiveSnapshot:
        self._reset_streams()
        session = await asyncio.to_thread(self._interactive.create)
        self._session_id = session.id
        self.active_run_id = None
        self.last_summary = None
        snapshot = await asyncio.to_thread(
            self._interactive.resume_session, session.id
        )
        return self._set_snapshot(snapshot)

    async def context_report(self) -> ContextSummary:
        if self._context is None:
            raise RuntimeError("context service is unavailable")
        session_id = await self._ensure_session()
        return await asyncio.to_thread(self._context.report, session_id)

    async def compact(self) -> ContextSummary:
        if self._context is None:
            raise RuntimeError("context service is unavailable")
        session_id = await self._ensure_session()
        return await asyncio.to_thread(self._context.compact, session_id)

    async def diagnostics(self) -> DiagnosticReport:
        if self._diagnostics is None:
            raise RuntimeError("diagnostic service is unavailable")
        project_id = self._project_id
        if project_id is None:
            snapshot = await self.snapshot()
            project_id = snapshot.session.project_id
        return await asyncio.to_thread(self._diagnostics.run, project_id)

    def drain_progress(self) -> tuple[RunProgress, ...]:
        updates: list[RunProgress] = []
        while True:
            try:
                update = self._queue.get_nowait()
                if self.accepts_progress(update.run_id):
                    updates.append(update)
            except Empty:
                if self._progress_stream_terminal:
                    self._progress_stream_run_id = None
                    self._progress_stream_terminal = False
                return tuple(updates)

    def drain_events(self) -> tuple[SessionEvent, ...]:
        events: list[SessionEvent] = []
        while True:
            try:
                event = self._event_queue.get_nowait()
                if (
                    self._session_id is not None
                    and event.session_id == self._session_id
                    and event.run_id == self._event_stream_run_id
                ):
                    events.append(event)
            except Empty:
                if self._event_stream_terminal:
                    self._event_stream_run_id = None
                    self._event_stream_terminal = False
                return tuple(events)

    async def _continue_active(self) -> InteractiveSnapshot | None:
        if self.active_run_id is None or self._session_id is None:
            return self._snapshot
        self._pause_requested_for = None
        self._cancellation.reset()
        session_id = self._session_id
        generation = self._stream_generation
        event_sink = self._progress_bridge(self.active_run_id)
        summary = await asyncio.to_thread(
            self._interactive.execute,
            self.active_run_id,
            event_sink,
            self._cancellation,
        )
        if generation != self._stream_generation or self._session_id != session_id:
            return await self.snapshot()
        self.last_summary = summary
        if summary.status.is_terminal:
            self._progress_stream_terminal = True
            self._event_stream_terminal = True
            self.active_run_id = None
        snapshot = await asyncio.to_thread(
            self._interactive.resume_session, session_id
        )
        return self._set_snapshot(snapshot)

    async def _ensure_session(self) -> UUID:
        if self._session_id is None:
            await self.snapshot()
        if self._session_id is None:
            raise RuntimeError("interactive session is unavailable")
        return self._session_id

    def _progress_bridge(self, run_id: UUID) -> ProgressSink:
        if self._session_id is None:
            raise RuntimeError("interactive session is not selected")
        return ProgressEventBridge(
            self._session_id,
            run_id,
            self._event_sink,
            progress=self._sink,
        )

    def _set_snapshot(self, snapshot: InteractiveSnapshot) -> InteractiveSnapshot:
        self._snapshot = snapshot
        return snapshot

    def _reset_streams(self) -> None:
        """Detach producers for the previous session from the visible queues."""

        self._cancellation.cancel()
        self._cancellation = CancellationToken()
        self._stream_generation += 1
        self.active_run_id = None
        self._pause_requested_for = None
        self._queue = SimpleQueue()
        self._sink = QueueProgressSink(self._queue)
        self._event_queue = SimpleQueue()
        self._event_sink = SequencedEventSink(QueueEventSink(self._event_queue))
        self._progress_stream_run_id = None
        self._event_stream_run_id = None
        self._progress_stream_terminal = False
        self._event_stream_terminal = False
