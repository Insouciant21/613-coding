"""Bounded, redacted renderers for the local terminal conversation."""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterable
from typing import Any

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static
from unidiff import PatchSet  # type: ignore[import-untyped]
from unidiff.errors import UnidiffParseError  # type: ignore[import-untyped]

from coding613.application.approvals import action_fingerprint
from coding613.application.budgets import BudgetLimits
from coding613.application.validation import ValidationResult
from coding613.domain.actions import ToolCall
from coding613.domain.events import redact_payload
from coding613.domain.models import ApprovalRequest, ResourceUsage
from coding613.domain.redaction import redact_text
from coding613.ports.tools import ToolResult

_DETAIL_LIMIT = 8_000


def _bounded(text: str, limit: int = _DETAIL_LIMIT) -> str:
    value = redact_text(text)
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n... output truncated ({len(value) - limit} characters omitted)"


def _json(value: Any) -> str:
    return json.dumps(redact_payload(value), indent=2, sort_keys=True, ensure_ascii=True)


class AssistantMessage(Markdown):
    def __init__(self, text: str) -> None:
        self.markdown_text = redact_text(text)
        super().__init__(self.markdown_text, classes="conversation-entry assistant-message")

    def replace(self, text: str) -> None:
        self.markdown_text = redact_text(text)
        self.update(self.markdown_text)


class DetailMessage(Static):
    def __init__(self, visual: Any, display_text: str, *, classes: str) -> None:
        self.display_text = display_text
        super().__init__(visual, classes=classes)


class ApprovalView(VerticalScroll):
    can_focus = True

    def __init__(self, request: ApprovalRequest) -> None:
        self.request_id = request.id
        self.action = request.action
        self.action_fingerprint = action_fingerprint(request.action)
        self.reason = redact_text(request.reason)
        self.affected_paths = _affected_paths(request.action)
        patch = request.action.arguments.get("patch", "")
        self.diff = redact_text(patch) if isinstance(patch, str) else ""
        super().__init__(classes="conversation-entry approval-view")

    def compose(self) -> ComposeResult:
        paths = ", ".join(self.affected_paths) or "none"
        header = Text.assemble(
            ("Approval required\n", "bold yellow"),
            f"Reason: {self.reason}\n",
            f"Fingerprint: {self.action_fingerprint}\n",
            f"Affected paths: {paths}\n",
            ("A approve  |  R reject", "bold"),
        )
        yield Static(header, classes="approval-header")
        if self.diff:
            yield render_unified_diff(self.diff)
        else:
            yield render_tool_call(self.action)


def render_assistant(text: str) -> AssistantMessage:
    return AssistantMessage(text)


def render_tool_call(call: ToolCall) -> DetailMessage:
    arguments = _json(call.arguments)
    content = Group(
        Text(f"Tool: {call.name}", style="bold cyan"),
        Syntax(arguments, "json", word_wrap=True),
    )
    return DetailMessage(
        content,
        f"Tool: {call.name}\n{arguments}",
        classes="conversation-entry tool-call",
    )


def render_tool_result(result: ToolResult) -> DetailMessage:
    status = "passed" if result.success else "failed"
    details: list[str] = []
    if result.output:
        details.append(_bounded(result.output))
    if result.error:
        details.append(f"error: {_bounded(result.error)}")
    if result.changed_files:
        details.append(f"changed: {', '.join(result.changed_files)}")
    content = Group(
        Text(f"Tool {result.call.name}: {status}", style="green" if result.success else "red"),
        Syntax("\n".join(details) or "(no output)", "text", word_wrap=True),
    )
    return DetailMessage(
        content,
        f"Tool {result.call.name}: {status}\n" + ("\n".join(details) or "(no output)"),
        classes="conversation-entry tool-result",
    )


def render_unified_diff(diff: str) -> DetailMessage:
    safe_diff = redact_text(diff)
    return DetailMessage(
        Syntax(safe_diff, "diff", word_wrap=False),
        safe_diff,
        classes="conversation-entry unified-diff",
    )


def render_validation(result: ValidationResult) -> DetailMessage:
    exit_status = "timeout" if result.timed_out else f"exit {result.exit_code}"
    command = shlex.join(result.command)
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    header = f"Validation: {command} | {exit_status} | {result.duration_seconds:.2f}s"
    safe_output = _bounded(output) if output else "(no output)"
    content = Group(
        Text(header, style="green" if result.passed else "red"),
        Syntax(safe_output, "text", word_wrap=True),
    )
    return DetailMessage(
        content,
        f"{header}\n{safe_output}",
        classes="conversation-entry validation-result",
    )


def render_approval(request: ApprovalRequest) -> ApprovalView:
    return ApprovalView(request)


def render_error(error: BaseException | str) -> DetailMessage:
    message = str(error)
    display_text = f"Error: {_bounded(message)}"
    return DetailMessage(
        Text(display_text, style="bold red"),
        display_text,
        classes="conversation-entry error-message",
    )


def render_budget(usage: ResourceUsage, limits: BudgetLimits) -> DetailMessage:
    items = (
        _budget_item("turns", usage.agent_turns, limits.per_agent_turns),
        _budget_item("calls", usage.model_calls, limits.total_model_calls),
        _budget_item("time", usage.wall_time_seconds, limits.wall_time_seconds, suffix="s"),
        _budget_item("cost", usage.provider_cost, limits.provider_cost, currency=True),
    )
    display_text = "Budget: " + " | ".join(items)
    return DetailMessage(
        Text(display_text, style="dim"),
        display_text,
        classes="conversation-entry budget-state",
    )


def _budget_item(
    label: str,
    used: float,
    limit: float | None,
    *,
    suffix: str = "",
    currency: bool = False,
) -> str:
    if currency:
        used_text = f"${used:.4f}"
        limit_text = "unlimited" if limit is None else f"${limit:.4f}"
    else:
        used_text = f"{used:g}{suffix}"
        limit_text = "unlimited" if limit is None else f"{limit:g}{suffix}"
    return f"{label} {used_text}/{limit_text}"


def _affected_paths(call: ToolCall) -> tuple[str, ...]:
    paths: list[str] = []
    direct_path = call.arguments.get("path")
    if isinstance(direct_path, str) and direct_path:
        paths.append(direct_path)
    direct_paths = call.arguments.get("paths")
    if isinstance(direct_paths, Iterable) and not isinstance(direct_paths, (str, bytes)):
        paths.extend(str(path) for path in direct_paths if isinstance(path, str) and path)
    patch = call.arguments.get("patch")
    if isinstance(patch, str) and patch:
        try:
            for item in PatchSet(patch):
                value = str(item.target_file if item.target_file != "/dev/null" else item.source_file)
                value = value.split("\t", 1)[0]
                if value.startswith(("a/", "b/")):
                    value = value[2:]
                if value and value != "/dev/null":
                    paths.append(value)
        except (UnidiffParseError, UnicodeDecodeError):
            return tuple(dict.fromkeys(paths))
    return tuple(dict.fromkeys(paths))
