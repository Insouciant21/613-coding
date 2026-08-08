from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from coding_harness.application.tool_registry import (
    DuplicateToolError,
    ToolRegistry,
    ToolSchemaError,
    UnknownToolError,
)
from coding_harness.domain.actions import ToolCall
from coding_harness.domain.models import PermissionMode
from coding_harness.ports.llm import ToolDefinition
from coding_harness.ports.tools import ToolContext, ToolResult


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        self.calls.append(call)
        return ToolResult(call=call, success=True, output=str(context.repository_root))


def definition() -> ToolDefinition:
    return ToolDefinition(
        name="read_file",
        description="Read one file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    )


def context(root: Path) -> ToolContext:
    return ToolContext(
        run_id=uuid4(), repository_root=root, permission_mode=PermissionMode.BALANCED
    )


def test_registry_validates_and_dispatches(tmp_path: Path) -> None:
    registry = ToolRegistry()
    executor = RecordingExecutor()
    registry.register(definition(), executor)
    call = ToolCall(name="read_file", arguments={"path": "a.py"})
    assert registry.dispatch(call, context(tmp_path)).success
    assert executor.calls == [call]


def test_registry_rejects_duplicate_unknown_and_invalid_arguments(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(definition(), RecordingExecutor())
    with pytest.raises(DuplicateToolError):
        registry.register(definition(), RecordingExecutor())
    with pytest.raises(UnknownToolError):
        registry.dispatch(ToolCall(name="missing", arguments={}), context(tmp_path))
    with pytest.raises(ToolSchemaError):
        registry.dispatch(ToolCall(name="read_file", arguments={"path": 1}), context(tmp_path))
