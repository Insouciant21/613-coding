from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from textual.widgets import Static

from coding613.application.credentials import CredentialStatus
from coding613.application.interactive import InteractiveSnapshot, TranscriptEntry
from coding613.application.progress import CancellationToken
from coding613.application.user_configuration import ProviderProfile
from coding613.config import LLMConfig
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
from coding613.tui.widgets import (
    ActiveOperation,
    CommandHints,
    ConfigMenu,
    ConversationLog,
    StatusFooter,
    TaskComposer,
    UsageHints,
)


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
async def test_tui_shows_slash_command_hints_and_cycles_with_tab_and_arrows() -> None:
    app = CodingApp()
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        hints = app.query_one(CommandHints)

        composer.load_text("/co")
        await pilot.pause()
        assert hints.display
        assert "/config" in str(hints.renderable)
        assert "/compact" in str(hints.renderable)

        await pilot.press("tab")
        assert composer.text == "/config"
        await pilot.press("tab")
        assert composer.text == "/compact"
        await pilot.press("up")
        assert composer.text == "/config"

        composer.load_text("/config ")
        await pilot.pause()
        assert not hints.display


@pytest.mark.asyncio
async def test_tui_keeps_persistent_usage_hints_visible() -> None:
    app = CodingApp()
    async with app.run_test(size=(80, 24)):
        usage = app.query_one(UsageHints)
        text = str(usage.renderable)
        assert "Enter send" in text
        assert "Ctrl+J newline" in text
        assert "Ctrl+Q exit" in text
        assert "Ctrl+T expand tool" in text
        assert "/help" in text


@pytest.mark.asyncio
async def test_tui_renders_markdown_links_without_corrupting_textual_style_metadata() -> None:
    app = CodingApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await app._render_progress(
            (
                RunProgress(
                    run_id=uuid4(),
                    kind=ProgressKind.TEXT_DELTA,
                    text="Read [README](https://example.com) and `config.py`.",
                ),
            )
        )
        await pilot.pause()


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
async def test_tui_double_slash_escapes_a_prompt_starting_with_slash() -> None:
    fake = FakeUiServices()
    app = CodingApp(controller=_controller(fake))
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("//status")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if fake.runs and fake.runs[-1].state is RunState.COMPLETED:
                break

        assert [run.task for run in fake.runs] == ["/status"]


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
async def test_tui_composer_has_no_hover_tooltip_and_bottom_rows_fit() -> None:
    app = CodingApp()
    async with app.run_test(size=(80, 24)):
        composer = app.query_one(TaskComposer)
        usage = app.query_one(UsageHints)
        footer = app.query_one(StatusFooter)

        assert composer.tooltip is None
        assert usage.region.bottom <= app.size.height
        assert footer.region.bottom <= app.size.height
        assert usage.region.y >= composer.region.bottom
        assert footer.region.y >= usage.region.bottom


@pytest.mark.asyncio
async def test_tui_replaces_stale_text_only_turn_before_rendering_next_turn() -> None:
    app = CodingApp()
    run_id = uuid4()
    async with app.run_test(size=(80, 24)):
        await app._render_progress(
            (
                RunProgress(
                    run_id=run_id,
                    kind=ProgressKind.STATE,
                    text=RunState.WAITING_MODEL.value,
                    payload={"to": RunState.WAITING_MODEL.value},
                ),
                RunProgress(
                    run_id=run_id,
                    kind=ProgressKind.TEXT_DELTA,
                    text="I will inspect the repository.",
                ),
                RunProgress(
                    run_id=run_id,
                    kind=ProgressKind.STATE,
                    text=RunState.WAITING_MODEL.value,
                    payload={"to": RunState.WAITING_MODEL.value},
                ),
                RunProgress(
                    run_id=run_id,
                    kind=ProgressKind.TEXT_DELTA,
                    text="No action was produced.",
                ),
            )
        )

        assistants = list(app.query(AssistantMessage))
        assert len(assistants) == 1
        assert assistants[0].markdown_text == "No action was produced."


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
async def test_tui_renders_terminal_summary_with_feedback_and_resource_usage() -> None:
    fake = FakeUiServices()
    app = CodingApp(controller=_controller(fake))
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("repair")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if any("Run: completed" in item.display_text for item in app.query(DetailMessage)):
                break

        summaries = [item.display_text for item in app.query(DetailMessage)]
        assert any("Run: completed" in item for item in summaries)
        assert any("resource_usage=" in item for item in summaries)


