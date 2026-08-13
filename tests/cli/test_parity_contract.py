from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from uuid import UUID

from coding613.cli.prompt import parse_root_args, run_print
from coding613.domain.conversation import (
    DiagnosticCheck,
    DiagnosticReport,
    PromptRequest,
    RunOptions,
)
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import (
    PermissionMode,
    Project,
    Run,
    RunState,
    RunSummary,
    StopReason,
)


class RecordingConversation:
    def __init__(self, project_id: UUID) -> None:
        self.project_id = project_id
        self.session = InteractiveSession(project_id=project_id)
        self.requests: list[PromptRequest] = []

    def submit(self, request: PromptRequest) -> Run:
        self.requests.append(request)
        return Run(
            project_id=request.project_id,
            session_id=request.session_id or self.session.id,
            task=request.text,
            options=request.options,
            permission_mode=request.permission_mode or PermissionMode.BALANCED,
        )

    def execute(self, run_id, sink, cancellation):
        del cancellation
        return RunSummary(run_id=run_id, status=RunState.COMPLETED, stop_reason=StopReason.SUCCESS)


class Services:
    def __init__(self, root: Path) -> None:
        project = Project(canonical_root=root)
        self.run_service = type("RunService", (), {"project": project})()
        self.conversation = RecordingConversation(project.id)
        self.diagnostics = type(
            "Diagnostics",
            (),
            {
                "run": lambda _, project_id: DiagnosticReport(
                    project_id=project_id,
                    checks=(DiagnosticCheck(name="provider", status="pass", detail="ready"),),
                )
            },
        )()


def test_print_contract_preserves_prompt_options_and_session_selection(tmp_path: Path) -> None:
    services = Services(tmp_path)
    request = parse_root_args(
        [
            "-p",
            "--repo",
            str(tmp_path),
            "--continue",
            "--output-format",
            "stream-json",
            "--permission-mode",
            "strict",
            "--model",
            "gpt-test",
            "repair",
            "tests",
        ]
    )
    output = StringIO()

    assert run_print(request, services_factory=lambda _: services, stdout=output) == 0
    captured = services.conversation.requests[0]
    assert captured.text == "repair tests"
    assert captured.continue_latest is True
    assert captured.permission_mode.value == "strict"
    assert captured.options == RunOptions(model="gpt-test")
    assert '"type":"run.completed"' in output.getvalue()


def test_stream_output_contains_session_and_user_lifecycle_events(tmp_path: Path) -> None:
    services = Services(tmp_path)
    request = parse_root_args(
        [
            "-p",
            "--repo",
            str(tmp_path),
            "--output-format",
            "stream-json",
            "token=secret-value",
        ]
    )

    output = StringIO()
    assert run_print(request, services_factory=lambda _: services, stdout=output) == 0

    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [event["type"] for event in events[:2]] == ["session.started", "user.message"]
    assert events[-1]["type"] == "run.completed"
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert "secret-value" not in output.getvalue()


def test_stream_terminal_event_reports_dangerous_alias_mode(tmp_path: Path) -> None:
    services = Services(tmp_path)
    request = parse_root_args(
        [
            "-p",
            "--repo",
            str(tmp_path),
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "inspect",
        ]
    )

    output = StringIO()
    assert run_print(request, services_factory=lambda _: services, stdout=output) == 0

    terminal = json.loads(output.getvalue().splitlines()[-1])
    assert terminal["type"] == "run.completed"
    assert terminal["data"]["permission_mode"] == "bypass"


def test_verbose_stream_output_wraps_diagnostics_as_versioned_event(tmp_path: Path) -> None:
    services = Services(tmp_path)
    request = parse_root_args(
        [
            "-p",
            "--repo",
            str(tmp_path),
            "--verbose",
            "--output-format",
            "stream-json",
            "inspect",
        ]
    )
    output = StringIO()

    assert run_print(request, services_factory=lambda _: services, stdout=output) == 0

    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert all(event["schema_version"] == 1 for event in events)
    assert events[0]["type"] == "diagnostic.completed"
