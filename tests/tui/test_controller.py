from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from coding613.application.interactive import InteractiveSnapshot, TranscriptEntry
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import PermissionMode, Run, RunState, RunSummary, StopReason
from coding613.ports.progress import ProgressKind, RunProgress
from coding613.tui.controller import TuiController


class FakeInteractive:
    def __init__(self) -> None:
        self.session = InteractiveSession(project_id=uuid4())
        self.runs: list[Run] = []
        self.transcript: list[TranscriptEntry] = []

    def create(self, title=None):
        self.session = InteractiveSession(project_id=self.session.project_id, title=title)
        return self.session

    def list_sessions(self):
        return [self.session]

    def submit(self, session_id, message, permission_mode=None):
        run = Run(
            project_id=self.session.project_id,
            session_id=session_id,
            task=message,
            permission_mode=permission_mode or PermissionMode.BALANCED,
        )
        self.runs.append(run)
        self.transcript.append(TranscriptEntry(role="user", text=message, run_id=run.id))
        return run

    def execute(self, run_id, progress, cancellation):
        progress.publish(RunProgress(run_id=run_id, kind=ProgressKind.TEXT_DELTA, text="hel"))
        progress.publish(RunProgress(run_id=run_id, kind=ProgressKind.TEXT_DELTA, text="lo"))
        self.transcript.append(TranscriptEntry(role="assistant", text="hello", run_id=run_id))
        self.runs[-1] = self.runs[-1].model_copy(
            update={
                "state": RunState.COMPLETED,
                "stop_reason": StopReason.SUCCESS,
                "updated_at": datetime.now(UTC),
            }
        )
        return RunSummary(
            run_id=run_id,
            status=RunState.COMPLETED,
            stop_reason=StopReason.SUCCESS,
        )

    def resume_session(self, session_id):
        return InteractiveSnapshot(
            session=self.session,
            runs=tuple(self.runs),
            transcript=tuple(self.transcript),
        )


class FakeRuns:
    def __init__(self) -> None:
        self.pause_calls: list[object] = []

    def pause(self, run_id):
        self.pause_calls.append(run_id)
        return RunSummary(run_id=run_id, status=RunState.PAUSED)

    def approve(self, request_id):
        return request_id

    def reject(self, request_id):
        return request_id


@pytest.mark.asyncio
async def test_controller_streams_deltas_and_restores_final_transcript() -> None:
    interactive = FakeInteractive()
    runs = FakeRuns()
    controller = TuiController(interactive, runs)

    snapshot = await controller.submit("repair", PermissionMode.BALANCED)

    deltas = [
        update.text
        for update in controller.drain_progress()
        if update.kind is ProgressKind.TEXT_DELTA
    ]
    assert deltas == ["hel", "lo"]
    assert [(entry.role, entry.text) for entry in snapshot.transcript] == [
        ("user", "repair"),
        ("assistant", "hello"),
    ]


@pytest.mark.asyncio
async def test_controller_pause_calls_run_service_once() -> None:
    interactive = FakeInteractive()
    runs = FakeRuns()
    controller = TuiController(interactive, runs)
    run = interactive.submit(interactive.session.id, "pause")
    controller.active_run_id = run.id

    await controller.pause()
    await controller.pause()

    assert runs.pause_calls == [run.id]
