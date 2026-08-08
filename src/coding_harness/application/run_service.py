"""Shared run use cases consumed by CLI and API adapters."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from coding_harness.application.approvals import (
    ApprovalDecision,
    ApprovalResolution,
)
from coding_harness.application.loop import AgentLoop, LoopDependencies
from coding_harness.domain.models import (
    PermissionMode,
    Run,
    RunSummary,
)
from coding_harness.domain.models_base import DomainModel


class RunRequest(DomainModel):
    task: str
    project_id: UUID | None = None
    permission_mode: PermissionMode = PermissionMode.BALANCED


class RunStore(Protocol):
    def create_run(self, run: Run) -> None: ...

    def get_run(self, run_id: UUID) -> Run | None: ...

    def update_run(self, run: Run) -> None: ...


class RunService:
    def __init__(
        self,
        store: RunStore,
        loop: AgentLoop,
        dependencies: Callable[[Run], LoopDependencies],
    ) -> None:
        self._store = store
        self._loop = loop
        self._dependency_factory = dependencies
        self._dependencies: dict[UUID, LoopDependencies] = {}
        self._summaries: dict[UUID, RunSummary] = {}
        self._approval_runs: dict[UUID, UUID] = {}

    def create_run(self, request: RunRequest) -> Run:
        run = Run(
            project_id=request.project_id,
            task=request.task,
            permission_mode=request.permission_mode,
        )
        self._store.create_run(run)
        return run

    def resume(self, run_id: UUID) -> RunSummary:
        run = self._require_run(run_id)
        dependencies = self._dependencies.get(run_id)
        if dependencies is None:
            dependencies = self._dependency_factory(run)
            self._dependencies[run_id] = dependencies
        summary = self._loop.run(run_id, run.task, dependencies)
        self._summaries[run_id] = summary
        for request_id in summary.approvals:
            self._approval_runs[request_id] = run_id
        self._persist_status(run, summary)
        return summary

    def approve(self, request_id: UUID) -> ApprovalResolution:
        return self._resolve(request_id, ApprovalDecision.APPROVE)

    def reject(self, request_id: UUID) -> ApprovalResolution:
        return self._resolve(request_id, ApprovalDecision.REJECT)

    def cancel(self, run_id: UUID) -> RunSummary:
        self._loop.cancel(run_id)
        return self.resume(run_id)

    def get_summary(self, run_id: UUID) -> RunSummary:
        try:
            return self._summaries[run_id]
        except KeyError as error:
            raise KeyError(f"run has no summary: {run_id}") from error

    def _resolve(
        self, request_id: UUID, decision: ApprovalDecision
    ) -> ApprovalResolution:
        try:
            run_id = self._approval_runs[request_id]
            dependencies = self._dependencies[run_id]
        except KeyError as error:
            raise KeyError(f"unknown approval: {request_id}") from error
        return dependencies.approvals.resolve(request_id, decision)

    def _require_run(self, run_id: UUID) -> Run:
        run = self._store.get_run(run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        return run

    def _persist_status(self, run: Run, summary: RunSummary) -> None:
        data = run.model_dump()
        data.update(
            state=summary.status,
            stop_reason=summary.stop_reason if summary.status.is_terminal else None,
            updated_at=datetime.now(UTC),
        )
        self._store.update_run(Run.model_validate(data))
