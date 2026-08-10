"""Async-facing adapter between Textual and blocking application services."""

from __future__ import annotations

import asyncio
from queue import Empty, SimpleQueue
from typing import Any, Protocol
from uuid import UUID

from coding613.application.events import ProgressEventBridge, SequencedEventSink
from coding613.application.interactive import InteractiveSnapshot
from coding613.application.progress import CancellationToken
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
    def __init__(self, interactive: InteractiveService, runs: RunActions) -> None:
        self._interactive = interactive
        self._runs = runs
        self._queue: SimpleQueue[RunProgress] = SimpleQueue()
        self._sink = QueueProgressSink(self._queue)
        self._event_queue: SimpleQueue[SessionEvent] = SimpleQueue()
        self._event_sink: EventSink = SequencedEventSink(QueueEventSink(self._event_queue))
        self._cancellation = CancellationToken()
        self._session_id: UUID | None = None
        self._snapshot: InteractiveSnapshot | None = None
        self._execution_lock = asyncio.Lock()
        self._pause_lock = asyncio.Lock()
        self._pause_requested_for: UUID | None = None
        self.active_run_id: UUID | None = None
        self.last_summary: RunSummary | None = None

    async def submit(
        self, message: str, permission_mode: PermissionMode | None = None
    ) -> InteractiveSnapshot:
        async with self._execution_lock:
            if self._session_id is None:
                session = await asyncio.to_thread(self._interactive.create)
                self._session_id = session.id
            run = await asyncio.to_thread(
                self._interactive.submit,
                self._session_id,
                message,
                permission_mode,
            )
            self.active_run_id = run.id
            self._pause_requested_for = None
            self._cancellation.reset()
            event_sink = self._progress_bridge(run.id)
            summary = await asyncio.to_thread(
                self._interactive.execute,
                run.id,
                event_sink,
                self._cancellation,
            )
            self.last_summary = summary
            if summary.status.is_terminal:
                self.active_run_id = None
            self._snapshot = await asyncio.to_thread(
                self._interactive.resume_session, self._session_id
            )
            return self._snapshot

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
        self._session_id = session.id
        self._snapshot = await asyncio.to_thread(
            self._interactive.resume_session, session.id
        )
        self.active_run_id = (
            self._snapshot.active_run.id if self._snapshot.active_run is not None else None
        )
        self.last_summary = None
        if self._snapshot.active_run is not None:
            self.last_summary = await asyncio.to_thread(
                self._runs.get_summary, self._snapshot.active_run.id
            )
            if self._snapshot.active_run.state is RunState.PAUSED:
                continued = await self._continue_active()
                assert continued is not None
                return continued
        return self._snapshot

    async def list_sessions(self) -> list[InteractiveSession]:
        return await asyncio.to_thread(self._interactive.list_sessions)

    async def snapshot(self) -> InteractiveSnapshot:
        if self._session_id is None:
            session = await asyncio.to_thread(self._interactive.create)
            self._session_id = session.id
        self._snapshot = await asyncio.to_thread(
            self._interactive.resume_session, self._session_id
        )
        return self._snapshot

    async def clear(self) -> InteractiveSnapshot:
        session = await asyncio.to_thread(self._interactive.create)
        self._session_id = session.id
        self.active_run_id = None
        self.last_summary = None
        self._snapshot = await asyncio.to_thread(
            self._interactive.resume_session, session.id
        )
        return self._snapshot

    def drain_progress(self) -> tuple[RunProgress, ...]:
        updates: list[RunProgress] = []
        while True:
            try:
                updates.append(self._queue.get_nowait())
            except Empty:
                return tuple(updates)

    def drain_events(self) -> tuple[SessionEvent, ...]:
        events: list[SessionEvent] = []
        while True:
            try:
                events.append(self._event_queue.get_nowait())
            except Empty:
                return tuple(events)

    async def _continue_active(self) -> InteractiveSnapshot | None:
        if self.active_run_id is None or self._session_id is None:
            return self._snapshot
        self._pause_requested_for = None
        self._cancellation.reset()
        event_sink = self._progress_bridge(self.active_run_id)
        summary = await asyncio.to_thread(
            self._interactive.execute,
            self.active_run_id,
            event_sink,
            self._cancellation,
        )
        self.last_summary = summary
        if summary.status.is_terminal:
            self.active_run_id = None
        self._snapshot = await asyncio.to_thread(
            self._interactive.resume_session, self._session_id
        )
        return self._snapshot

    def _progress_bridge(self, run_id: UUID) -> ProgressSink:
        if self._session_id is None:
            raise RuntimeError("interactive session is not selected")
        return ProgressEventBridge(
            self._session_id,
            run_id,
            self._event_sink,
            progress=self._sink,
        )
