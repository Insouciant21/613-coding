"""Deterministic sandbox runtime for contract and application tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from coding613.domain.sandbox import (
    CommandResult,
    SandboxHandle,
    SandboxSpec,
    WorkArtifact,
)


class FakeSandboxRuntime:
    def __init__(
        self,
        command_results: Sequence[CommandResult] = (),
        artifact: WorkArtifact | None = None,
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._command_results = list(command_results)
        self._artifact = artifact or WorkArtifact()
        self._handles: dict[str, bool] = {}

    def create(self, spec: SandboxSpec) -> SandboxHandle:
        handle = SandboxHandle(workspace_path=spec.workspace_path)
        self._handles[str(handle.id)] = True
        self.calls.append(("create", spec))
        return handle

    def execute(self, handle: SandboxHandle, command: Sequence[str]) -> CommandResult:
        self._require_live(handle)
        command_tuple = tuple(command)
        if not command_tuple:
            raise ValueError("command must not be empty")
        self.calls.append(("execute", (handle, command_tuple)))
        if self._command_results:
            return self._command_results.pop(0)
        return CommandResult(command=command_tuple, exit_code=0)

    def export(self, handle: SandboxHandle) -> WorkArtifact:
        self._require_live(handle)
        self.calls.append(("export", handle))
        return self._artifact

    def destroy(self, handle: SandboxHandle) -> None:
        self._require_live(handle)
        self._handles[str(handle.id)] = False
        self.calls.append(("destroy", handle))

    def _require_live(self, handle: SandboxHandle) -> None:
        if self._handles.get(str(handle.id)) is not True:
            raise RuntimeError("sandbox handle is unknown or destroyed")
