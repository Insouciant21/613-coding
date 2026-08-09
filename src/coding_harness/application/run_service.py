"""Shared run use cases consumed by CLI and API adapters."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from coding_harness.application.approvals import (
    ApprovalDecision,
    ApprovalResolution,
    StaleApprovalError,
)
from coding_harness.application.loop import AgentLoop, LoopDependencies
from coding_harness.domain.models import (
    ApprovalRequest,
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

    def compare_and_set_run(self, expected: Run, replacement: Run) -> bool: ...

    def get_approval(self, request_id: UUID) -> ApprovalRequest | None: ...


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
        dependencies = self._get_dependencies(run)
        if run.state.is_terminal:
            return self._terminal_summary(run, dependencies)
        summary = self._loop.run(run_id, run.task, dependencies)
        return self._persist_status(run, summary)

    def approve(self, request_id: UUID) -> ApprovalResolution:
        return self._resolve(request_id, ApprovalDecision.APPROVE)

    def reject(self, request_id: UUID) -> ApprovalResolution:
        return self._resolve(request_id, ApprovalDecision.REJECT)

    def cancel(self, run_id: UUID) -> RunSummary:
        run = self._require_run(run_id)
        dependencies = self._get_dependencies(run)
        if run.state.is_terminal:
            return self._terminal_summary(run, dependencies)
        summary = self._loop.cancel(run_id, run.task, dependencies)
        return self._persist_status(run, summary)

    def get_summary(self, run_id: UUID) -> RunSummary:
        run = self._require_run(run_id)
        dependencies = self._get_dependencies(run)
        if dependencies.sessions.get_loop_session(run_id) is None:
            return RunSummary(
                run_id=run.id,
                status=run.state,
                stop_reason=run.stop_reason,
            )
        return self._loop.get_summary(run_id, dependencies)

    def _resolve(
        self, request_id: UUID, decision: ApprovalDecision
    ) -> ApprovalResolution:
        request = self._store.get_approval(request_id)
        if request is None or request.run_id is None:
            raise KeyError(f"unknown approval: {request_id}")
        run = self._require_run(request.run_id)
        if run.state.is_terminal:
            raise StaleApprovalError("cannot resolve approval for a terminal run")
        dependencies = self._get_dependencies(run)
        return dependencies.approvals.resolve(request_id, decision)

    def _get_dependencies(self, run: Run) -> LoopDependencies:
        dependencies = self._dependencies.get(run.id)
        if dependencies is None:
            dependencies = self._dependency_factory(run)
            self._dependencies[run.id] = dependencies
        return dependencies

    def _require_run(self, run_id: UUID) -> Run:
        run = self._store.get_run(run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        return run

    def _persist_status(self, run: Run, summary: RunSummary) -> RunSummary:
        data = run.model_dump()
        data.update(
            state=summary.status,
            stop_reason=summary.stop_reason if summary.status.is_terminal else None,
            updated_at=datetime.now(UTC),
        )
        replacement = Run.model_validate(data)
        if self._store.compare_and_set_run(run, replacement):
            return summary
        authoritative = self._require_run(run.id)
        return self._with_run_status(summary, authoritative)

    def _terminal_summary(
        self,
        run: Run,
        dependencies: LoopDependencies,
    ) -> RunSummary:
        summary = self._loop.get_summary(run.id, dependencies)
        return self._with_run_status(summary, run)

    @staticmethod
    def _with_run_status(summary: RunSummary, run: Run) -> RunSummary:
        return summary.model_copy(
            update={
                "status": run.state,
                "stop_reason": run.stop_reason,
            }
        )
