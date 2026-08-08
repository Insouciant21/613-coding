"""Dependency-aware task graph values for Supervisor orchestration."""

from __future__ import annotations

import fnmatch
from enum import StrEnum
from pathlib import Path

from pydantic import ConfigDict, Field, ValidationError, model_validator

from .models_base import DomainModel


class GraphValidationError(ValueError):
    """A task graph violates dependency or write ownership rules."""


class WorkerRole(StrEnum):
    PLANNER = "planner"
    CODER = "coder"
    TESTER = "tester"
    REVIEWER = "reviewer"
    SECURITY = "security"


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class TaskNode(DomainModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    role: WorkerRole
    dependencies: tuple[str, ...] = ()
    declared_write_set: tuple[str, ...] = ()
    max_attempts: int = Field(default=1, ge=1)
    attempts: int = Field(default=0, ge=0)
    state: TaskState = TaskState.PENDING

    @model_validator(mode="after")
    def normalize_paths(self) -> TaskNode:
        normalized: list[str] = []
        for value in self.declared_write_set:
            path = Path(value)
            if path.is_absolute() or ".." in path.parts or path.as_posix() in {"", "."}:
                raise GraphValidationError(f"write-set path must be repository-relative: {value}")
            normalized.append(path.as_posix())
        object.__setattr__(self, "declared_write_set", tuple(sorted(set(normalized))))
        return self


class TaskGraph(DomainModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    nodes: tuple[TaskNode, ...] = ()

    def __init__(self, **data: object) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            graph_error = next(
                (
                    error["ctx"]["error"]
                    for error in exc.errors()
                    if error["type"] == "value_error" and isinstance(error.get("ctx", {}).get("error"), GraphValidationError)
                ),
                None,
            )
            if graph_error is not None:
                raise graph_error from exc
            raise

    @model_validator(mode="after")
    def validate_graph(self) -> TaskGraph:
        by_id = {node.id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise GraphValidationError("task graph contains duplicate node ids")
        for node in self.nodes:
            missing = set(node.dependencies) - by_id.keys()
            if missing:
                raise GraphValidationError(f"missing dependency: {min(missing)}")
        self._reject_cycles(by_id)
        for index, left in enumerate(self.nodes):
            for right in self.nodes[index + 1 :]:
                if not _write_sets_overlap(left.declared_write_set, right.declared_write_set):
                    continue
                if not self._depends_on(left.id, right.id, by_id) and not self._depends_on(right.id, left.id, by_id):
                    raise GraphValidationError(f"write-set overlap requires dependency: {left.id}/{right.id}")
        return self

    def ready_nodes(self) -> tuple[TaskNode, ...]:
        by_id = {node.id: node for node in self.nodes}
        return tuple(
            sorted(
                (
                    node
                    for node in self.nodes
                    if node.state is TaskState.PENDING
                    and all(by_id[dependency].state is TaskState.SUCCEEDED for dependency in node.dependencies)
                ),
                key=lambda node: node.id,
            )
        )

    def transition(self, node_id: str, target: TaskState) -> TaskGraph:
        allowed = {
            TaskState.PENDING: {TaskState.RUNNING, TaskState.CANCELLED, TaskState.BLOCKED},
            TaskState.RUNNING: {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED},
            TaskState.FAILED: {TaskState.PENDING, TaskState.CANCELLED},
        }
        nodes = list(self.nodes)
        for index, node in enumerate(nodes):
            if node.id != node_id:
                continue
            if target not in allowed.get(node.state, set()):
                raise GraphValidationError(f"invalid transition {node.state}->{target}")
            nodes[index] = node.model_copy(update={"state": target, "attempts": node.attempts + (target is TaskState.RUNNING)})
            return TaskGraph(nodes=tuple(nodes))
        raise GraphValidationError(f"unknown task node: {node_id}")

    @staticmethod
    def _reject_cycles(by_id: dict[str, TaskNode]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise GraphValidationError("task graph contains a cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in by_id[node_id].dependencies:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in by_id:
            visit(node_id)

    @staticmethod
    def _depends_on(node_id: str, target: str, by_id: dict[str, TaskNode]) -> bool:
        pending = list(by_id[node_id].dependencies)
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(by_id[current].dependencies)
        return False


def _write_sets_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    for first in left:
        for second in right:
            if first == second or first.startswith(second.rstrip("/") + "/") or second.startswith(first.rstrip("/") + "/"):
                return True
            if fnmatch.fnmatchcase(first, second) or fnmatch.fnmatchcase(second, first):
                return True
    return False
