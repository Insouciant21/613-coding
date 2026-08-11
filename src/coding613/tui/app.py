# ruff: noqa: BLE001
"""Claude Code-like local Textual shell."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast
from uuid import UUID

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static, TextArea
from textual.widgets.option_list import Option

from coding613.application.validation import ValidationResult
from coding613.config import LLMConfig
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
from .widgets import (
    ActiveOperation,
    CommandHints,
    ConfigMenu,
    ConversationLog,
    ProviderEditorScreen,
    ProviderKeyScreen,
    StatusFooter,
    TaskComposer,
    UsageHints,
    UserMessage,
)

_REASONING_LEVEL_SUGGESTIONS = ("low", "med", "medium", "high", "xhigh", "max")


def _reasoning_levels(current: str) -> tuple[str, ...]:
    """Return common provider levels while retaining any user-defined value."""

    return tuple(dict.fromkeys((*_REASONING_LEVEL_SUGGESTIONS, current)))


if TYPE_CHECKING:
    from coding613.application.composition import LocalServices


class CodingApp(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "613 Coding"
    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("enter", "submit_task", "Submit", priority=True),
        Binding("tab", "complete_command", "Complete command", show=False, priority=True),
        Binding("ctrl+j", "insert_newline", "New line", show=False, priority=True),
        Binding("ctrl+t", "toggle_tool_output", "Expand tool output", show=False, priority=True),
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
        self._last_tool_widget: DetailMessage | None = None
        self._summary_widgets: dict[UUID, DetailMessage] = {}
        self._validation_widget: DetailMessage | None = None
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
        yield CommandHints()
        yield UsageHints()
        yield StatusFooter()

    def on_mount(self) -> None:
        self.query_one(TaskComposer).focus()
        self._update_command_hints()
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
        if isinstance(self.focused, ConfigMenu):
            self.focused.action_select()
            return
        if not self._executing and not self.query_one(TaskComposer).disabled:
            self.query_one(TaskComposer).submit()

    def action_insert_newline(self) -> None:
        self.query_one(TaskComposer).insert("\n")

    def action_complete_command(self) -> None:
        self.query_one(TaskComposer).cycle_completion()

    def action_toggle_tool_output(self) -> None:
        if self._last_tool_widget is not None:
            self._last_tool_widget.toggle_expanded()

    def action_history_previous(self) -> None:
        if isinstance(self.focused, ConfigMenu):
            self.focused.action_cursor_up()
            return
        composer = self.query_one(TaskComposer)
        if not composer.cycle_completion(-1):
            composer.history_previous()

    def action_history_next(self) -> None:
        if isinstance(self.focused, ConfigMenu):
            self.focused.action_cursor_down()
            return
        composer = self.query_one(TaskComposer)
        if not composer.cycle_completion(1):
            composer.history_next()

    def on_text_area_changed(self, message: TextArea.Changed) -> None:
        if isinstance(message.text_area, TaskComposer):
            self._update_command_hints()

    def action_pause_run(self) -> None:
        if isinstance(self.focused, ConfigMenu):
            self.run_worker(self._close_config_menu(), group="config-menu")
            return
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
            elif getattr(self.services, "user_configuration", None) is not None:
                await self._show_model_menu()
            elif metadata is None:
                await log.mount(Static("Model: not configured"))
            else:
                await log.mount(
                    Static(
                        f"Model: {metadata.model} | Provider: {metadata.provider} | URL: {metadata.base_url}"
                    )
                )
        elif command.name == "provider":
            configuration = getattr(self.services, "user_configuration", None)
            if configuration is None:
                await log.mount(Static("User provider configuration is unavailable"))
            elif not command.arguments:
                await self._show_provider_menu()
            elif command.arguments[0] == "add":
                await self._open_provider_editor()
            elif command.arguments[0] == "list":
                profiles = await asyncio.to_thread(configuration.profiles)
                lines = [
                    f"{'*' if profile.active else ' '} {profile.name} | "
                    f"{profile.config.api} | {profile.config.model} | {profile.config.base_url} | "
                    f"key={profile.credential.source if profile.credential.configured else 'missing'}"
                    for profile in profiles
                ]
                await log.mount(Static("\n".join(lines) or "No provider profiles configured"))
            elif command.arguments[0] == "edit":
                await self._open_provider_editor(command.arguments[1])
            elif command.arguments[0] in {"remove", "delete"}:
                await self._show_provider_delete_confirmation(command.arguments[1])
            elif command.arguments[0] == "key":
                await self._open_provider_key_editor(command.arguments[1])
            elif command.arguments[0] == "clear-key":
                await self._show_provider_key_clear_confirmation(command.arguments[1])
            elif command.arguments[0] == "show":
                name = command.arguments[1]
                profile = next(
                    (item for item in await asyncio.to_thread(configuration.profiles) if item.name == name),
                    None,
                )
                if profile is None:
                    await log.mount(Static(f"Provider is not configured: {name}"))
                else:
                    await log.mount(
                        Static(
                            f"Provider: {profile.name}\n"
                            f"Active: {profile.active}\n"
                            f"API: {profile.config.api}\n"
                            f"Model: {profile.config.model}\n"
                            f"Base URL: {profile.config.base_url}\n"
                            f"Key: {profile.credential.source if profile.credential.configured else 'missing'}"
                        )
                    )
            else:
                switch_provider = getattr(self.services, "switch_provider", None)
                if not callable(switch_provider):
                    await log.mount(Static("Provider switching is unavailable"))
                else:
                    name = command.arguments[1]
                    updated = await asyncio.to_thread(switch_provider, name)
                    self._update_footer()
                    active = getattr(updated, "active_provider", None) or name
                    await log.mount(Static(f"Active provider: {active}"))
        elif command.name == "config":
            configuration = getattr(self.services, "configuration", None)
            if configuration is None:
                await log.mount(Static("Configuration service is unavailable"))
            elif not command.arguments:
                await self._show_config_menu()
            elif not command.arguments or command.arguments[0] == "show":
                summary = await asyncio.to_thread(configuration.summary)
                user_configuration = getattr(self.services, "user_configuration", None)
                if user_configuration is not None:
                    summary = (
                        summary
                        + "\n\n"
                        + await asyncio.to_thread(user_configuration.summary)
                    )
                await log.mount(Static(summary))
            else:
                _, key, value = command.arguments
                user_configuration = getattr(self.services, "user_configuration", None)
                if key.strip().lower().startswith("budgets."):
                    if user_configuration is None:
                        raise ValueError("user configuration service is unavailable")
                    await asyncio.to_thread(
                        user_configuration.set_budget_value,
                        key.split(".", 1)[1],
                        value,
                    )
                    reload_configuration = getattr(self.services, "reload_configuration", None)
                    if not callable(reload_configuration):
                        raise ValueError("configuration reload is unavailable")
                    updated = await asyncio.to_thread(reload_configuration)
                    self.permission_mode = updated.permission_mode
                    self._update_footer()
                    summary = await asyncio.to_thread(user_configuration.summary)
                    await log.mount(Static(f"User budget updated: {key}\n{summary}"))
                    return
                updated = await asyncio.to_thread(configuration.set_value, key, value)
                reload_configuration = getattr(self.services, "reload_configuration", None)
                if callable(reload_configuration):
                    updated = await asyncio.to_thread(reload_configuration)
                self.permission_mode = updated.permission_mode
                self._update_footer()
                summary = await asyncio.to_thread(configuration.summary)
                await log.mount(Static(f"Configuration updated: {key}\n{summary}"))
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

    async def _provider_profile(self, name: str) -> Any | None:
        configuration = self._user_configuration()
        profiles = await asyncio.to_thread(configuration.profiles)
        return next((profile for profile in profiles if profile.name == name), None)

    def _user_configuration(self) -> Any:
        services = self.services
        if services is None or not hasattr(services, "user_configuration"):
            raise ValueError("user provider configuration is unavailable")
        return services.user_configuration

    async def _reload_provider_runtime(self) -> None:
        reload_configuration = getattr(self.services, "reload_configuration", None)
        if callable(reload_configuration):
            await asyncio.to_thread(reload_configuration)
        self._update_footer()

    @staticmethod
    def _provider_form_values(profile: Any | None = None) -> dict[str, str]:
        if profile is None:
            return {
                "api": "responses",
                "provider": "openai-compatible",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "credential": "openai",
                "timeout_seconds": "120",
                "max_output_tokens": "128000",
                "context_window_chars": "256000",
                "streaming": "false",
                "reasoning_effort": "low",
                "make_active": "true",
            }
        selected = profile.selected
        return {
            "name": profile.name,
            "provider": profile.config.provider,
            "api": selected.api,
            "base_url": selected.base_url,
            "model": selected.model,
            "credential": selected.credential,
            "timeout_seconds": str(selected.timeout_seconds),
            "max_output_tokens": str(selected.max_output_tokens),
            "context_window_chars": str(selected.context_window_chars),
            "streaming": str(selected.streaming).lower(),
            "reasoning_effort": selected.reasoning_effort,
            "make_active": str(profile.active).lower(),
        }

    async def _open_provider_editor(self, name: str | None = None) -> None:
        try:
            profile = await self._provider_profile(name) if name else None
            if name is not None and profile is None:
                raise ValueError(f"provider is not configured: {name}")
            values = await self.push_screen_wait(
                ProviderEditorScreen(
                    self._provider_form_values(profile),
                    editing=profile is not None,
                )
            )
            if values is None:
                return
            provider_name = values.get("name", "").strip()
            if not provider_name:
                raise ValueError("provider name must not be blank")
            api_value = values.get("api", "responses")
            if api_value not in {"chat_completions", "responses", "anthropic", "messages"}:
                raise ValueError(f"unsupported API surface: {api_value}")
            provider = LLMConfig(
                provider=values.get("provider", "openai-compatible"),
                api=cast(Literal["chat_completions", "responses", "anthropic", "messages"], api_value),
                base_url=values.get("base_url", ""),
                model=values.get("model", ""),
                credential=values.get("credential", "").strip() or provider_name,
                timeout_seconds=float(values.get("timeout_seconds", "120")),
                max_output_tokens=int(values.get("max_output_tokens", "128000")),
                context_window_chars=int(values.get("context_window_chars", "256000")),
                streaming=values.get("streaming", "false").lower() == "true",
                reasoning_effort=values.get("reasoning_effort", "low"),
            )
            api_key = values.get("api_key", "").strip() or None
            make_active = values.get("active", "false").lower() == "true"
            configuration = self._user_configuration()
            await asyncio.to_thread(
                configuration.upsert_provider,
                provider_name,
                provider,
                api_key=api_key,
                make_active=make_active,
            )
            await self._reload_provider_runtime()
            await self.query_one(ConversationLog).mount(
                Static(f"Provider {'updated' if name else 'added'}: {provider_name}")
            )
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))

    async def _open_provider_key_editor(self, name: str) -> None:
        try:
            profile = await self._provider_profile(name)
            if profile is None:
                raise ValueError(f"provider is not configured: {name}")
            value = await self.push_screen_wait(ProviderKeyScreen(name))
            if value is None:
                return
            configuration = self._user_configuration()
            await asyncio.to_thread(configuration.set_api_key, name, value)
            await self.query_one(ConversationLog).mount(Static(f"API key updated: {name}"))
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))

    async def _show_provider_delete_confirmation(self, name: str) -> None:
        try:
            profile = await self._provider_profile(name)
            if profile is None:
                raise ValueError(f"provider is not configured: {name}")
            menu = ConfigMenu(
                (
                    (f"Confirm delete provider: {name}", f"provider:delete-confirm:{name}"),
                    ("Cancel", "provider:cancel"),
                )
            )
            await self.query_one(ConversationLog).mount(menu)
            menu.focus()
            self.query_one(StatusFooter).update("Confirm provider deletion · ↑/↓ · Enter · Esc")
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))

    async def _show_provider_key_clear_confirmation(self, name: str) -> None:
        try:
            profile = await self._provider_profile(name)
            if profile is None:
                raise ValueError(f"provider is not configured: {name}")
            menu = ConfigMenu(
                (
                    (f"Confirm clear API key: {name}", f"provider:key-clear-confirm:{name}"),
                    ("Cancel", "provider:cancel"),
                )
            )
            await self.query_one(ConversationLog).mount(menu)
            menu.focus()
            self.query_one(StatusFooter).update("Confirm API-key removal · ↑/↓ · Enter · Esc")
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))

    async def _show_config_menu(self) -> None:
        """Mount a keyboard menu for safe, frequently used configuration edits."""

        log = self.query_one(ConversationLog)
        existing = list(log.query(ConfigMenu))
        for menu in existing:
            await menu.remove()

        options: list[tuple[str, str]] = [
            ("Show full configuration", "show"),
            ("Permission mode: strict", "mode:strict"),
            ("Permission mode: balanced", "mode:balanced"),
            ("Permission mode: autonomous", "mode:autonomous"),
            ("Allow network: on", "policy:allow_network:true"),
            ("Allow network: off", "policy:allow_network:false"),
            ("Allow dependency install: on", "policy:allow_dependency_install:true"),
            ("Allow dependency install: off", "policy:allow_dependency_install:false"),
            ("Allow git writes: on", "policy:allow_git_writes:true"),
            ("Allow git writes: off", "policy:allow_git_writes:false"),
            ("Allow repository writes: on", "policy:allow_writes:true"),
            ("Allow repository writes: off", "policy:allow_writes:false"),
            ("Budget: 10 model calls", "budget:total_model_calls:10"),
            ("Budget: 30 model calls", "budget:total_model_calls:30"),
            ("Budget: 100 model calls", "budget:total_model_calls:100"),
        ]
        user_configuration = getattr(self.services, "user_configuration", None)
        if user_configuration is not None:
            try:
                profiles = await asyncio.to_thread(user_configuration.profiles)
            except Exception:
                profiles = ()
            for profile in profiles:
                options.append(
                    (
                        f"Provider: {profile.name} ({profile.selected.model})",
                        f"provider:use:{profile.name}",
                    )
                )
                if profile.active:
                    try:
                        models = await asyncio.to_thread(user_configuration.models, profile.name)
                    except Exception:
                        models = ()
                    for item in models:
                        options.append(
                            (
                                f"Model: {item.alias} ({item.config.model}, reasoning={item.config.reasoning_effort})",
                                f"model:{profile.name}:{item.alias}",
                            )
                        )
                        for effort in _reasoning_levels(item.config.reasoning_effort):
                            options.append(
                                (
                                    f"  Reasoning for {item.alias}: {effort}",
                                    f"reasoning:{profile.name}:{item.alias}:{effort}",
                                )
                            )
        menu = ConfigMenu(tuple(options))
        await log.mount(menu)
        menu.focus()
        self.query_one(StatusFooter).update("Config menu · ↑/↓ select · Enter apply · Esc close")

    async def _show_provider_menu(self) -> None:
        user_configuration = getattr(self.services, "user_configuration", None)
        if user_configuration is None:
            return
        try:
            profiles = await asyncio.to_thread(user_configuration.profiles)
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))
            return
        options: list[tuple[str, str]] = [("Add provider", "provider:add")]
        for profile in profiles:
            marker = "* " if profile.active else ""
            options.extend(
                (
                    (f"{marker}Use provider: {profile.name} · {profile.selected.model}", f"provider:use:{profile.name}"),
                    (f"Edit provider: {profile.name}", f"provider:edit:{profile.name}"),
                    (f"Delete provider: {profile.name}", f"provider:remove:{profile.name}"),
                    (f"Set API key: {profile.name}", f"provider:key:{profile.name}"),
                    (f"Clear API key: {profile.name}", f"provider:clear-key:{profile.name}"),
                )
            )
        menu = ConfigMenu(tuple(options))
        await self.query_one(ConversationLog).mount(menu)
        menu.focus()
        self.query_one(StatusFooter).update(
            "Provider management · ↑/↓ select · Enter apply · Esc close"
        )

    async def _show_model_menu(self) -> None:
        user_configuration = getattr(self.services, "user_configuration", None)
        if user_configuration is None:
            return
        try:
            active = await asyncio.to_thread(user_configuration.active)
            if active is None:
                await self.query_one(ConversationLog).mount(Static("Model: not configured"))
                return
            models = await asyncio.to_thread(user_configuration.models, active.name)
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))
            return
        if not models:
            await self.query_one(ConversationLog).mount(
                Static(f"Model: {active.selected.model} (legacy provider model)")
            )
            return
        menu = ConfigMenu(
            tuple(
                (
                    (
                        f"{'* ' if item.active else ''}{item.alias} · {item.config.model} · "
                        f"reasoning={item.config.reasoning_effort}"
                    ),
                    f"model:{active.name}:{item.alias}",
                )
                for item in models
            )
        )
        for item in models:
            menu.add_options(
                [
                    Option(
                        f"  Reasoning for {item.alias}: {effort}",
                        id=f"reasoning:{active.name}:{item.alias}:{effort}",
                    )
                    for effort in _reasoning_levels(item.config.reasoning_effort)
                ]
            )
        await self.query_one(ConversationLog).mount(menu)
        menu.focus()
        self.query_one(StatusFooter).update("Model menu · ↑/↓ select · Enter apply · Esc close")

    async def _close_config_menu(self) -> None:
        for menu in list(self.query(ConfigMenu)):
            await menu.remove()
        self._update_footer()
        self._update_input_state()

    async def on_option_list_option_selected(self, message: Any) -> None:
        option_list = getattr(message, "option_list", None)
        if option_list is None or getattr(option_list, "id", None) != "config-menu":
            return
        option = getattr(message, "option", None)
        action = getattr(option, "id", None)
        if isinstance(action, str):
            # Menu messages are dispatched by Textual's message pump rather than
            # a worker. Provider add/edit/key actions wait for a modal result, and
            # Textual only permits that wait from an active worker. Running every
            # menu action here also keeps persistence and menu cleanup ordered.
            self.run_worker(self._apply_config_menu_action(action), group="config-menu")

    async def _apply_config_menu_action(self, action: str) -> None:
        menu = self.query_one(ConfigMenu)
        try:
            if action == "show":
                await menu.remove()
                await self._execute_command(ParsedCommand("config", ("show",)))
                return
            if action.startswith("mode:"):
                value = action.split(":", 1)[1]
                await self._set_project_config_value("mode", value)
            elif action.startswith("policy:"):
                _, key, value = action.split(":", 2)
                await self._set_project_config_value(key, value)
            elif action.startswith("budget:"):
                _, key, value = action.split(":", 2)
                user_configuration = getattr(self.services, "user_configuration", None)
                if user_configuration is None:
                    raise ValueError("user configuration service is unavailable")
                await asyncio.to_thread(user_configuration.set_budget_value, key, value)
                reload_configuration = getattr(self.services, "reload_configuration", None)
                if callable(reload_configuration):
                    await asyncio.to_thread(reload_configuration)
                await self.query_one(ConversationLog).mount(
                    Static(f"User budget updated: {key}={value}")
                )
            elif action.startswith("provider:"):
                parts = action.split(":", 2)
                if len(parts) == 2 and parts[1] in {"add", "cancel"}:
                    operation, name = parts[1], ""
                else:
                    operation = parts[1] if len(parts) == 3 else "use"
                    name = parts[2] if len(parts) == 3 else parts[1]
                if operation == "cancel":
                    return
                if operation == "add":
                    await self._open_provider_editor()
                    return
                if operation == "edit":
                    await self._open_provider_editor(name)
                    return
                if operation == "remove":
                    await self._show_provider_delete_confirmation(name)
                    return
                if operation == "delete-confirm":
                    configuration = self._user_configuration()
                    await asyncio.to_thread(configuration.remove_provider, name)
                    await self._reload_provider_runtime()
                    await self.query_one(ConversationLog).mount(
                        Static(f"Provider deleted: {name}")
                    )
                    return
                if operation == "key":
                    await self._open_provider_key_editor(name)
                    return
                if operation == "clear-key":
                    await self._show_provider_key_clear_confirmation(name)
                    return
                if operation == "key-clear-confirm":
                    configuration = self._user_configuration()
                    await asyncio.to_thread(configuration.clear_api_key, name)
                    await self.query_one(ConversationLog).mount(
                        Static(f"API key cleared: {name}")
                    )
                    return
                if operation != "use":
                    raise ValueError(f"unknown provider menu action: {operation}")
                switch_provider = getattr(self.services, "switch_provider", None)
                if not callable(switch_provider):
                    raise ValueError("provider switching is unavailable")
                await asyncio.to_thread(switch_provider, name)
                self._update_footer()
                await self.query_one(ConversationLog).mount(Static(f"Active provider: {name}"))
            elif action.startswith("model:"):
                _, provider, alias = action.split(":", 2)
                switch_model = getattr(self.services, "switch_model", None)
                if not callable(switch_model):
                    raise ValueError("model switching is unavailable")
                await asyncio.to_thread(switch_model, provider, alias)
                self._update_footer()
                await self.query_one(ConversationLog).mount(
                    Static(f"Active model for {provider}: {alias}")
                )
            elif action.startswith("reasoning:"):
                _, provider, alias, effort = action.split(":", 3)
                switch_reasoning = getattr(self.services, "switch_model_reasoning", None)
                if not callable(switch_reasoning):
                    raise ValueError("model reasoning switching is unavailable")
                await asyncio.to_thread(switch_reasoning, provider, alias, effort)
                self._update_footer()
                await self.query_one(ConversationLog).mount(
                    Static(f"Reasoning for {provider}/{alias}: {effort}")
                )
        except Exception as error:
            await self.query_one(ConversationLog).mount(render_error(error))
        finally:
            if menu.parent is not None:
                await menu.remove()
            self._update_footer()
            self._update_input_state()

    async def _set_project_config_value(self, key: str, value: str) -> None:
        configuration = getattr(self.services, "configuration", None)
        if configuration is None:
            raise ValueError("configuration service is unavailable")
        updated = await asyncio.to_thread(configuration.set_value, key, value)
        reload_configuration = getattr(self.services, "reload_configuration", None)
        if callable(reload_configuration):
            updated = await asyncio.to_thread(reload_configuration)
        self.permission_mode = updated.permission_mode
        await self.query_one(ConversationLog).mount(
            Static(f"Configuration updated: {key}={value}")
        )

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
                if state == RunState.WAITING_MODEL.value:
                    # Each model call is a fresh response.  Keep the live view
                    # focused on the current turn instead of concatenating
                    # repeated planning text from an earlier no-action turn.
                    self._drafts.pop(update.run_id, None)
                    previous = self._assistants.pop(update.run_id, None)
                    if previous is not None:
                        await previous.remove()
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
                    finished_widget.replace_with(result)
                    self._last_tool_widget = finished_widget
            elif update.kind is ProgressKind.VALIDATION_STARTED:
                self._validation_widget = DetailMessage(
                    Static("Validation started"),
                    "Validation started",
                    classes="conversation-entry validation-result",
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
                    self._validation_widget.replace_with(result)
                    self._last_tool_widget = self._validation_widget
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
            self._last_tool_widget = None
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
        provider = None
        user_configuration = getattr(self.services, "user_configuration", None)
        if user_configuration is not None:
            try:
                provider = user_configuration.load().active_provider
            except Exception:
                provider = None
        provider = provider or getattr(metadata, "provider", None) or "unconfigured"
        session = str(self._current_session_id)[:8] if self._current_session_id else "new"
        footer.update(
            "613 Coding"
            f" | repo={repository}"
            f" | session={session}"
            f" | model={model}"
            f" | mode={self.permission_mode.value}"
            f" | provider={provider}"
        )

    def _update_command_hints(self) -> None:
        try:
            composer = self.query_one(TaskComposer)
            hints = self.query_one(CommandHints)
        except Exception:
            return
        matches = self.command_catalog.complete(composer.text)
        # Keep the original prefix choices while the user cycles through a
        # completed item (for example ``/co`` -> ``/config`` -> ``/compact``).
        # Once the text no longer names one of those choices, normal prefix
        # matching resumes.
        if composer.text in composer.completion_matches:
            matches = composer.completion_matches
        composer.set_completion_matches(matches)
        hints.update_matches(matches, composer.completion_index)

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
