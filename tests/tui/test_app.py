from __future__ import annotations

import time
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from textual.widgets import Static

from coding613.application.interactive import InteractiveSnapshot, TranscriptEntry
from coding613.application.progress import CancellationToken
from coding613.domain.actions import ToolCall
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import (
    ApprovalRequest,
    ApprovalStatus,
    PermissionMode,
    Run,
    RunState,
    RunSummary,
    StopReason,
)
from coding613.domain.permissions import PermissionRule
from coding613.ports.progress import ProgressKind, ProgressSink, RunProgress
from coding613.tui.app import CodingApp
from coding613.tui.controller import TuiController
from coding613.tui.renderers import ApprovalView, AssistantMessage, DetailMessage
from coding613.tui.widgets import ActiveOperation, ConversationLog, StatusFooter, TaskComposer


class FakeUiServices:
    def __init__(self) -> None:
        self.session = InteractiveSession(project_id=uuid4())
        self.runs: list[Run] = []
        self.transcript: list[TranscriptEntry] = []
        self.approvals: dict[UUID, ApprovalRequest] = {}
        self.pause_calls: list[UUID] = []
        self.approve_calls: list[UUID] = []
        self.reject_calls: list[UUID] = []
        self.approval_decision: str | None = None
        self.execution_started = Event()

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

    def execute(self, run_id, progress: ProgressSink, cancellation: CancellationToken):
        self.execution_started.set()
        run = self.runs[-1]
        if run.task == "pause":
            if run.state is RunState.PAUSED:
                self.transcript.append(
                    TranscriptEntry(role="assistant", text="resumed", run_id=run_id)
                )
                self.runs[-1] = run.model_copy(
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
            while not cancellation.is_cancelled():
                time.sleep(0.005)
            replacement = run.model_copy(
                update={"state": RunState.PAUSED, "updated_at": datetime.now(UTC)}
            )
            self.runs[-1] = replacement
            return RunSummary(run_id=run_id, status=RunState.PAUSED)
        if run.task == "approval":
            if self.approval_decision == "approve":
                self.transcript.append(
                    TranscriptEntry(role="assistant", text="patched", run_id=run_id)
                )
                return RunSummary(
                    run_id=run_id,
                    status=RunState.COMPLETED,
                    stop_reason=StopReason.SUCCESS,
                )
            if self.approval_decision == "reject":
                self.runs[-1] = run.model_copy(
                    update={
                        "state": RunState.FAILED,
                        "stop_reason": StopReason.APPROVAL_REJECTED,
                        "updated_at": datetime.now(UTC),
                    }
                )
                return RunSummary(
                    run_id=run_id,
                    status=RunState.FAILED,
                    stop_reason=StopReason.APPROVAL_REJECTED,
                )
            request = ApprovalRequest(
                run_id=run_id,
                action=ToolCall(name="apply_patch", arguments={"patch": _long_patch()}),
                reason="strict mode requires approval",
            )
            self.approvals[request.id] = request
            self.runs[-1] = run.model_copy(
                update={"state": RunState.WAITING_APPROVAL, "updated_at": datetime.now(UTC)}
            )
            return RunSummary(
                run_id=run_id,
                status=RunState.WAITING_APPROVAL,
                stop_reason=StopReason.APPROVAL_REQUIRED,
                approvals=(request.id,),
            )
        if run.task == "error":
            raise RuntimeError("provider failed api_key=topsecret sk-secretvalue")
        progress.publish(RunProgress(run_id=run_id, kind=ProgressKind.TEXT_DELTA, text="hel"))
        progress.publish(RunProgress(run_id=run_id, kind=ProgressKind.TEXT_DELTA, text="lo"))
        self.transcript.append(TranscriptEntry(role="assistant", text="hello", run_id=run_id))
        self.runs[-1] = run.model_copy(
            update={
                "state": RunState.COMPLETED,
                "stop_reason": StopReason.SUCCESS,
                "updated_at": datetime.now(UTC),
            }
        )
        return RunSummary(run_id=run_id, status=RunState.COMPLETED, stop_reason=StopReason.SUCCESS)

    def resume_session(self, session_id):
        active = next((run for run in reversed(self.runs) if not run.state.is_terminal), None)
        return InteractiveSnapshot(
            session=self.session,
            runs=tuple(self.runs),
            active_run=active,
            transcript=tuple(self.transcript),
        )

    def pause(self, run_id):
        self.pause_calls.append(run_id)
        return RunSummary(run_id=run_id, status=RunState.PAUSED)

    def approve(self, request_id):
        self.approve_calls.append(request_id)
        self.approval_decision = "approve"
        request = self.approvals[request_id]
        self.approvals[request_id] = request.model_copy(
            update={"status": ApprovalStatus.APPROVED, "resolved_at": datetime.now(UTC)}
        )
        run = self.runs[-1]
        self.runs[-1] = run.model_copy(
            update={
                "state": RunState.COMPLETED,
                "stop_reason": StopReason.SUCCESS,
                "updated_at": datetime.now(UTC),
            }
        )
        self.transcript.append(TranscriptEntry(role="assistant", text="patched", run_id=run.id))
        return request_id

    def reject(self, request_id):
        self.reject_calls.append(request_id)
        self.approval_decision = "reject"
        request = self.approvals[request_id]
        self.approvals[request_id] = request.model_copy(
            update={"status": ApprovalStatus.REJECTED, "resolved_at": datetime.now(UTC)}
        )
        return request_id

    def get_approval(self, request_id):
        return self.approvals[request_id]

    def get_summary(self, run_id):
        run = next(run for run in self.runs if run.id == run_id)
        approvals = tuple(
            request.id
            for request in self.approvals.values()
            if request.run_id == run_id and request.status is ApprovalStatus.PENDING
        )
        return RunSummary(
            run_id=run_id,
            status=run.state,
            stop_reason=(
                StopReason.APPROVAL_REQUIRED
                if run.state is RunState.WAITING_APPROVAL
                else run.stop_reason
            ),
            approvals=approvals,
        )


class FakePermissionRules:
    def __init__(self) -> None:
        self.rules: list[PermissionRule] = []

    def list_rules(self) -> list[PermissionRule]:
        return list(self.rules)

    def allow_tool(self, name: str) -> PermissionRule:
        rule = PermissionRule(scope="tool", pattern=name, effect="allow")
        self.rules = [item for item in self.rules if item.pattern != name]
        self.rules.append(rule)
        return rule

    def deny_tool(self, name: str) -> PermissionRule:
        rule = PermissionRule(scope="tool", pattern=name, effect="deny")
        self.rules = [item for item in self.rules if item.pattern != name]
        self.rules.append(rule)
        return rule

    def clear_tool(self, name: str) -> None:
        self.rules = [item for item in self.rules if item.pattern != name]


def _long_patch() -> str:
    additions = "".join(f"+line {index}\n" for index in range(200))
    return (
        "--- /dev/null\n+++ b/src/generated.py\n"
        "@@ -0,0 +1,200 @@\n" + additions
    )


def _controller(fake: FakeUiServices) -> TuiController:
    return TuiController(fake, fake)


@pytest.mark.asyncio
async def test_tui_shell_focuses_composer_and_inserts_initial_task() -> None:
    app = CodingApp(initial_task="repair tests")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        composer = app.query_one(TaskComposer)
        assert app.focused is composer
        assert composer.text == "repair tests"
        assert app.query_one(ConversationLog).size.height > 0
        assert app.query_one(StatusFooter).size.height == 1


@pytest.mark.asyncio
async def test_tui_history_restores_previous_prompt_without_submitting() -> None:
    fake = FakeUiServices()
    app = CodingApp(controller=_controller(fake))
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("first")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if fake.runs and fake.runs[-1].state is RunState.COMPLETED:
                break
        before = len(fake.runs)
        await pilot.press("up")
        assert composer.text == "first"
        assert len(fake.runs) == before


@pytest.mark.asyncio
async def test_tui_shell_stays_stable_in_narrow_terminal() -> None:
    app = CodingApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        composer = app.query_one(TaskComposer)
        footer = app.query_one(StatusFooter)
        log = app.query_one(ConversationLog)
        assert composer.region.width == footer.region.width == log.region.width == 60
        assert composer.region.height >= 3
        assert footer.region.y >= composer.region.bottom


@pytest.mark.asyncio
async def test_tui_submits_in_background_and_replaces_streamed_draft_once() -> None:
    fake = FakeUiServices()
    app = CodingApp(controller=_controller(fake))
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("repair")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if app.query(AssistantMessage):
                break
        await pilot.pause(0.05)

        assistants = list(app.query(AssistantMessage))
        assert len(assistants) == 1
        assert assistants[0].markdown_text == "hello"
        assert app.query_one(ActiveOperation).renderable == "Idle"


@pytest.mark.asyncio
async def test_tui_tracks_repeated_tool_names_by_call_id() -> None:
    app = CodingApp()
    async with app.run_test(size=(80, 24)):
        run_id = uuid4()
        await app._render_progress(
            (
                RunProgress(
                    run_id=run_id,
                    kind=ProgressKind.TOOL_STARTED,
                    payload={
                        "tool_call_id": "call-1",
                        "tool": "read_file",
                        "arguments": {"path": "one.txt"},
                    },
                ),
                RunProgress(
                    run_id=run_id,
                    kind=ProgressKind.TOOL_STARTED,
                    payload={
                        "tool_call_id": "call-2",
                        "tool": "read_file",
                        "arguments": {"path": "two.txt"},
                    },
                ),
                RunProgress(
                    run_id=run_id,
                    kind=ProgressKind.TOOL_FINISHED,
                    payload={
                        "tool_call_id": "call-1",
                        "tool": "read_file",
                        "success": True,
                        "output": "one",
                    },
                ),
                RunProgress(
                    run_id=run_id,
                    kind=ProgressKind.TOOL_FINISHED,
                    payload={
                        "tool_call_id": "call-2",
                        "tool": "read_file",
                        "success": True,
                        "output": "two",
                    },
                ),
            )
        )
        details = [item.display_text for item in app.query(DetailMessage)]
        assert len(details) == 2
        assert any("one" in item for item in details)
        assert any("two" in item for item in details)


@pytest.mark.asyncio
async def test_tui_pause_is_idempotent_and_reports_redacted_error() -> None:
    fake = FakeUiServices()
    app = CodingApp(controller=_controller(fake))
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("pause")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if fake.execution_started.is_set():
                break
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert len(fake.pause_calls) == 1

        composer.load_text("error")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if app.query(DetailMessage):
                break
        errors = [item.display_text for item in app.query(DetailMessage)]
        assert any("[REDACTED]" in item for item in errors)
        assert all("topsecret" not in item and "sk-secretvalue" not in item for item in errors)


@pytest.mark.asyncio
async def test_tui_restart_resumes_paused_run_with_same_transcript_and_run_id() -> None:
    fake = FakeUiServices()
    first = CodingApp(controller=_controller(fake))
    async with first.run_test(size=(80, 24)) as pilot:
        composer = first.query_one(TaskComposer)
        composer.load_text("pause")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if fake.execution_started.is_set():
                break
        await pilot.press("escape")
        for _ in range(50):
            await pilot.pause(0.01)
            if fake.runs and fake.runs[-1].state is RunState.PAUSED:
                break

    run_id = fake.runs[-1].id
    second = CodingApp(controller=_controller(fake), resume="latest")
    async with second.run_test(size=(80, 24)) as pilot:
        for _ in range(50):
            await pilot.pause(0.01)
            assistants = list(second.query(AssistantMessage))
            if assistants and assistants[-1].markdown_text == "resumed":
                break

        assert len(fake.runs) == 1
        assert fake.runs[-1].id == run_id
        assert fake.runs[-1].state is RunState.COMPLETED
        assert list(second.query(AssistantMessage))[-1].markdown_text == "resumed"


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (60, 20)])
async def test_tui_approval_diff_is_scrollable_and_explicit(size: tuple[int, int]) -> None:
    fake = FakeUiServices()
    app = CodingApp(controller=_controller(fake))
    async with app.run_test(size=size) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("approval")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if app.query(ApprovalView):
                break
        approval = app.query_one(ApprovalView)
        assert approval.action_fingerprint
        assert approval.reason == "strict mode requires approval"
        assert approval.affected_paths == ("src/generated.py",)
        assert approval.virtual_size.height > approval.size.height
        assert composer.disabled
        assert "A approve" in approval.query_one(Static).renderable.plain


