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
from coding613.domain.models import ApprovalRequest, ResourceUsage, RunSummary
from coding613.domain.redaction import redact_text
from coding613.ports.tools import ToolResult

_DETAIL_LIMIT = 8_000
_TOOL_RESULT_LIMIT = 1_000_000
_TOOL_PREVIEW_LIMIT = 200
_VALIDATION_LINE_LIMIT = 10


def _bounded(text: str, limit: int = _DETAIL_LIMIT) -> str:
    value = redact_text(text)
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n... output truncated ({len(value) - limit} characters omitted)"


def _bounded_lines(text: str, limit: int = _VALIDATION_LINE_LIMIT) -> str:
    """Bound human-facing command output by lines, with a byte-safe fallback."""

    value = redact_text(text)
    lines = value.splitlines()
    if len(lines) > limit:
        omitted = len(lines) - limit
        return "\n".join(lines[:limit]) + f"\n... {omitted} lines omitted"
    # A command can emit one very long line. Keep the existing character safety
    # boundary for that pathological case while using line count for normal logs.
    return _bounded(value)


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
    def __init__(
        self,
        visual: Any,
        display_text: str,
        *,
        classes: str,
        expanded_visual: Any | None = None,
        expanded_text: str | None = None,
    ) -> None:
        self._collapsed_visual = visual
        self._expanded_visual = expanded_visual if expanded_visual is not None else visual
        self._collapsed_text = display_text
        self._expanded_text = expanded_text if expanded_text is not None else display_text
        self.expanded = False
        self.display_text = display_text
        super().__init__(visual, classes=classes)

    @property
    def expandable(self) -> bool:
        """Whether this detail has a larger view available."""

        return self._expanded_visual is not self._collapsed_visual

    def toggle_expanded(self) -> bool:
        """Toggle the larger view and return the new expanded state."""

        if not self.expandable:
            return False
        self.expanded = not self.expanded
        self.display_text = self._expanded_text if self.expanded else self._collapsed_text
        self.update(self._expanded_visual if self.expanded else self._collapsed_visual)
        return self.expanded

    def replace_with(self, other: DetailMessage) -> None:
        """Replace content while retaining this widget's position in the log."""

        self._collapsed_visual = other._collapsed_visual
        self._expanded_visual = other._expanded_visual
        self._collapsed_text = other._collapsed_text
        self._expanded_text = other._expanded_text
        self.expanded = other.expanded
        self.display_text = other.display_text
        self.update(other.renderable)


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
    # Keep the terminal's expanded view separately bounded from the loop's
    # larger internal progress cap; only the default view is shortened here.
    full_output = _bounded(result.output, _TOOL_RESULT_LIMIT) if result.output else ""
    if (
        result.call.name == "apply_patch"
        and result.error
        and result.error.startswith("PatchConflictError")
        and not full_output
    ):
        # Older persisted progress events may contain only the stable error
        # type. Keep the TUI actionable even when they predate the executor's
        # richer current-file excerpt.
        full_output = (
            "Patch rejected because repository context changed; re-read the affected files "
            "with read_file and submit a fresh patch."
        )
    preview_output, output_collapsed = _preview_tool_text(full_output)
    full_error = _bounded(result.error, _TOOL_RESULT_LIMIT) if result.error else ""
    preview_error, error_collapsed = _preview_tool_text(full_error)
    full_details = _tool_result_details(full_output, full_error, result.changed_files)
    preview_details = _tool_result_details(preview_output, preview_error, result.changed_files)
    header = f"Tool {result.call.name}: {status}"
    content = Group(
        Text(header, style="green" if result.success else "red"),
        Text(preview_details),
    )
    expanded_content = Group(
        Text(header, style="green" if result.success else "red"),
        Text(full_details),
    )
    expandable = output_collapsed or error_collapsed
    preview_text = f"{header}\n{preview_details}"
    full_text = f"{header}\n{full_details}"
    return DetailMessage(
        content,
        preview_text,
        classes="conversation-entry tool-result",
        expanded_visual=expanded_content if expandable else None,
        expanded_text=full_text if expandable else None,
    )


def _preview_tool_text(text: str, limit: int = _TOOL_PREVIEW_LIMIT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    preview = text[:limit].rsplit("\n", 1)[0]
    hidden = len(text) - len(preview)
    return f"{preview}\n... {hidden} characters hidden; press Ctrl+T to expand", True


def _tool_result_details(
    output: str,
    error: str,
    changed_files: tuple[str, ...],
) -> str:
    details: list[str] = []
    if output:
        details.append(output)
    if error:
        details.append(f"error: {error}")
    if changed_files:
        details.append(f"changed: {', '.join(changed_files)}")
    return "\n".join(details) or "(no output)"


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
    safe_output = _bounded_lines(output) if output else "(no output)"
    content = Group(
        Text(header, style="green" if result.passed else "red"),
        Text(safe_output),
    )
    expanded_output = _bounded(output, _TOOL_RESULT_LIMIT) if output else "(no output)"
    expanded_content = Group(
        Text(header, style="green" if result.passed else "red"),
        Text(expanded_output),
    )
    expandable = expanded_output != safe_output
    return DetailMessage(
        content,
        f"{header}\n{safe_output}",
        classes="conversation-entry validation-result",
        expanded_visual=expanded_content if expandable else None,
        expanded_text=f"{header}\n{expanded_output}" if expandable else None,
    )


def render_run_summary(summary: RunSummary) -> DetailMessage:
    """Render terminal feedback and resource usage without exposing raw payloads."""

    stop_reason = summary.stop_reason.value if summary.stop_reason else "none"
    lines = [
        f"Run: {summary.status.value} | stop_reason={stop_reason}",
        f"validation={len(summary.validation_evidence)} | approvals={len(summary.approvals)}",
        f"resource_profile={summary.resource_profile or 'standard'}",
        (
            "feedback="
            + (",".join(item.value for item in summary.completion_blockers) or "none")
        ),
        (
            "resource_usage="
            + ", ".join(
                f"{name}={value}"
                for name, value in summary.resource_usage.model_dump(mode="json").items()
            )
        ),
    ]
    if summary.changed_files:
        lines.append("changed_files=" + ", ".join(summary.changed_files))
    display_text = _bounded("\n".join(lines))
    return DetailMessage(
        Text(display_text, style="green" if summary.status.value == "completed" else "yellow"),
        display_text,
        classes="conversation-entry run-summary",
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
        _budget_item("turns", usage.agent_turns, None),
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
