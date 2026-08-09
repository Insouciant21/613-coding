from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from coding613.domain.sandbox import WorkArtifact
from coding613.domain.tasks import TaskNode, WorkerRole
from coding613.domain.worker import WorkerContext
from coding613.ports.orchestration import Worker


def test_worker_roles_and_context_are_explicit(tmp_path: Path) -> None:
    node = TaskNode(id="plan", title="plan", role=WorkerRole.PLANNER)
    context = WorkerContext(run_id=uuid4(), project_root=tmp_path)

    assert node.role is WorkerRole.PLANNER
    assert context.project_root == tmp_path.resolve()
    assert isinstance(WorkArtifact(), WorkArtifact)


def test_worker_protocol_accepts_async_artifact_result() -> None:
    class StubWorker:
        async def run(self, node: TaskNode, context: WorkerContext) -> WorkArtifact:
            return WorkArtifact(summary=f"{node.id}:{context.run_id}")

    worker: Worker = StubWorker()
    result = asyncio.run(
        worker.run(
            TaskNode(id="test", title="test", role=WorkerRole.TESTER),
            WorkerContext(run_id=uuid4(), project_root=Path(".")),
        )
    )

    assert result.summary.startswith("test:")
