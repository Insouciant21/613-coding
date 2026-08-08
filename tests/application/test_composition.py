from __future__ import annotations

from pathlib import Path

from coding_harness.application.composition import build_services
from coding_harness.application.run_service import RunRequest
from coding_harness.domain.models import RunState, StopReason


def test_local_composition_persists_runs_and_can_cancel_without_provider(tmp_path: Path) -> None:
    services = build_services(tmp_path)
    run = services.run_service.create_run(RunRequest(task="inspect repository"))

    assert run.project_id is not None
    cancelled = services.run_service.cancel(run.id)

    assert cancelled.status is RunState.CANCELLED
    assert cancelled.stop_reason is StopReason.CANCELLED
    assert services.list_events(run.id)


def test_local_composition_reports_provider_boundary_on_resume(tmp_path: Path) -> None:
    services = build_services(tmp_path)
    run = services.run_service.create_run(RunRequest(task="make a change"))

    summary = services.run_service.resume(run.id)

    assert summary.status is RunState.FAILED
    assert summary.stop_reason is StopReason.PROVIDER_ERROR
