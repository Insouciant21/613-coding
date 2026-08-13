from __future__ import annotations

from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest

from coding613.cli.prompt import parse_root_args, run_print
from coding613.domain.conversation import DiagnosticCheck, DiagnosticReport
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import PermissionMode, Project, Run, RunState, RunSummary, StopReason
from coding613.ports.progress import ProgressKind, RunProgress


class FakeConversation:
    def __init__(self, project_id: UUID) -> None:
        self.project_id = project_id
        self.session = InteractiveSession(project_id=project_id)
        self.requests: list[object] = []

    def submit(self, request):
        self.requests.append(request)
        session_id = request.session_id or self.session.id
        if request.session_id is None and not request.continue_latest:
            self.session = InteractiveSession(project_id=self.project_id)
            session_id = self.session.id
        return Run(project_id=self.project_id, session_id=session_id, task=request.text)

    def execute(self, run_id, sink, cancellation):
        del cancellation
        sink.publish(RunProgress(run_id=run_id, kind=ProgressKind.TEXT_DELTA, text="hello"))
        return RunSummary(run_id=run_id, status=RunState.COMPLETED, stop_reason=StopReason.SUCCESS)


class FakeServices:
    def __init__(self, root: Path) -> None:
        project = Project(canonical_root=root)
        self.run_service = type("RunService", (), {"project": project})()
        self.conversation = FakeConversation(project.id)
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


def test_print_request_captures_prompt_and_options(tmp_path: Path) -> None:
    request = parse_root_args(
        [
            "-p",
            "--repo",
            str(tmp_path),
            "--output-format",
            "json",
            "--permission-mode",
            "strict",
            "--model",
            "gpt-test",
            "--allowed-tools",
            "read_file",
            "repair",
            "tests",
        ]
    )

    assert request.print_mode is True
    assert request.prompt == "repair tests"
    assert request.options.model == "gpt-test"
    assert request.options.allowed_tools == frozenset({"read_file"})
    assert request.permission_mode is PermissionMode.STRICT


def test_root_parser_rejects_conflicting_session_selectors(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse_root_args(["--repo", str(tmp_path), "--continue", "--resume", "latest"])


def test_root_parser_accepts_bypass_and_dangerous_alias(tmp_path: Path) -> None:
    canonical = parse_root_args(
        ["--repo", str(tmp_path), "--permission-mode", "bypass", "inspect"]
    )
    alias = parse_root_args(
        ["--repo", str(tmp_path), "--dangerously-skip-permissions", "inspect"]
    )

    assert canonical.permission_mode is PermissionMode.BYPASS
    assert alias.permission_mode is PermissionMode.BYPASS


def test_root_parser_rejects_conflicting_dangerous_mode(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse_root_args(
            [
                "--repo",
                str(tmp_path),
                "--permission-mode",
                "strict",
                "--dangerously-skip-permissions",
                "inspect",
            ]
        )


def test_root_parser_rejects_invalid_resume_before_service_creation(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse_root_args(["--repo", str(tmp_path), "--resume", "not-a-session", "inspect"])


def test_run_print_json_uses_shared_conversation_and_emits_final_envelope(tmp_path: Path) -> None:
    services = FakeServices(tmp_path)
    request = parse_root_args(
        ["-p", "--repo", str(tmp_path), "--output-format", "json", "repair", "tests"]
    )
    output = StringIO()

    code = run_print(request, services_factory=lambda _: services, stdout=output)

    assert code == 0
    assert '"assistant_text":"hello"' in output.getvalue()
    assert len(services.conversation.requests) == 1


def test_run_print_reports_invalid_stdin_without_creating_services(tmp_path: Path) -> None:
    created = False

    def factory(_: Path):
        nonlocal created
        created = True
        return FakeServices(tmp_path)

    request = parse_root_args(["-p", "--repo", str(tmp_path)])
    output = StringIO()

    code = run_print(request, services_factory=factory, stdin=StringIO(" \n"), stdout=output)

    assert code == 2
    assert created is False
    assert "invalid input" in output.getvalue()


def test_run_print_verbose_emits_injected_diagnostics(tmp_path: Path) -> None:
    services = FakeServices(tmp_path)
    request = parse_root_args(["-p", "--repo", str(tmp_path), "--verbose", "inspect"])
    output = StringIO()

    assert run_print(request, services_factory=lambda _: services, stdout=output) == 0
    assert '"name":"provider"' in output.getvalue()
