from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from coding_harness.api.app import create_app
from coding_harness.application.approvals import ApprovalDecision, ApprovalResolution
from coding_harness.domain.models import Run, RunState, RunSummary, StopReason


@dataclass
class FakeRunService:
    run: Run

    def create_run(self, request):
        self.run = self.run.model_copy(update={"task": request.task})
        return self.run

    def get_summary(self, run_id: UUID) -> RunSummary:
        return RunSummary(run_id=run_id, status=self.run.state, stop_reason=self.run.stop_reason)

    def approve(self, request_id: UUID) -> ApprovalResolution:
        return ApprovalResolution(
            request_id=request_id,
            run_id=self.run.id,
            decision=ApprovalDecision.APPROVE,
            action_fingerprint="a" * 64,
            resolved_at=datetime.now(UTC),
        )

    def reject(self, request_id: UUID) -> ApprovalResolution:
        return ApprovalResolution(
            request_id=request_id,
            run_id=self.run.id,
            decision=ApprovalDecision.REJECT,
            action_fingerprint="a" * 64,
            resolved_at=datetime.now(UTC),
        )

    def resume(self, run_id: UUID) -> RunSummary:
        return self.get_summary(run_id)

    def cancel(self, run_id: UUID) -> RunSummary:
        return RunSummary(run_id=run_id, status=RunState.CANCELLED, stop_reason=StopReason.CANCELLED)


@dataclass
class FakeServices:
    run_service: FakeRunService
    events: tuple[dict[str, object], ...] = (
        {"version": 1, "event_type": "run.created"},
        {"version": 2, "event_type": "run.completed"},
    )

    def list_events(self, run_id: UUID):
        return self.events


def client() -> tuple[TestClient, FakeServices]:
    services = FakeServices(FakeRunService(Run(task="old")))
    return TestClient(create_app(services)), services


def test_create_run_validates_and_calls_shared_service() -> None:
    test_client, services = client()
    response = test_client.post("/api/runs", json={"task": "fix bug"})
    assert response.status_code == 201
    assert response.json()["task"] == "fix bug"
    assert services.run_service.run.task == "fix bug"


def test_run_lifecycle_and_approval_routes_return_service_models() -> None:
    test_client, services = client()
    run_id = str(services.run_service.run.id)
    approval_id = str(uuid4())
    assert test_client.get(f"/api/runs/{run_id}").status_code == 200
    assert test_client.post(f"/api/approvals/{approval_id}", json={"decision": "approve"}).status_code == 200
    assert test_client.post(f"/api/runs/{run_id}/resume").status_code == 200
    assert test_client.post(f"/api/runs/{run_id}/cancel").status_code == 200


def test_events_are_ordered_and_health_is_public() -> None:
    test_client, services = client()
    run_id = str(services.run_service.run.id)
    events = test_client.get(f"/api/runs/{run_id}/events")
    assert events.status_code == 200
    assert [item["version"] for item in events.json()] == [1, 2]
    assert test_client.get("/healthz").json() == {"status": "ok"}


def test_invalid_request_and_service_error_are_safe() -> None:
    test_client, services = client()
    assert test_client.post("/api/runs", json={"task": ""}).status_code == 422

    def fail(_run_id: UUID):
        raise KeyError("secret-internal-id")

    services.run_service.get_summary = fail  # type: ignore[method-assign]
    response = test_client.get(f"/api/runs/{services.run_service.run.id}")
    assert response.status_code == 404
    assert "secret-internal-id" not in response.text
