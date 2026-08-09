from __future__ import annotations

import pytest

from coding613.domain.tasks import (
    GraphValidationError,
    TaskGraph,
    TaskNode,
    TaskState,
    WorkerRole,
)


def _node(node_id: str, *, deps: tuple[str, ...] = (), writes: tuple[str, ...] = ()) -> TaskNode:
    return TaskNode(id=node_id, title=node_id, role=WorkerRole.CODER, dependencies=deps, declared_write_set=writes)


def test_ready_nodes_follow_dependencies_and_transitions() -> None:
    graph = TaskGraph(nodes=(_node("a"), _node("b", deps=("a",))))

    assert [node.id for node in graph.ready_nodes()] == ["a"]
    running = graph.transition("a", TaskState.RUNNING)
    completed = running.transition("a", TaskState.SUCCEEDED)

    assert [node.id for node in completed.ready_nodes()] == ["b"]


def test_graph_rejects_missing_dependencies_and_cycles() -> None:
    with pytest.raises(GraphValidationError, match="missing"):
        TaskGraph(nodes=(_node("a", deps=("missing",)),))
    with pytest.raises(GraphValidationError, match="cycle"):
        TaskGraph(nodes=(_node("a", deps=("b",)), _node("b", deps=("a",))))


def test_graph_rejects_unserialized_overlapping_write_sets() -> None:
    with pytest.raises(GraphValidationError, match="overlap"):
        TaskGraph(
            nodes=(
                _node("a", writes=("src/app.py",)),
                _node("b", writes=("src",)),
            )
        )


def test_dependency_serializes_overlapping_write_sets() -> None:
    graph = TaskGraph(
        nodes=(
            _node("a", writes=("src/app.py",)),
            _node("b", deps=("a",), writes=("src",)),
        )
    )

    assert graph.nodes[1].declared_write_set == ("src",)


def test_invalid_transition_is_rejected() -> None:
    graph = TaskGraph(nodes=(_node("a"),))

    with pytest.raises(GraphValidationError, match="transition"):
        graph.transition("a", TaskState.SUCCEEDED)
