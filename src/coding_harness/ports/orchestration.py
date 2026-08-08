"""Ports for dependency-aware multi-agent orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from coding_harness.domain.sandbox import WorkArtifact
from coding_harness.domain.tasks import TaskGraph, TaskNode
from coding_harness.domain.worker import WorkerContext


class Worker(Protocol):
    async def run(self, node: TaskNode, context: WorkerContext) -> WorkArtifact: ...


class TaskScheduler(Protocol):
    async def next_ready(self, graph: TaskGraph) -> Sequence[TaskNode]: ...
