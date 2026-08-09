"""Shared run use cases consumed by CLI and API adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from coding613.application.approvals import (
    ApprovalDecision,
    ApprovalResolution,
    StaleApprovalError,
)
from coding613.application.loop import AgentLoop, LoopDependencies
from coding613.application.progress import CancellationToken
from coding613.domain.models import (
    ApprovalRequest,
    PermissionMode,
    Run,
    RunSummary,
)
from coding613.domain.models_base import DomainModel
from coding613.ports.progress import ProgressSink


class RunRequest(DomainModel):
    task: str
    project_id: UUID | None = None
    session_id: UUID | None = None
    permission_mode: PermissionMode | None = None


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
        self._active_runs: set[UUID] = set()

    def create_run(self, request: RunRequest) -> Run:
        run = Run(
            project_id=request.project_id,
            session_id=request.session_id,
            task=request.task,
            permission_mode=request.permission_mode or PermissionMode.BALANCED,
        )
        self._store.create_run(run)
        return run

    def resume(
        self,
        run_id: UUID,
        *,
        progress: ProgressSink | None = None,
        cancellation: CancellationToken | None = None,
    ) -> RunSummary:
        run = self._require_run(run_id)
        dependencies = self._get_dependencies(run)
        if progress is not None or cancellation is not None:
            dependencies = replace(
                dependencies,
                progress=progress or dependencies.progress,
                cancellation=cancellation or dependencies.cancellation,
            )
            self._dependencies[run.id] = dependencies
        if run.state.is_terminal:
            return self._terminal_summary(run, dependencies)
        dependencies.cancellation.reset()
        self._active_runs.add(run_id)
        try:
            summary = self._loop.run(run_id, run.task, dependencies)
        finally:
            self._active_runs.discard(run_id)
        return self._persist_status(run, summary)

    def pause(self, run_id: UUID) -> RunSummary:
        run = self._require_run(run_id)
        dependencies = self._get_dependencies(run)
        dependencies.cancellation.cancel()
        if run_id in self._active_runs:
            return self.get_summary(run_id)
        if run.state.is_terminal:
            return self._terminal_summary(run, dependencies)
        summary = self._loop.pause(run_id, run.task, dependencies)
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
        dependencies.cancellation.cancel()
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

    def get_approval(self, request_id: UUID) -> ApprovalRequest:
        request = self._store.get_approval(request_id)
        if request is None:
            raise KeyError(f"unknown approval: {request_id}")
        return request

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