@pytest.mark.asyncio
async def test_tui_approval_keyboard_action_resumes_same_run() -> None:
    fake = FakeUiServices()
    app = CodingApp(controller=_controller(fake))
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("approval")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if app.query(ApprovalView):
                break
        approval_id = next(iter(fake.approvals))
        await pilot.press("a")
        for _ in range(50):
            await pilot.pause(0.01)
            if fake.approve_calls:
                break
        assert fake.approve_calls == [approval_id]
        assert not app.query(ApprovalView)
        assert not composer.disabled


@pytest.mark.asyncio
async def test_tui_resume_restores_pending_approval_view() -> None:
    fake = FakeUiServices()
    run = fake.submit(fake.session.id, "approval")
    request = ApprovalRequest(
        run_id=run.id,
        action=ToolCall(name="apply_patch", arguments={"patch": _long_patch()}),
        reason="strict mode requires approval",
    )
    fake.approvals[request.id] = request
    fake.runs[-1] = run.model_copy(
        update={"state": RunState.WAITING_APPROVAL, "updated_at": datetime.now(UTC)}
    )
    app = CodingApp(controller=_controller(fake), resume="latest")

    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(50):
            await pilot.pause(0.01)
            if app.query(ApprovalView):
                break

        approval = app.query_one(ApprovalView)
        assert approval.action_fingerprint
        assert app.query_one(TaskComposer).disabled


@pytest.mark.asyncio
async def test_tui_permissions_slash_command_changes_next_run_mode() -> None:
    fake = FakeUiServices()
    app = CodingApp(controller=_controller(fake))
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("/permissions strict")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if "strict" in str(app.query_one(StatusFooter).renderable):
                break
        assert app.permission_mode is PermissionMode.STRICT
        assert "strict" in str(app.query_one(StatusFooter).renderable)


@pytest.mark.asyncio
async def test_tui_permissions_slash_commands_use_application_rule_service() -> None:
    fake = FakeUiServices()
    rules = FakePermissionRules()
    services = SimpleNamespace(permission_rules=rules)
    app = CodingApp(controller=_controller(fake), services=services)

    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("/permissions allow read_file")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if rules.rules:
                break
        assert rules.rules == [
            PermissionRule(scope="tool", pattern="read_file", effect="allow")
        ]
        assert any(
            "Allowed tool: read_file" in str(widget.renderable)
            for widget in app.query_one(ConversationLog).query(Static)
        )

        composer.load_text("/permissions clear read_file")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if not rules.rules:
                break
        assert rules.rules == []
