from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from coding_harness.adapters.sandbox.fake import FakeSandboxRuntime
from coding_harness.application.worker_runtime import WorkerRuntime, WorkerRuntimeError
from coding_harness.domain.sandbox import SandboxSpec, WorkArtifact
from coding_harness.domain.tasks import TaskNode, WorkerRole
from coding_harness.domain.worker import WorkerContext


def _context(tmp_path: Path, spec: SandboxSpec) -> WorkerContext:
    return WorkerContext(run_id=uuid4(), project_root=tmp_path, metadata={"sandbox_spec": spec})


class FakeLoop:
    def __init__(self, artifact: WorkArtifact | None = None, error: Exception | None = None) -> None:
        self.artifact = artifact or WorkArtifact(summary="loop artifact")
        self.error = error

    async def run(self, node: TaskNode, context: WorkerContext) -> WorkArtifact:
        if self.error is not None:
            raise self.error
        return self.artifact


def _spec(tmp_path: Path) -> SandboxSpec:
    return SandboxSpec(
        image_digest="sha256:" + "a" * 64,
        workspace_path=tmp_path,
        worker_id="worker-1",
    )


def test_worker_runtime_creates_exports_and_destroys_sandbox(tmp_path: Path) -> None:
    sandbox = FakeSandboxRuntime(artifact=WorkArtifact(summary="exported"))
    runtime = WorkerRuntime(lambda policy: FakeLoop(), sandbox)
    node = TaskNode(id="code", title="code", role=WorkerRole.CODER, declared_write_set=("main.py",))

    artifact = asyncio.run(runtime.run(node, _context(tmp_path, _spec(tmp_path))))

    assert artifact.summary == "exported"
    assert [call[0] for call in sandbox.calls] == ["create", "export", "destroy"]


def test_read_only_worker_rejects_produced_changes(tmp_path: Path) -> None:
    sandbox = FakeSandboxRuntime(artifact=WorkArtifact(changed_files=("main.py",)))
    runtime = WorkerRuntime(lambda policy: FakeLoop(), sandbox)
    node = TaskNode(id="test", title="test", role=WorkerRole.TESTER)

    with pytest.raises(WorkerRuntimeError, match="read-only"):
        asyncio.run(runtime.run(node, _context(tmp_path, _spec(tmp_path))))
    assert [call[0] for call in sandbox.calls] == ["create", "export", "destroy"]


def test_worker_runtime_destroys_sandbox_when_loop_fails(tmp_path: Path) -> None:
    sandbox = FakeSandboxRuntime()
    runtime = WorkerRuntime(lambda policy: FakeLoop(error=RuntimeError("loop failed")), sandbox)
    node = TaskNode(id="code", title="code", role=WorkerRole.CODER)

    with pytest.raises(RuntimeError, match="loop failed"):
        asyncio.run(runtime.run(node, _context(tmp_path, _spec(tmp_path))))
    assert [call[0] for call in sandbox.calls] == ["create", "destroy"]
