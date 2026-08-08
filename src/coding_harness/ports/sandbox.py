"""Sandbox runtime port."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from coding_harness.domain.sandbox import (
    CommandResult,
    SandboxHandle,
    SandboxSpec,
    WorkArtifact,
)


class SandboxRuntime(Protocol):
    def create(self, spec: SandboxSpec) -> SandboxHandle: ...

    def execute(self, handle: SandboxHandle, command: Sequence[str]) -> CommandResult: ...

    def export(self, handle: SandboxHandle) -> WorkArtifact: ...

    def destroy(self, handle: SandboxHandle) -> None: ...