@pytest.mark.asyncio
async def test_tui_status_footer_shows_repository_session_model_and_provider() -> None:
    fake = FakeUiServices()
    services = SimpleNamespace(
        run_service=SimpleNamespace(
            project=SimpleNamespace(canonical_root=Path("/workspace/demo")),
        ),
        llm_metadata=SimpleNamespace(
            model="gpt-test", provider="openai", base_url="https://example.invalid"
        ),
    )
    app = CodingApp(
        controller=_controller(fake),
        services=services,
        permission_mode=PermissionMode.STRICT,
    )
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("repair")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if fake.runs and fake.runs[-1].state is RunState.COMPLETED:
                break

        footer = str(app.query_one(StatusFooter).renderable)
        assert "repo=demo" in footer
        assert "session=" in footer
        assert "model=gpt-test" in footer
        assert "provider=openai" in footer
        assert "strict" in footer


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
async def test_tui_ctrl_t_expands_the_latest_large_tool_result() -> None:
    app = CodingApp()
    output = "\n".join(f"line-{index}" for index in range(400))
    async with app.run_test(size=(80, 24)) as pilot:
        await app._render_progress(
            (
                RunProgress(
                    run_id=uuid4(),
                    kind=ProgressKind.TOOL_STARTED,
                    payload={
                        "tool_call_id": "call-read",
                        "tool": "read_file",
                        "arguments": {"path": "src/app.py"},
                    },
                ),
                RunProgress(
                    run_id=uuid4(),
                    kind=ProgressKind.TOOL_FINISHED,
                    payload={
                        "tool_call_id": "call-read",
                        "tool": "read_file",
                        "success": True,
                        "output": output,
                    },
                ),
            )
        )
        widget = app.query_one(DetailMessage)
        assert widget.expandable
        assert "line-399" not in widget.display_text

        await pilot.press("ctrl+t")
        assert "line-399" in widget.display_text

        await pilot.press("ctrl+t")
        assert "line-399" not in widget.display_text


