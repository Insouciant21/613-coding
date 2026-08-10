from __future__ import annotations

from uuid import uuid4

from coding613.application.diagnostics import DiagnosticService
from coding613.domain.conversation import DiagnosticCheck


def test_diagnostics_uses_injected_checks_and_redacts_details() -> None:
    def check(project_id):
        assert project_id == project
        return DiagnosticCheck(
            name="provider", status="warn", detail="provider configured; key [REDACTED]"
        )

    project = uuid4()
    report = DiagnosticService((check,)).run(project)

    assert report.project_id == project
    assert report.checks[0].status == "warn"
    assert "key [REDACTED]" in report.checks[0].detail


def test_diagnostics_maps_failed_check_to_fail_without_raising() -> None:
    def broken(project_id):
        del project_id
        raise RuntimeError("backend secret sk-test-secret")

    report = DiagnosticService((broken,)).run(uuid4())

    assert report.checks[0].status == "fail"
    assert "sk-test-secret" not in report.checks[0].detail
