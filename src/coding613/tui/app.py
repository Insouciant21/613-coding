# ruff: noqa: BLE001
"""Claude Code-like local Textual shell."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from coding613.application.validation import ValidationResult
from coding613.domain.actions import ToolCall
from coding613.domain.conversation import RunOptions
from coding613.domain.models import PermissionMode, RunState
from coding613.ports.progress import ProgressKind, RunProgress
from coding613.ports.tools import ToolResult

from .commands import CommandCatalog, ParsedCommand
from .controller import TuiController
from .renderers import (
    ApprovalView,
    AssistantMessage,
    DetailMessage,
    render_approval,
    render_assistant,
    render_error,
    render_run_summary,
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
        Binding("up", "history_previous", "Previous prompt", show=False, priority=True),
        Binding("down", "history_next", "Next prompt", show=False, priority=True),
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
        continue_latest: bool = False,
        permission_mode: PermissionMode = PermissionMode.BALANCED,
        options: RunOptions | None = None,
    ) -> None:
        super().__init__()
        self.services = services
        self.controller = controller
        if self.controller is None and services is not None:
            self.controller = TuiController(
                services.interactive,
                services.run_service,
                context=getattr(services, "context", None),
                diagnostics=getattr(services, "diagnostics", None),
                project_id=services.run_service.project.id,
            )
        self.initial_task = initial_task
        self.resume = resume
        self.continue_latest = continue_latest
        self.permission_mode = permission_mode
        self.options = options
        self.command_catalog = CommandCatalog.default()
        self._drafts: dict[UUID, str] = {}
        self._assistants: dict[UUID, AssistantMessage] = {}
        self._entries: set[tuple[str, UUID]] = set()
        self._tool_widgets: dict[str, DetailMessage] = {}
        self._tool_calls: dict[str, ToolCall] = {}
        self._tool_keys_by_name: dict[str, list[str]] = {}
        self._summary_widgets: dict[UUID, DetailMessage] = {}
        self._validation_widget: Static | None = None
        self._approval_id: UUID | None = None
        self._current_session_id: UUID | None = None
        self._pending_user: UserMessage | None = None
        self._executing = False
        self._operation_started_at: float | None = None
        self._drain_timer: object | None = None

    def compose(self) -> ComposeResult:
        yield ConversationLog(id="conversation-log")
        yield ActiveOperation()
        yield TaskComposer(self.initial_task or "")
        yield StatusFooter()

    def on_mount(self) -> None:
        self.query_one(TaskComposer).focus()
        self._update_footer()
        self._drain_timer = self.set_interval(0.05, self._drain_progress)
        if self.controller is not None:
            if self.resume is not None or self.continue_latest:
                self.run_worker(
                    self._restore_session(submit_after=self.initial_task), group="session"
                )
            elif self.initial_task:
                self.run_worker(self._submit_message(self.initial_task), group="execution")

    def action_submit_task(self) -> None:
        if not self._executing and not self.query_one(TaskComposer).disabled:
            self.query_one(TaskComposer).submit()

    def action_insert_newline(self) -> None:
        self.query_one(TaskComposer).insert("\n")

    def action_history_previous(self) -> None:
        self.query_one(TaskComposer).history_previous()

    def action_history_next(self) -> None:
        self.query_one(TaskComposer).history_next()

    def action_pause_run(self) -> None:
        if self.controller is not None and self.controller.active_run_id is not None:
            self.run_worker(self._pause_run(), group="pause")
        else:
            self.query_one(ActiveOperation).update("Idle")

    def action_confirm_exit(self) -> None:
        if self.controller is not None and self.controller.active_run_id is not None:
            self.run_worker(self._pause_run(), group="pause")
            return
        self.query_one(StatusFooter).update("Press Ctrl+Q to exit; Esc resumes editing")

    async def action_quit(self) -> None:
        if self.controller is not None and self.controller.active_run_id is not None:
            await self._pause_run()
        self.exit()

    def on_task_composer_submitted(self, message: TaskComposer.Submitted) -> None:
        if self.controller is None or self._executing:
            return
        if message.text.startswith("//"):
            self.run_worker(
                self._submit_message(message.text[1:]),
                group="execution",
                exclusive=True,
            )
            return
        if message.text.startswith("/"):
            self.run_worker(self._handle_command(message.text), group="command")
            return
        self.run_worker(self._submit_message(message.text), group="execution", exclusive=True)

    async def _handle_command(self, text: str) -> None:
        try:
            command = self.command_catalog.parse(text)
            await self._execute_command(command)
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))

    async def _execute_command(self, command: ParsedCommand) -> None:
        if self.controller is None:
            return
        log = self.query_one(ConversationLog)
        if command.name == "help":
            await log.mount(Static(self.command_catalog.help(command.arguments[0] if command.arguments else None)))
        elif command.name == "model":
            metadata = getattr(self.services, "llm_metadata", None)
            if command.arguments:
                if self.options is None:
                    from coding613.domain.conversation import RunOptions

                    self.options = RunOptions(model=command.arguments[0])
                else:
                    self.options = self.options.model_copy(update={"model": command.arguments[0]})
                self._update_footer()
                await log.mount(Static(f"Model selected: {command.arguments[0]}"))
            elif metadata is None:
                await log.mount(Static("Model: not configured"))
            else:
                await log.mount(
                    Static(
                        f"Model: {metadata.model} | Provider: {metadata.provider} | URL: {metadata.base_url}"
                    )
                )
        elif command.name == "permissions":
            if command.arguments and command.arguments[0] in {
                "strict",
                "balanced",
                "autonomous",
            }:
                self.permission_mode = PermissionMode(command.arguments[0])
                self._update_footer()
            else:
                service = getattr(self.services, "permission_rules", None)
                if service is None:
                    await log.mount(Static("Permission rules are unavailable"))
                elif not command.arguments or command.arguments[0] == "list":
                    rules = await asyncio.to_thread(service.list_rules)
                    lines = [
                        f"{rule.effect} {rule.scope}:{rule.pattern}" for rule in rules
                    ]
                    await log.mount(
                        Static(
                            f"Mode: {self.permission_mode.value}\n"
                            + ("\n".join(lines) or "No project permission rules")
                        )
                    )
                else:
                    action, tool_name = command.arguments
                    if action == "allow":
                        rule = await asyncio.to_thread(service.allow_tool, tool_name)
                        message = f"Allowed tool: {rule.pattern}"
                    elif action == "deny":
                        rule = await asyncio.to_thread(service.deny_tool, tool_name)
                        message = f"Denied tool: {rule.pattern}"
                    else:
                        await asyncio.to_thread(service.clear_tool, tool_name)
                        message = f"Cleared tool rule: {tool_name}"
                    await log.mount(Static(message))
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
        elif command.name == "status":
            summary = self.controller.last_summary
            status = summary.status.value if summary is not None else "idle"
            approval = "pending" if summary is not None and summary.approvals else "none"
            validation = len(summary.validation_evidence) if summary is not None else 0
            blockers = (
                ",".join(item.value for item in summary.completion_blockers)
                if summary is not None and summary.completion_blockers
                else "none"
            )
            usage = summary.resource_usage.model_dump(mode="json") if summary is not None else {}
            await log.mount(
                Static(
                    f"Status: {status}; active_run={self.controller.active_run_id or 'none'}; "
                    f"approval={approval}; validation={validation}; feedback={blockers}; "
                    f"budget={usage}"
                )
            )
        elif command.name == "cost":
            summary = self.controller.last_summary
            if summary is None:
                await log.mount(Static("Cost: no run yet"))
            else:
                await log.mount(Static(f"Resource usage: {summary.resource_usage.model_dump(mode='json')}"))
        elif command.name in {"context", "compact", "doctor"}:
            method_name = {
                "context": "context_report",
                "compact": "compact",
                "doctor": "diagnostics",
            }[command.name]
            method = getattr(self.controller, method_name, None)
            if method is None:
                await log.mount(Static(f"/{command.name} is not available in this service bundle"))
            else:
                result = await method()
                display = (
                    result.model_dump_json()
                    if hasattr(result, "model_dump_json")
                    else str(result)
                )
                await log.mount(Static(display))
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
        self._operation_started_at = time.monotonic()
        composer = self.query_one(TaskComposer)
        composer.disabled = True
        composer.load_text("")
        pending = UserMessage(message)
        self._pending_user = pending
        await self.query_one(ConversationLog).mount(pending)
        self._set_active_operation("Starting run")
        try:
            snapshot = await self.controller.submit(
                message,
                self._permission_mode,
                self.options,
            )
            await self._render_snapshot(snapshot)
            self.controller.drain_progress()
            if self.controller.last_summary is not None:
                await self._render_summary(self.controller.last_summary)
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))
        finally:
            self._executing = False
            self._pending_user = None
            self._update_input_state()
            self._set_active_operation("Idle", reset=True)

    async def _restore_session(self, *, submit_after: str | None = None) -> None:
        if self.controller is None:
            return
        self._executing = True
        self._operation_started_at = time.monotonic()
        self._update_input_state()
        self._set_active_operation("Restoring session")
        try:
            snapshot = await self.controller.resume(self.resume or "latest")
            await self._render_snapshot(snapshot, clear=True)
            if self.controller.last_summary is not None:
                await self._render_summary(self.controller.last_summary)
            if submit_after and self._approval_id is None:
                await self._submit_message(submit_after)
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))
        finally:
            self._executing = False
            self._update_input_state()
            if self._approval_id is None:
                self._set_active_operation("Idle", reset=True)

    async def _pause_run(self) -> None:
        if self.controller is None:
            return
        self._set_active_operation("Pause requested")
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
                if self.controller.last_summary is not None:
                    await self._render_summary(self.controller.last_summary)
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
                self._set_active_operation("Receiving response")
            elif update.kind is ProgressKind.STATE:
                state = update.payload.get("to", update.text) or "working"
                self._set_active_operation(str(state))
            elif update.kind is ProgressKind.TOOL_STARTED:
                name = str(update.payload.get("tool", "tool"))
                key = str(update.payload.get("tool_call_id") or f"{name}:{len(self._tool_widgets)}")
                tool_widget = render_tool_call(
                    ToolCall(name=name, arguments=dict(update.payload.get("arguments", {})))
                )
                self._tool_widgets[key] = tool_widget
                self._tool_calls[key] = ToolCall(
                    name=name, arguments=dict(update.payload.get("arguments", {}))
                )
                self._tool_keys_by_name.setdefault(name, []).append(key)
                await log.mount(tool_widget)
                self._set_active_operation(f"Running {name}")
            elif update.kind is ProgressKind.TOOL_FINISHED:
                name = str(update.payload.get("tool", "tool"))
                key = str(update.payload.get("tool_call_id", ""))
                if not key:
                    key = self._tool_keys_by_name.get(name, [""])[-1]
                finished_widget = self._tool_widgets.get(key)
                if finished_widget is not None:
                    success = bool(update.payload.get("success", False))
                    call = self._tool_calls.get(
                        key, ToolCall(name=name, arguments={})
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
                    # Progress payloads are JSON-safe and therefore carry enum
                    # values as strings; opt out of the strict domain parser at
                    # this display boundary and keep validation authoritative in
                    # the application loop.
                    result = render_validation(
                        ValidationResult.model_validate(result_data, strict=False)
                    )
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
        self._current_session_id = snapshot.session.id
        if clear:
            await log.remove_children()
            self._entries.clear()
            self._assistants.clear()
            self._drafts.clear()
            self._tool_widgets.clear()
            self._tool_calls.clear()
            self._tool_keys_by_name.clear()
            self._summary_widgets.clear()
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
        composer = self.query_one(TaskComposer)
        composer.set_history(
            tuple(entry.text for entry in snapshot.transcript if entry.role == "user")
        )
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
        self._update_footer()

    def _update_footer(self) -> None:
        try:
            footer = self.query_one(StatusFooter)
        except Exception:
            return
        project = getattr(self.services, "run_service", None)
        project = getattr(project, "project", None)
        root = getattr(project, "canonical_root", None)
        repository = getattr(root, "name", None) or (str(root) if root else "unknown")
        metadata = getattr(self.services, "llm_metadata", None)
        model = self.options.model if self.options is not None else None
        model = model or getattr(metadata, "model", None) or "default"
        provider = getattr(metadata, "provider", None) or "unconfigured"
        session = str(self._current_session_id)[:8] if self._current_session_id else "new"
        footer.update(
            "613 Coding"
            f" | repo={repository}"
            f" | session={session}"
            f" | model={model}"
            f" | mode={self.permission_mode.value}"
            f" | provider={provider}"
        )

    async def _render_summary(self, summary: Any) -> None:
        if not hasattr(summary, "run_id"):
            return
        widget = render_run_summary(summary)
        existing = self._summary_widgets.get(summary.run_id)
        if existing is None:
            self._summary_widgets[summary.run_id] = widget
            await self.query_one(ConversationLog).mount(widget)
        else:
            existing.display_text = widget.display_text
            existing.update(widget.renderable)
        self.query_one(ConversationLog).scroll_end(animate=False)

    def _update_input_state(self) -> None:
        composer = self.query_one(TaskComposer)
        awaiting = self._approval_id is not None
        composer.disabled = self._executing or awaiting
        if not composer.disabled:
            composer.focus()

    def _set_active_operation(self, label: str, *, reset: bool = False) -> None:
        if reset:
            self._operation_started_at = None
            self.query_one(ActiveOperation).update(label)
            return
        elapsed = (
            time.monotonic() - self._operation_started_at
            if self._operation_started_at is not None
            else 0.0
        )
        self.query_one(ActiveOperation).update(f"{label} | elapsed={elapsed:.1f}s")

    @property
    def _permission_mode(self) -> PermissionMode:
        return self.permission_mode
