from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from coding613.application.interactive import InteractiveSnapshot, TranscriptEntry
from coding613.domain.conversation import ContextSummary, DiagnosticCheck, DiagnosticReport
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import PermissionMode, Run, RunState, RunSummary, StopReason
from coding613.domain.session_events import EventType
from coding613.ports.progress import ProgressKind, RunProgress
from coding613.tui.controller import TuiController


class FakeInteractive:
    def __init__(self) -> None:
        self.session = InteractiveSession(project_id=uuid4())
        self.runs: list[Run] = []
        self.transcript: list[TranscriptEntry] = []
        self.execute_calls: list[object] = []

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
        self.execute_calls.append(run_id)
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
        active = next((run for run in reversed(self.runs) if not run.state.is_terminal), None)
        return InteractiveSnapshot(
            session=self.session,
            runs=tuple(self.runs),
            active_run=active,
            transcript=tuple(self.transcript),
        )


class MultiSessionInteractive:
    def __init__(self) -> None:
        project_id = uuid4()
        self.sessions = [
            InteractiveSession(project_id=project_id, title="first"),
            InteractiveSession(project_id=project_id, title="second"),
        ]
        self.runs = {
            session.id: [
                Run(
                    project_id=project_id,
                    session_id=session.id,
                    task=session.title or "task",
                    state=RunState.COMPLETED,
                    stop_reason=StopReason.SUCCESS,
                )
            ]
            for session in self.sessions
        }

    def create(self, title=None):
        session = InteractiveSession(project_id=self.sessions[0].project_id, title=title)
        self.sessions.append(session)
        self.runs[session.id] = []
        return session

    def list_sessions(self):
        return list(self.sessions)

    def resume_session(self, session_id):
        session = next(item for item in self.sessions if item.id == session_id)
        runs = self.runs[session.id]
        return InteractiveSnapshot(
            session=session,
            runs=tuple(runs),
            active_run=next((run for run in reversed(runs) if not run.state.is_terminal), None),
            transcript=tuple(
                TranscriptEntry(role="user", text=run.task, run_id=run.id) for run in runs
            ),
        )


class FakeRuns:
    def __init__(self) -> None:
        self.pause_calls: list[object] = []
        self.summaries: dict[object, RunSummary] = {}

    def pause(self, run_id):
        self.pause_calls.append(run_id)
        return RunSummary(run_id=run_id, status=RunState.PAUSED)

    def approve(self, request_id):
        return request_id

    def reject(self, request_id):
        return request_id

    def get_summary(self, run_id):
        return self.summaries[run_id]


class FakeContext:
    def __init__(self, session_id):
        self.session_id = session_id
        self.report_calls = []
        self.compact_calls = []

    def report(self, session_id):
        self.report_calls.append(session_id)
        return ContextSummary(
            summary_revision="report",
            estimated_tokens=3,
            max_tokens=100,
        )

    def compact(self, session_id):
        self.compact_calls.append(session_id)
        return ContextSummary(
            summary_revision="compact",
            estimated_tokens=2,
            max_tokens=100,
        )


