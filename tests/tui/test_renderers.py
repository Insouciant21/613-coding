from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from textual.containers import VerticalScroll
from textual.widgets import Markdown

from coding613.application.approvals import action_fingerprint
from coding613.application.budgets import BudgetLimits
from coding613.application.validation import ValidationKind, ValidationResult
from coding613.domain.actions import ToolCall
from coding613.domain.models import ApprovalRequest, ResourceUsage
from coding613.ports.tools import ToolResult
from coding613.tui.renderers import (
    render_approval,
    render_assistant,
    render_budget,
    render_error,
    render_tool_call,
    render_tool_result,
    render_unified_diff,
    render_validation,
)


def test_assistant_uses_textual_markdown() -> None:
    widget = render_assistant("**fixed**")

    assert isinstance(widget, Markdown)
    assert widget.markdown_text == "**fixed**"


def test_tool_call_and_result_render_structured_bounded_details() -> None:
    call = ToolCall(
        name="edit_file",
        arguments={"path": "src/app.py", "api_key": "sk-secretvalue"},
    )
    result = ToolResult(
        call=call,
        success=False,
        output="x" * 20_000,
        error="password=hunter2",
        changed_files=("src/app.py",),
    )

    call_text = render_tool_call(call).display_text
    result_text = render_tool_result(result).display_text

    assert "edit_file" in call_text
    assert '"path": "src/app.py"' in call_text
    assert "sk-secretvalue" not in call_text
    assert "[REDACTED]" in call_text
    assert "failed" in result_text
    assert "password=hunter2" not in result_text
    assert "output truncated" in result_text
    assert len(result_text) < 12_000


def test_diff_and_validation_render_command_status_and_capped_output() -> None:
    patch = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"
    validation = ValidationResult(
        command=("uv", "run", "pytest", "-q"),
        kind=ValidationKind.TEST,
        exit_code=1,
        stdout="passed output\n",
        stderr="failure\n" + ("z" * 20_000),
        duration_seconds=1.25,
    )

    assert patch == render_unified_diff(patch).display_text
    validation_text = render_validation(validation).display_text
    assert "uv run pytest -q" in validation_text
    assert "exit 1" in validation_text
    assert "1.25s" in validation_text
    assert "output truncated" in validation_text
    assert len(validation_text) < 12_000


def test_approval_contains_exact_fingerprint_reason_paths_and_long_diff() -> None:
    additions = "".join(f"+line {index}\n" for index in range(200))
    patch = (
        "--- /dev/null\n"
        "+++ b/src/generated.py\n"
        "@@ -0,0 +1,200 @@\n"
        f"{additions}"
    )
    request = ApprovalRequest(
        run_id=uuid4(),
        action=ToolCall(name="apply_patch", arguments={"patch": patch}),
        reason="repository write requires approval",
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    widget = render_approval(request)

    assert isinstance(widget, VerticalScroll)
    assert widget.action_fingerprint == action_fingerprint(request.action)
    assert widget.reason == request.reason
    assert widget.affected_paths == ("src/generated.py",)
    assert widget.diff == patch


def test_error_is_redacted_and_budget_shows_used_over_limit() -> None:
    error_text = (
        render_error(RuntimeError("provider rejected api_key=topsecret sk-secretvalue"))
    ).display_text
    budget_text = (
        render_budget(
            ResourceUsage(
                agent_turns=2,
                model_calls=3,
                wall_time_seconds=4.5,
                provider_cost=0.25,
            ),
            BudgetLimits(total_model_calls=8, provider_cost=1.0),
        )
    ).display_text

    assert "topsecret" not in error_text
    assert "sk-secretvalue" not in error_text
    assert "[REDACTED]" in error_text
    assert "calls 3/8" in budget_text
    assert "cost $0.2500/$1.0000" in budget_text
