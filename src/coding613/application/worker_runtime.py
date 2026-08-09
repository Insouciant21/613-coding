"""Run one role-scoped worker inside an owned sandbox."""

from __future__ import annotations

import fnmatch
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from coding613.adapters.sandbox.workspace import WorkspacePathError
from coding613.domain.sandbox import SandboxSpec, WorkArtifact
from coding613.domain.tasks import TaskNode
from coding613.domain.worker import WorkerContext
from coding613.ports.sandbox import SandboxRuntime

from .role_policies import ToolPolicy, role_policy


class WorkerRuntimeError(RuntimeError):
    """A role policy or worker lifecycle contract was violated."""


class WorkerRuntime:
    def __init__(self, loop_factory: Callable[[ToolPolicy], Any], sandbox_runtime: SandboxRuntime) -> None:
        self._loop_factory = loop_factory
        self._sandbox = sandbox_runtime
        self.events: list[tuple[str, dict[str, str]]] = []

    async def run(self, node: TaskNode, task_context: WorkerContext) -> WorkArtifact:
        policy = role_policy(node.role)
        spec = task_context.metadata.get("sandbox_spec")
        if not isinstance(spec, SandboxSpec):
            raise WorkerRuntimeError("task context requires a validated sandbox_spec")
        if spec.workspace_path != task_context.project_root.resolve():
            raise WorkerRuntimeError("sandbox workspace does not match task context")
        handle = self._sandbox.create(spec)
        self.events.append(("worker.created", {"node_id": node.id, "role": node.role.value}))
        try:
            loop = self._loop_factory(policy)
            result = loop.run(node, task_context.model_copy(update={"role": node.role}))
            await result if inspect.isawaitable(result) else None
            artifact = self._sandbox.export(handle)
            self._validate_artifact(artifact, node, policy)
            self.events.append(("worker.artifact", {"node_id": node.id, "role": node.role.value}))
            return artifact
        finally:
            self._sandbox.destroy(handle)
            self.events.append(("worker.destroyed", {"node_id": node.id, "role": node.role.value}))

    @staticmethod
    def _validate_artifact(artifact: WorkArtifact, node: TaskNode, policy: ToolPolicy) -> None:
        if not policy.allow_writes and artifact.changed_files:
            raise WorkerRuntimeError(f"{node.role.value} worker is read-only")
        write_set = node.declared_write_set
        for changed in artifact.changed_files:
            path = Path(changed)
            if path.is_absolute() or ".." in path.parts:
                raise WorkspacePathError(f"artifact path escapes repository: {changed}")
            if not any(
                fnmatch.fnmatchcase(changed, pattern)
                or changed == pattern
                or changed.startswith(pattern.rstrip("/") + "/")
                for pattern in write_set
            ):
                raise WorkerRuntimeError(f"artifact path outside write set: {changed}")
