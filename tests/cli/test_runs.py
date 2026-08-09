from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from typer.testing import CliRunner

import coding613.cli.runs as runs_cli
from coding613.application.approvals import ApprovalDecision, ApprovalResolution
from coding613.cli.main import app
from coding613.domain.models import Run, RunState, RunSummary, StopReason


@dataclass
class FakeService:
    run: Run
    events_data: tuple[dict[str, object], ...] = ()
    approval_calls: list[tuple[UUID, ApprovalDecision]] | None = None

    def __post_init__(self) -> None:
        self.approval_calls = []

    def create_run(self, request):
        self.run = self.run.model_copy(update={"task": request.task})
        return self.run

    def get_summary(self, run_id: UUID) -> RunSummary:
        assert run_id == self.run.id
        return RunSummary(run_id=run_id, status=self.run.state, stop_reason=self.run.stop_reason)

    def resume(self, run_id: UUID) -> RunSummary:
        return self.get_summary(run_id)

    def cancel(self, run_id: UUID) -> RunSummary:
        return RunSummary(run_id=run_id, status=RunState.CANCELLED, stop_reason=StopReason.CANCELLED)

    def approve(self, approval_id: UUID) -> ApprovalResolution:
        self.approval_calls.append((approval_id, ApprovalDecision.APPROVE))  # type: ignore[union-attr]
        return ApprovalResolution(
            request_id=approval_id,
            run_id=self.run.id,
            decision=ApprovalDecision.APPROVE,
            action_fingerprint="a" * 64,
            resolved_at=datetime.now(UTC),
        )

    def reject(self, approval_id: UUID) -> ApprovalResolution:
        self.approval_calls.append((approval_id, ApprovalDecision.REJECT))  # type: ignore[union-attr]
        return ApprovalResolution(
            request_id=approval_id,
            run_id=self.run.id,
            decision=ApprovalDecision.REJECT,
            action_fingerprint="a" * 64,
            resolved_at=datetime.now(UTC),
        )

    def list_events(self, run_id: UUID):
        assert run_id == self.run.id
        return self.events_data


def _service() -> FakeService:
    return FakeService(Run(task="task"), events_data=({"version": 1, "event_type": "run.created"},))


def test_run_task_calls_service_and_emits_json(monkeypatch, tmp_path: Path) -> None:
    service = _service()
    monkeypatch.setattr(runs_cli, "get_run_service", lambda repo_root: service)
    result = CliRunner().invoke(app, ["run", "task", "fix bug", "--repo", str(tmp_path), "--json"])
    assert result.exit_code == 0
    assert '"task": "fix bug"' in result.stdout


def test_status_and_events_serialize_service_results(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(runs_cli, "get_run_service", lambda repo_root=None: service)
    run_id = str(service.run.id)
    status = CliRunner().invoke(app, ["runs", "status", run_id, "--json"])
    events = CliRunner().invoke(app, ["runs", "events", run_id, "--json"])
    assert status.exit_code == 0 and '"run_id"' in status.stdout
    assert events.exit_code == 0 and "run.created" in events.stdout


def test_approval_and_cancel_commands_return_nonzero_on_service_error(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr(runs_cli, "get_run_service", lambda repo_root=None: service)
    approval_id = str(uuid4())
    approved = CliRunner().invoke(app, ["runs", "approve", approval_id])
    rejected = CliRunner().invoke(app, ["runs", "reject", approval_id])
    cancelled = CliRunner().invoke(app, ["runs", "cancel", str(service.run.id)])
    assert approved.exit_code == 0 and "decision: approve" in approved.stdout
    assert rejected.exit_code == 0 and "decision: reject" in rejected.stdout
    assert cancelled.exit_code == 0 and "cancelled" in cancelled.stdout


def test_demo_dispatches_named_demo(monkeypatch, tmp_path: Path) -> None:
    called: list[str] = []
    monkeypatch.setattr(runs_cli, "run_demo", lambda name, repo: called.append(name) or {"demo": name})
    result = CliRunner().invoke(app, ["demo", "multi-agent", "--repo", str(tmp_path), "--json"])
    assert result.exit_code == 0
    assert called == ["multi-agent"]
    assert '"demo": "multi-agent"' in result.stdout


def test_default_factory_creates_and_cancels_a_real_local_run(tmp_path: Path) -> None:
    created = CliRunner().invoke(app, ["run", "task", "inspect", "--repo", str(tmp_path), "--json"])
    assert created.exit_code == 0
    run_id = json.loads(created.stdout)["id"]

    cancelled = CliRunner().invoke(
        app, ["runs", "cancel", run_id, "--repo", str(tmp_path), "--json"]
    )

    assert cancelled.exit_code == 0
    assert json.loads(cancelled.stdout)["status"] == "cancelled"
