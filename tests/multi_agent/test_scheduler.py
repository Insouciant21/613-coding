from __future__ import annotations

import asyncio

from coding613.application.scheduling import Scheduler
from coding613.domain.tasks import TaskGraph, TaskNode, WorkerRole


def test_scheduler_selects_ready_nodes_in_stable_order() -> None:
    graph = TaskGraph(
        nodes=(
            TaskNode(id="b", title="b", role=WorkerRole.TESTER),
            TaskNode(id="a", title="a", role=WorkerRole.PLANNER),
        )
    )

    assert [node.id for node in Scheduler().select_ready(graph)] == ["a", "b"]


def test_async_scheduler_matches_sync_selection() -> None:
    graph = TaskGraph(nodes=(TaskNode(id="a", title="a", role=WorkerRole.PLANNER),))

    result = asyncio.run(Scheduler().next_ready(graph))

    assert [node.id for node in result] == ["a"]