@pytest.mark.asyncio
async def test_tui_active_operation_includes_elapsed_time() -> None:
    app = CodingApp()
    async with app.run_test(size=(80, 24)):
        app._operation_started_at = time.monotonic() - 1.0
        await app._render_progress(
            (
                RunProgress(
                    run_id=uuid4(),
                    kind=ProgressKind.STATE,
                    text="waiting_model",
                    payload={"to": "waiting_model"},
                ),
            )
        )

        assert "elapsed=" in str(app.query_one(ActiveOperation).renderable)


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
async def test_tui_ctrl_c_requests_pause_before_exit() -> None:
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

        await pilot.press("ctrl+c")
        for _ in range(50):
            await pilot.pause(0.01)
            if fake.pause_calls:
                break

        assert fake.pause_calls == [fake.runs[-1].id]


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
async def test_tui_continue_with_prompt_restores_latest_session_then_submits_follow_up() -> None:
    fake = FakeUiServices()
    first = fake.submit(fake.session.id, "first")
    fake.runs[-1] = first.model_copy(
        update={
            "state": RunState.COMPLETED,
            "stop_reason": StopReason.SUCCESS,
            "updated_at": datetime.now(UTC),
        }
    )
    fake.transcript.append(TranscriptEntry(role="assistant", text="hello", run_id=first.id))

    app = CodingApp(controller=_controller(fake), initial_task="follow-up", resume="latest")
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(50):
            await pilot.pause(0.01)
            if len(fake.runs) == 2 and fake.runs[-1].state is RunState.COMPLETED:
                break

        assert [run.task for run in fake.runs] == ["first", "follow-up"]


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
async def test_tui_status_command_reports_approval_and_budget_state() -> None:
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

        await app._handle_command("/status")
        for _ in range(50):
            await pilot.pause(0.01)
            if any("approval=" in str(item.renderable) for item in app.query(Static)):
                break

        texts = [str(item.renderable) for item in app.query(Static)]
        assert any("approval=pending" in text for text in texts)
        assert any("budget=" in text for text in texts)


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
async def test_tui_provider_command_switches_user_profile() -> None:
    fake = FakeUiServices()

    class FakeUserConfiguration:
        def __init__(self) -> None:
            self.active = "openai"

        def profiles(self) -> tuple[ProviderProfile, ...]:
            return tuple(
                ProviderProfile(
                    name=name,
                    config=LLMConfig(model=f"{name}-model", credential=f"{name}-key"),
                    active=name == self.active,
                    credential=CredentialStatus(
                        provider=f"{name}-key", configured=False, source="none"
                    ),
                )
                for name in ("deepseek", "openai")
            )

    user = FakeUserConfiguration()

    def switch(name: str) -> SimpleNamespace:
        user.active = name
        return SimpleNamespace(active_provider=name)

    app = CodingApp(
        controller=_controller(fake),
        services=SimpleNamespace(
            user_configuration=user,
            switch_provider=switch,
            llm_metadata=LLMConfig(model="openai-model"),
        ),
    )
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("/provider use deepseek")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if "Active provider: deepseek" in "\n".join(
                str(widget.renderable) for widget in app.query_one(ConversationLog).query(Static)
            ):
                break

        assert user.active == "deepseek"
        assert any(
            "Active provider: deepseek" in str(widget.renderable)
            for widget in app.query_one(ConversationLog).query(Static)
        )


@pytest.mark.asyncio
async def test_tui_config_slash_command_persists_and_refreshes_configuration() -> None:
    fake = FakeUiServices()
    calls: list[tuple[str, str]] = []

    class FakeConfiguration:
        def summary(self) -> str:
            return "mode=balanced"

        def set_value(self, key: str, value: str) -> SimpleNamespace:
            calls.append((key, value))
            return SimpleNamespace(permission_mode=PermissionMode.AUTONOMOUS)

    app = CodingApp(
        controller=_controller(fake),
        services=SimpleNamespace(configuration=FakeConfiguration()),
    )
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("/config set mode autonomous")
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.01)
            if calls:
                break

        assert calls == [("mode", "autonomous")]
        assert app.permission_mode is PermissionMode.AUTONOMOUS
        assert any(
            "Configuration updated: mode" in str(widget.renderable)
            for widget in app.query_one(ConversationLog).query(Static)
        )


@pytest.mark.asyncio
async def test_tui_config_without_arguments_opens_selectable_menu() -> None:
    fake = FakeUiServices()

    class FakeConfiguration:
        def summary(self) -> str:
            return "mode=balanced"

        def set_value(self, key: str, value: str) -> SimpleNamespace:
            del key
            return SimpleNamespace(permission_mode=PermissionMode(value))

    app = CodingApp(
        controller=_controller(fake),
        services=SimpleNamespace(
            configuration=FakeConfiguration(),
            reload_configuration=lambda: SimpleNamespace(
                permission_mode=PermissionMode.BALANCED
            ),
        ),
    )
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("/config")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.01)
            if app.query(ConfigMenu):
                break
        menu = app.query_one(ConfigMenu)
        assert menu.options[1].prompt == "Permission mode: strict"
        await pilot.press("down", "enter")
        await pilot.pause()
        assert not app.query(ConfigMenu)


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