class FakeDiagnostics:
    def run(self, project_id):
        return DiagnosticReport(
            project_id=project_id,
            checks=(DiagnosticCheck(name="provider", status="pass", detail="ready"),),
        )


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
    events = controller.drain_events()
    assert [event.type for event in events] == [
        EventType.ASSISTANT_DELTA,
        EventType.ASSISTANT_DELTA,
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


@pytest.mark.asyncio
async def test_controller_resume_continues_same_paused_run() -> None:
    interactive = FakeInteractive()
    paused = Run(
        project_id=interactive.session.project_id,
        session_id=interactive.session.id,
        task="repair",
        state=RunState.PAUSED,
    )
    interactive.runs.append(paused)
    runs = FakeRuns()
    runs.summaries[paused.id] = RunSummary(run_id=paused.id, status=RunState.PAUSED)
    controller = TuiController(interactive, runs)

    snapshot = await controller.resume("latest")

    assert interactive.execute_calls == [paused.id]
    assert snapshot.runs[-1].id == paused.id
    assert snapshot.runs[-1].state is RunState.COMPLETED


@pytest.mark.asyncio
async def test_controller_resume_continues_an_interrupted_running_run() -> None:
    interactive = FakeInteractive()
    running = Run(
        project_id=interactive.session.project_id,
        session_id=interactive.session.id,
        task="repair",
        state=RunState.RUNNING,
    )
    interactive.runs.append(running)
    runs = FakeRuns()
    runs.summaries[running.id] = RunSummary(run_id=running.id, status=RunState.RUNNING)
    controller = TuiController(interactive, runs)

    snapshot = await controller.resume("latest")

    assert interactive.execute_calls == [running.id]
    assert snapshot.runs[-1].state is RunState.COMPLETED


@pytest.mark.asyncio
async def test_controller_resume_reconstructs_pending_approval_summary() -> None:
    interactive = FakeInteractive()
    waiting = Run(
        project_id=interactive.session.project_id,
        session_id=interactive.session.id,
        task="approval",
        state=RunState.WAITING_APPROVAL,
    )
    interactive.runs.append(waiting)
    approval_id = uuid4()
    runs = FakeRuns()
    runs.summaries[waiting.id] = RunSummary(
        run_id=waiting.id,
        status=RunState.WAITING_APPROVAL,
        stop_reason=StopReason.APPROVAL_REQUIRED,
        approvals=(approval_id,),
    )
    controller = TuiController(interactive, runs)

    snapshot = await controller.resume("latest")

    assert snapshot.active_run == waiting
    assert controller.last_summary is not None
    assert controller.last_summary.approvals == (approval_id,)
    assert interactive.execute_calls == []


@pytest.mark.asyncio
async def test_controller_exposes_context_and_diagnostic_services() -> None:
    interactive = FakeInteractive()
    runs = FakeRuns()
    context = FakeContext(interactive.session.id)
    diagnostics = FakeDiagnostics()
    controller = TuiController(
        interactive,
        runs,
        context=context,
        diagnostics=diagnostics,
    )

    report = await controller.context_report()
    compacted = await controller.compact()
    diagnostic_report = await controller.diagnostics()

    assert report.summary_revision == "report"
    assert compacted.summary_revision == "compact"
    assert context.report_calls == [interactive.session.id]
    assert context.compact_calls == [interactive.session.id]
    assert diagnostic_report.checks[0].name == "provider"
    assert diagnostic_report.project_id == interactive.session.project_id


@pytest.mark.asyncio
async def test_controller_drops_late_progress_when_switching_sessions() -> None:
    interactive = MultiSessionInteractive()
    controller = TuiController(interactive, FakeRuns())
    first, second = interactive.sessions
    first_run = interactive.runs[first.id][0]
    second_run = interactive.runs[second.id][0]

    await controller.resume(str(first.id))
    old_queue = controller._queue
    old_queue.put(RunProgress(run_id=first_run.id, kind=ProgressKind.TEXT_DELTA, text="old"))

    snapshot = await controller.resume(str(second.id))

    assert snapshot.session.id == second.id
    assert controller.session_id == second.id
    assert controller.drain_progress() == ()
    assert not controller.accepts_progress(first_run.id)
    assert not controller.accepts_progress(second_run.id)


@pytest.mark.asyncio
async def test_controller_drops_completed_run_progress_before_new_run() -> None:
    interactive = FakeInteractive()
    controller = TuiController(interactive, FakeRuns())

    snapshot = await controller.submit("first")
    first_run = snapshot.runs[-1]
    controller._queue.put(
        RunProgress(run_id=first_run.id, kind=ProgressKind.TEXT_DELTA, text="late")
    )

    await controller.submit("second")

    updates = controller.drain_progress()
    assert updates
    assert all(update.run_id != first_run.id for update in updates)


@pytest.mark.asyncio
async def test_controller_drops_progress_late_after_completed_stream_is_drained() -> None:
    interactive = FakeInteractive()
    controller = TuiController(interactive, FakeRuns())

    snapshot = await controller.submit("first")
    first_run = snapshot.runs[-1]
    assert controller.drain_progress()
    controller._queue.put(
        RunProgress(run_id=first_run.id, kind=ProgressKind.TEXT_DELTA, text="late")
    )

    assert controller.drain_progress() == ()
