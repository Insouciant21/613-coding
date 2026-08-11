from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Markdown

from coding613.application.approvals import action_fingerprint
from coding613.application.budgets import BudgetLimits
from coding613.application.validation import ValidationKind, ValidationResult
from coding613.domain.actions import ToolCall
from coding613.domain.models import (
    ApprovalRequest,
    FeedbackKind,
    ResourceUsage,
    RunState,
    RunSummary,
    StopReason,
)
from coding613.ports.tools import ToolResult
from coding613.tui.renderers import (
    render_approval,
    render_assistant,
    render_budget,
    render_error,
    render_run_summary,
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
    assert len(result_text) < 12_000
    assert "output truncated" not in result_text
    assert "characters hidden; press Ctrl+T to expand" in result_text
    expanded_widget = render_tool_result(result)
    assert expanded_widget.expandable
    assert expanded_widget.toggle_expanded()
    assert "output truncated" not in expanded_widget.display_text
    assert "x" * 200 in expanded_widget.display_text


def test_large_tool_result_is_collapsed_and_can_be_expanded() -> None:
    output = "\n".join(f"line-{index}" for index in range(400))
    widget = render_tool_result(
        ToolResult(
            call=ToolCall(name="read_file", arguments={"path": "src/app.py"}),
            success=True,
            output=output,
        )
    )

    assert widget.expandable
    assert "line-0" in widget.display_text
    assert "line-399" not in widget.display_text
    assert "Ctrl+T" in widget.display_text

    assert widget.toggle_expanded()
    assert "line-399" in widget.display_text
    assert "Ctrl+T" not in widget.display_text
    assert not widget.toggle_expanded()
    assert "line-399" not in widget.display_text


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


def test_validation_render_caps_lines_and_avoids_syntax_background_blocks() -> None:
    validation = ValidationResult(
        command=("npm", "test"),
        kind=ValidationKind.TEST,
        exit_code=1,
        stdout="\n".join(f"line-{index}" for index in range(400)),
        duration_seconds=0.2,
    )

    widget = render_validation(validation)

    assert "line-0" in widget.display_text
    assert "line-9" in widget.display_text
    assert "line-10" not in widget.display_text
    assert "lines omitted" in widget.display_text
    assert isinstance(widget.renderable.renderables[1], Text)
    assert widget.expandable
    assert widget.toggle_expanded()
    assert "line-399" in widget.display_text


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


def test_run_summary_renderer_exposes_feedback_validation_and_budget() -> None:
    summary = RunSummary(
        run_id=uuid4(),
        status=RunState.FAILED,
        stop_reason=StopReason.VALIDATION_FAILED,
        changed_files=("src/app.py",),
        validation_evidence=({"stdout": "1 failed"},),
        approvals=(uuid4(),),
        completion_blockers=(FeedbackKind.TEST_FAILURE,),
        resource_usage=ResourceUsage(model_calls=2, wall_time_seconds=1.25),
    )

    widget = render_run_summary(summary)

    assert "validation_failed" in widget.display_text
    assert "test_failure" in widget.display_text
    assert "validation=1" in widget.display_text
    assert "approvals=1" in widget.display_text
    assert "model_calls=2" in widget.display_text
