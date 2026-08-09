# ruff: noqa: BLE001
"""Claude Code-like local Textual shell."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from coding613.application.validation import ValidationResult
from coding613.domain.actions import ToolCall
from coding613.domain.models import PermissionMode, RunState
from coding613.ports.progress import ProgressKind, RunProgress
from coding613.ports.tools import ToolResult

from .commands import ParsedCommand, SlashCommand
from .controller import TuiController
from .renderers import (
    ApprovalView,
    AssistantMessage,
    DetailMessage,
    render_approval,
    render_assistant,
    render_error,
    render_tool_call,
    render_tool_result,
    render_validation,
)
from .widgets import ActiveOperation, ConversationLog, StatusFooter, TaskComposer, UserMessage

if TYPE_CHECKING:
    from coding613.application.composition import LocalServices


class CodingApp(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "613 Coding"
    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("enter", "submit_task", "Submit", priority=True),
        Binding("ctrl+j", "insert_newline", "New line", show=False, priority=True),
        Binding("escape", "pause_run", "Pause", priority=True),
        Binding("ctrl+c", "confirm_exit", "Pause / exit", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("a", "approve_request", "Approve", show=False),
        Binding("r", "reject_request", "Reject", show=False),
    ]

    def __init__(
        self,
        *,
        services: LocalServices | None = None,
        controller: TuiController | None = None,
        initial_task: str | None = None,
        resume: str | None = None,
        permission_mode: PermissionMode = PermissionMode.BALANCED,
    ) -> None:
        super().__init__()
        self.services = services
        self.controller = controller
        if self.controller is None and services is not None:
            self.controller = TuiController(services.interactive, services.run_service)
        self.initial_task = initial_task
        self.resume = resume
        self.permission_mode = permission_mode
        self._drafts: dict[UUID, str] = {}
        self._assistants: dict[UUID, AssistantMessage] = {}
        self._entries: set[tuple[str, UUID]] = set()
        self._tool_widgets: dict[str, DetailMessage] = {}
        self._tool_calls: dict[str, ToolCall] = {}
        self._validation_widget: Static | None = None
        self._approval_id: UUID | None = None
        self._pending_user: UserMessage | None = None
        self._executing = False
        self._drain_timer: object | None = None

    def compose(self) -> ComposeResult:
        yield ConversationLog(id="conversation-log")
        yield ActiveOperation()
        yield TaskComposer(self.initial_task or "")
        yield StatusFooter()

    def on_mount(self) -> None:
        self.query_one(TaskComposer).focus()
        self._drain_timer = self.set_interval(0.05, self._drain_progress)
        if self.controller is not None:
            if self.resume is not None:
                self.run_worker(self._restore_session(), group="session")
            elif self.initial_task:
                self.run_worker(self._submit_message(self.initial_task), group="execution")

    def action_submit_task(self) -> None:
        if not self._executing and not self.query_one(TaskComposer).disabled:
            self.query_one(TaskComposer).submit()

    def action_insert_newline(self) -> None:
        self.query_one(TaskComposer).insert("\n")

    def action_pause_run(self) -> None:
        if self.controller is not None and self.controller.active_run_id is not None:
            self.run_worker(self._pause_run(), group="pause")
        else:
            self.query_one(ActiveOperation).update("Idle")

    def action_confirm_exit(self) -> None:
        self.query_one(StatusFooter).update("Press Ctrl+Q to exit; Esc resumes editing")

    async def action_quit(self) -> None:
        if self.controller is not None and self.controller.active_run_id is not None:
            await self._pause_run()
        self.exit()

    def on_task_composer_submitted(self, message: TaskComposer.Submitted) -> None:
        if self.controller is None or self._executing:
            return
        if message.text.startswith("/"):
            self.run_worker(self._handle_command(message.text), group="command")
            return
        self.run_worker(self._submit_message(message.text), group="execution", exclusive=True)

    async def _handle_command(self, text: str) -> None:
        try:
            command = SlashCommand.parse(text)
            await self._execute_command(command)
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))

    async def _execute_command(self, command: ParsedCommand) -> None:
        if self.controller is None:
            return
        log = self.query_one(ConversationLog)
        if command.name == "help":
            await log.mount(Static("/help /model /permissions /resume /runs /clear /quit"))
        elif command.name == "model":
            metadata = getattr(self.services, "llm_metadata", None)
            if metadata is None:
                await log.mount(Static("Model: not configured"))
            else:
                await log.mount(
                    Static(
                        f"Model: {metadata.model} | Provider: {metadata.provider} | URL: {metadata.base_url}"
                    )
                )
        elif command.name == "permissions":
            if command.arguments:
                self.permission_mode = PermissionMode(command.arguments[0])
            self.query_one(StatusFooter).update(
                f"613 Coding  |  {self.permission_mode.value}  |  ready"
            )
        elif command.name == "runs":
            snapshot = await self.controller.snapshot()
            lines = [f"{run.id}  {run.state.value}  {run.task}" for run in snapshot.runs]
            await log.mount(Static("\n".join(lines) or "No runs"))
        elif command.name == "resume":
            snapshot = await self.controller.resume(command.arguments[0])
            await self._render_snapshot(snapshot, clear=True)
        elif command.name == "clear":
            snapshot = await self.controller.clear()
            await self._render_snapshot(snapshot, clear=True)
        elif command.name == "quit":
            await self.action_quit()

    async def action_approve_request(self) -> None:
        await self._resolve_approval(approve=True)

    async def action_reject_request(self) -> None:
        await self._resolve_approval(approve=False)

    async def _submit_message(self, message: str) -> None:
        if self.controller is None:
            return
        self._executing = True
        composer = self.query_one(TaskComposer)
        composer.disabled = True
        composer.load_text("")
        pending = UserMessage(message)
        self._pending_user = pending
        await self.query_one(ConversationLog).mount(pending)
        self.query_one(ActiveOperation).update("Starting run")
        try:
            snapshot = await self.controller.submit(message, self._permission_mode)
            await self._render_snapshot(snapshot)
            self.controller.drain_progress()
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))
        finally:
            self._executing = False
            self._pending_user = None
            self._update_input_state()
            self.query_one(ActiveOperation).update("Idle")

    async def _restore_session(self) -> None:
        if self.controller is None:
            return
        self._executing = True
        self._update_input_state()
        self.query_one(ActiveOperation).update("Restoring session")
        try:
            snapshot = await self.controller.resume(self.resume or "latest")
            await self._render_snapshot(snapshot, clear=True)
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))
        finally:
            self._executing = False
            self._update_input_state()
            if self._approval_id is None:
                self.query_one(ActiveOperation).update("Idle")

    async def _pause_run(self) -> None:
        if self.controller is None:
            return
        self.query_one(ActiveOperation).update("Pause requested")
        try:
            await self.controller.pause()
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))

    async def _resolve_approval(self, *, approve: bool) -> None:
        if self.controller is None or self._approval_id is None:
            return
        self._executing = True
        try:
            snapshot = (
                await self.controller.approve(self._approval_id)
                if approve
                else await self.controller.reject(self._approval_id)
            )
            if snapshot is not None:
                await self._render_snapshot(snapshot)
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))
        finally:
            self._executing = False
            self._update_input_state()

    def _drain_progress(self) -> None:
        if self.controller is None:
            return
        updates = self.controller.drain_progress()
        if updates:
            self.run_worker(self._render_progress(updates), group="render")

    async def _render_progress(self, updates: tuple[RunProgress, ...]) -> None:
        log = self.query_one(ConversationLog)
        for update in updates:
            if update.kind is ProgressKind.TEXT_DELTA:
                draft = self._drafts.get(update.run_id, "") + update.text
                self._drafts[update.run_id] = draft
                assistant_widget = self._assistants.get(update.run_id)
                if assistant_widget is None:
                    assistant_widget = render_assistant(draft)
                    self._assistants[update.run_id] = assistant_widget
                    await log.mount(assistant_widget)
                else:
                    assistant_widget.replace(draft)
                self.query_one(ActiveOperation).update("Receiving response")
            elif update.kind is ProgressKind.STATE:
                state = update.payload.get("to", update.text) or "working"
                self.query_one(ActiveOperation).update(str(state))
            elif update.kind is ProgressKind.TOOL_STARTED:
                name = str(update.payload.get("tool", "tool"))
                tool_widget = render_tool_call(
                    ToolCall(name=name, arguments=dict(update.payload.get("arguments", {})))
                )
                self._tool_widgets[name] = tool_widget
                self._tool_calls[name] = ToolCall(
                    name=name, arguments=dict(update.payload.get("arguments", {}))
                )
                await log.mount(tool_widget)
                self.query_one(ActiveOperation).update(f"Running {name}")
            elif update.kind is ProgressKind.TOOL_FINISHED:
                name = str(update.payload.get("tool", "tool"))
                finished_widget = self._tool_widgets.get(name)
                if finished_widget is not None:
                    success = bool(update.payload.get("success", False))
                    call = self._tool_calls.get(
                        name, ToolCall(name=name, arguments={})
                    )
                    result = render_tool_result(
                        ToolResult(
                            call=call,
                            success=success,
                            output=str(update.payload.get("output", "")),
                            error=str(update.payload.get("error", "")) or None,
                            changed_files=tuple(
                                str(path)
                                for path in update.payload.get("changed_files", ())
                            ),
                        )
                    )
                    finished_widget.display_text = result.display_text
                    finished_widget.update(result.renderable)
            elif update.kind is ProgressKind.VALIDATION_STARTED:
                self._validation_widget = Static(
                    "Validation started", classes="conversation-entry"
                )
                await log.mount(self._validation_widget)
            elif update.kind is ProgressKind.VALIDATION_FINISHED:
                result_data = update.payload.get("result")
                if isinstance(result_data, dict) and self._validation_widget is not None:
                    result = render_validation(ValidationResult.model_validate(result_data))
                    self._validation_widget.update(result.renderable)
                else:
                    status = "passed" if update.payload.get("success") else "failed"
                    await log.mount(
                        Static(f"Validation {status}", classes="conversation-entry")
                    )
            elif update.kind is ProgressKind.ERROR:
                await log.mount(render_error(update.text or json.dumps(dict(update.payload))))
        log.scroll_end(animate=False)

    async def _render_snapshot(self, snapshot: Any, *, clear: bool = False) -> None:
        log = self.query_one(ConversationLog)
        if clear:
            await log.remove_children()
            self._entries.clear()
            self._assistants.clear()
            self._drafts.clear()
        for entry in snapshot.transcript:
            key = (entry.role, entry.run_id)
            if key in self._entries:
                if entry.role == "assistant" and entry.run_id in self._assistants:
                    self._assistants[entry.run_id].replace(entry.text)
                continue
            if entry.role == "user" and self._pending_user is not None:
                self._entries.add(key)
                continue
            elif entry.role == "assistant" and entry.run_id in self._assistants:
                self._assistants[entry.run_id].replace(entry.text)
                self._entries.add(key)
                continue
            elif entry.role == "assistant":
                assistant_widget = render_assistant(entry.text)
                self._assistants[entry.run_id] = assistant_widget
                await log.mount(assistant_widget)
            else:
                user_widget = UserMessage(entry.text)
                await log.mount(user_widget)
            self._entries.add(key)
        for approval_view in list(log.query(ApprovalView)):
            await approval_view.remove()
        self._approval_id = None
        if snapshot.active_run is not None and snapshot.active_run.state is RunState.WAITING_APPROVAL:
            summary = self.controller.last_summary if self.controller is not None else None
            if summary is not None and summary.approvals:
                self._approval_id = summary.approvals[-1]
                controller = self.controller
                assert controller is not None
                request = await controller.get_approval(self._approval_id)
                await log.mount(render_approval(request))
                self.query_one(ActiveOperation).update("Awaiting approval")
        log.scroll_end(animate=False)
        self._update_input_state()

    def _update_input_state(self) -> None:
        composer = self.query_one(TaskComposer)
        awaiting = self._approval_id is not None
        composer.disabled = self._executing or awaiting
        if not composer.disabled:
            composer.focus()

    @property
    def _permission_mode(self) -> PermissionMode:
        return self.permission_mode
