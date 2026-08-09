from __future__ import annotations

import asyncio
from pathlib import Path

from coding613.application.supervisor import Supervisor
from coding613.domain.sandbox import WorkArtifact
from coding613.domain.tasks import TaskNode, WorkerRole
from coding613.domain.worker import WorkerContext


class ScriptedWorker:
    def __init__(self, outcomes: dict[str, list[object]]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    async def run(self, node: TaskNode, context: WorkerContext) -> WorkArtifact:
        del context
        self.calls.append(node.id)
        outcome = self.outcomes.setdefault(node.id, [WorkArtifact(summary=node.id)]).pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome if isinstance(outcome, WorkArtifact) else WorkArtifact(summary=node.id)


def _supervisor(tmp_path: Path, worker: ScriptedWorker, **kwargs: object) -> Supervisor:
    return Supervisor(
        workers={role: worker for role in WorkerRole},
        project_root=tmp_path,
        **kwargs,
    )


def test_supervisor_runs_dependencies_in_order_and_returns_artifacts(tmp_path: Path) -> None:
    worker = ScriptedWorker({})
    supervisor = _supervisor(tmp_path, worker)
    graph_id = supervisor.create_graph(
        (
            TaskNode(id="b", title="b", role=WorkerRole.TESTER, dependencies=("a",)),
            TaskNode(id="a", title="a", role=WorkerRole.PLANNER),
        )
    )

    summary = asyncio.run(supervisor.run(graph_id))

    assert summary.state == "completed"
    assert worker.calls == ["a", "b"]
    assert summary.completed_nodes == ("a", "b")


def test_supervisor_retries_failed_node_within_node_budget(tmp_path: Path) -> None:
    worker = ScriptedWorker({"a": [RuntimeError("first"), WorkArtifact(summary="ok")]})
    supervisor = _supervisor(tmp_path, worker)
    graph_id = supervisor.create_graph(
        (TaskNode(id="a", title="a", role=WorkerRole.CODER, max_attempts=2),)
    )

    summary = asyncio.run(supervisor.run(graph_id))

    assert summary.state == "completed"
    assert summary.total_calls == 2


def test_supervisor_propagates_failure_without_running_dependents(tmp_path: Path) -> None:
    worker = ScriptedWorker({"a": [RuntimeError("broken")]})
    supervisor = _supervisor(tmp_path, worker)
    graph_id = supervisor.create_graph(
        (
            TaskNode(id="a", title="a", role=WorkerRole.CODER),
            TaskNode(id="b", title="b", role=WorkerRole.TESTER, dependencies=("a",)),
        )
    )

    summary = asyncio.run(supervisor.run(graph_id))

    assert summary.state == "failed"
    assert summary.failed_nodes == ("a",)
    assert worker.calls == ["a"]


def test_supervisor_enforces_total_call_budget(tmp_path: Path) -> None:
    worker = ScriptedWorker({})
    supervisor = _supervisor(tmp_path, worker, max_total_calls=1)
    graph_id = supervisor.create_graph(
        (
            TaskNode(id="a", title="a", role=WorkerRole.PLANNER),
            TaskNode(id="b", title="b", role=WorkerRole.TESTER),
        )
    )

    summary = asyncio.run(supervisor.run(graph_id))

    assert summary.state == "budget_exhausted"
    assert summary.total_calls == 1


def test_supervisor_pause_resume_and_cancel_are_explicit(tmp_path: Path) -> None:
    worker = ScriptedWorker({})
    supervisor = _supervisor(tmp_path, worker)
    graph_id = supervisor.create_graph((TaskNode(id="a", title="a", role=WorkerRole.PLANNER),))
    supervisor.pause(graph_id)

    paused = asyncio.run(supervisor.run(graph_id))
    assert paused.state == "paused"
    supervisor.resume(graph_id)
    assert asyncio.run(supervisor.run(graph_id)).state == "completed"

    cancelled_id = supervisor.create_graph((TaskNode(id="b", title="b", role=WorkerRole.PLANNER),))
    supervisor.cancel(cancelled_id)
    assert asyncio.run(supervisor.run(cancelled_id)).state == "cancelled"
