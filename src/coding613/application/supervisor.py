"""Dependency-aware multi-agent Supervisor."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from coding613.domain.models_base import DomainModel
from coding613.domain.sandbox import WorkArtifact
from coding613.domain.tasks import TaskGraph, TaskNode, TaskState, WorkerRole
from coding613.domain.worker import WorkerContext
from coding613.ports.orchestration import Worker

from .scheduling import Scheduler


class SupervisorSummary(DomainModel):
    graph_id: str
    state: str
    completed_nodes: tuple[str, ...] = ()
    failed_nodes: tuple[str, ...] = ()
    cancelled_nodes: tuple[str, ...] = ()
    total_calls: int = 0
    artifacts: dict[str, WorkArtifact] = Field(default_factory=dict)
    events: tuple[str, ...] = ()
    feedback_repaired: bool = False
    approval_granted: bool = False
    integration_applied: bool = False
    final_validation_passed: bool = False


class Supervisor:
    def __init__(
        self,
        workers: Mapping[WorkerRole, Worker],
        project_root: Path,
        scheduler: Scheduler | None = None,
        max_total_calls: int = 100,
    ) -> None:
        if max_total_calls < 1:
            raise ValueError("max_total_calls must be positive")
        self._workers = dict(workers)
        self._project_root = project_root.expanduser().resolve()
        self._scheduler = scheduler or Scheduler()
        self._max_total_calls = max_total_calls
        self._graphs: dict[str, TaskGraph] = {}
        self._artifacts: dict[str, dict[str, WorkArtifact]] = {}
        self._calls: dict[str, int] = {}
        self._events: dict[str, list[str]] = {}
        self._paused: set[str] = set()
        self._cancelled: set[str] = set()

    def create_graph(self, task: TaskGraph | Sequence[TaskNode]) -> str:
        graph = task if isinstance(task, TaskGraph) else TaskGraph(nodes=tuple(task))
        graph_id = str(uuid4())
        self._graphs[graph_id] = graph
        self._artifacts[graph_id] = {}
        self._calls[graph_id] = 0
        self._events[graph_id] = ["graph.created"]
        return graph_id

    async def run(self, graph_id: str) -> SupervisorSummary:
        graph = self._graphs[graph_id]
        if graph_id in self._cancelled:
            return self._summary(graph_id, "cancelled")
        if graph_id in self._paused:
            return self._summary(graph_id, "paused")
        while True:
            if graph_id in self._cancelled:
                return self._summary(graph_id, "cancelled")
            if graph_id in self._paused:
                self._graphs[graph_id] = graph
                return self._summary(graph_id, "paused")
            ready = list(self._scheduler.select_ready(graph))
            if not ready:
                self._graphs[graph_id] = graph
                if all(node.state is TaskState.SUCCEEDED for node in graph.nodes):
                    return self._summary(graph_id, "completed")
                if any(node.state is TaskState.FAILED for node in graph.nodes):
                    return self._summary(graph_id, "failed")
                return self._summary(graph_id, "failed")
            remaining = self._max_total_calls - self._calls[graph_id]
            if remaining <= 0:
                self._graphs[graph_id] = graph
                self._events[graph_id].append("budget.exhausted")
                return self._summary(graph_id, "budget_exhausted")
            budget_limited = len(ready) > remaining
            ready = ready[:remaining]
            running_ids = [node.id for node in ready]
            for node in ready:
                graph = graph.transition(node.id, TaskState.RUNNING)
            self._events[graph_id].extend(f"node.started:{node_id}" for node_id in running_ids)
            results = await asyncio.gather(
                *(self._run_worker(graph_id, node) for node in ready),
                return_exceptions=True,
            )
            self._calls[graph_id] += len(ready)
            for node, result in zip(ready, results, strict=True):
                if isinstance(result, BaseException):
                    graph = graph.transition(node.id, TaskState.FAILED)
                    updated = next(item for item in graph.nodes if item.id == node.id)
                    if updated.attempts < updated.max_attempts:
                        graph = graph.transition(node.id, TaskState.PENDING)
                        self._events[graph_id].append(f"node.retry:{node.id}")
                    else:
                        self._events[graph_id].append(f"node.failed:{node.id}")
                    continue
                graph = graph.transition(node.id, TaskState.SUCCEEDED)
                self._artifacts[graph_id][node.id] = result
                self._events[graph_id].append(f"node.succeeded:{node.id}")
            self._graphs[graph_id] = graph
            if budget_limited:
                self._events[graph_id].append("budget.exhausted")
                return self._summary(graph_id, "budget_exhausted")

    def pause(self, graph_id: str) -> None:
        self._require_graph(graph_id)
        self._paused.add(graph_id)
        self._events[graph_id].append("graph.paused")

    def resume(self, graph_id: str) -> None:
        self._require_graph(graph_id)
        self._paused.discard(graph_id)
        self._events[graph_id].append("graph.resumed")

    def cancel(self, graph_id: str) -> None:
        self._require_graph(graph_id)
        self._cancelled.add(graph_id)
        self._events[graph_id].append("graph.cancelled")

    async def _run_worker(self, graph_id: str, node: TaskNode) -> WorkArtifact:
        worker = self._workers.get(node.role)
        if worker is None:
            raise RuntimeError(f"no worker registered for role {node.role.value}")
        context = WorkerContext(
            run_id=uuid4(),
            project_root=self._project_root,
            prior_artifacts=tuple(self._artifacts[graph_id].values()),
            metadata={"graph_id": graph_id, "node_id": node.id},
            role=node.role,
        )
        return await worker.run(node, context)

    def _summary(self, graph_id: str, state: str) -> SupervisorSummary:
        graph = self._graphs[graph_id]
        return SupervisorSummary(
            graph_id=graph_id,
            state=state,
            completed_nodes=tuple(sorted(node.id for node in graph.nodes if node.state is TaskState.SUCCEEDED)),
            failed_nodes=tuple(sorted(node.id for node in graph.nodes if node.state is TaskState.FAILED)),
            cancelled_nodes=tuple(sorted(node.id for node in graph.nodes if node.state is TaskState.CANCELLED)),
            total_calls=self._calls[graph_id],
            artifacts=dict(self._artifacts[graph_id]),
            events=tuple(self._events[graph_id]),
        )

    def _require_graph(self, graph_id: str) -> None:
        if graph_id not in self._graphs:
            raise KeyError(graph_id)
