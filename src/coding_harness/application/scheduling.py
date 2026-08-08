"""Deterministic ready-node selection."""

from __future__ import annotations

from collections.abc import Sequence

from coding_harness.domain.tasks import TaskGraph, TaskNode


class Scheduler:
    def select_ready(self, graph: TaskGraph) -> tuple[TaskNode, ...]:
        return graph.ready_nodes()

    async def next_ready(self, graph: TaskGraph) -> Sequence[TaskNode]:
        return self.select_ready(graph)
