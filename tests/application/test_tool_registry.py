from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from coding613.adapters.tools.dependencies import DependencyInstallResult
from coding613.adapters.tools.filesystem import FilesystemTools
from coding613.adapters.tools.patch import PatchCommitError
from coding613.adapters.tools.repository import build_repository_tools
from coding613.application.tool_registry import (
    DuplicateToolError,
    ToolRegistry,
    ToolSchemaError,
    UnknownToolError,
)
from coding613.domain.actions import ToolCall
from coding613.domain.models import PermissionMode
from coding613.ports.llm import ToolDefinition
from coding613.ports.tools import ToolContext, ToolResult


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        self.calls.append(call)
        return ToolResult(call=call, success=True, output=str(context.repository_root))


class RecordingInstaller:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def install(self, **kwargs: object) -> DependencyInstallResult:
        self.calls.append(kwargs)
        return DependencyInstallResult(
            success=True,
            output="installed",
            changed_files=("package.json", "package-lock.json"),
        )


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


def test_repository_registry_exposes_versioned_apply_patch_and_dispatches(
    tmp_path: Path,
) -> None:
    target = tmp_path / "value.txt"
    target.write_text("old\n", encoding="utf-8")
    registry, _, changed_files = build_repository_tools(tmp_path, ())
    definition = next(item for item in registry.definitions() if item.name == "apply_patch")
    assert definition.input_schema == {
        "$id": "coding613.tool.apply_patch.v1",
        "type": "object",
        "properties": {
            "patch": {"type": "string", "minLength": 1, "maxLength": 1_000_000}
        },
        "required": ["patch"],
        "additionalProperties": False,
    }
    patch = """--- a/value.txt
+++ b/value.txt
@@ -1 +1 @@
-old
+new
"""

    result = registry.dispatch(
        ToolCall(name="apply_patch", arguments={"patch": patch}),
        context(tmp_path),
    )

    assert result.success is True
    assert result.changed_files == ("value.txt",)
    assert changed_files == ["value.txt"]
    assert target.read_text(encoding="utf-8") == "new\n"
    assert result.output == '{"added": 0, "changed_files": ["value.txt"], "deleted": 0, "updated": 1}'


def test_repository_registry_dispatches_dependency_install_with_validated_arguments(
    tmp_path: Path,
) -> None:
    installer = RecordingInstaller()
    registry, _, changed_files = build_repository_tools(
        tmp_path, (), dependency_installer=installer
    )
    definition = next(item for item in registry.definitions() if item.name == "install_dependency")
    assert definition.input_schema["properties"] == {
        "manager": {"type": "string", "enum": ["npm"]},
        "packages": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 128},
            "minItems": 1,
            "maxItems": 32,
        },
        "workspace": {"type": "string", "minLength": 1, "maxLength": 128},
        "dev": {"type": "boolean"},
    }

    result = registry.dispatch(
        ToolCall(
            name="install_dependency",
            arguments={
                "manager": "npm",
                "packages": ["three"],
                "workspace": "@613-cube-solver/web",
                "dev": True,
            },
        ),
        context(tmp_path),
    )

    assert result.success is True
    assert result.changed_files == ("package.json", "package-lock.json")
    assert changed_files == ["package.json", "package-lock.json"]
    assert installer.calls == [
        {
            "manager": "npm",
            "packages": ("three",),
            "workspace": "@613-cube-solver/web",
            "dev": True,
        }
    ]


def test_apply_patch_schema_rejects_malformed_arguments_before_executor(
    tmp_path: Path,
) -> None:
    registry, _, _ = build_repository_tools(tmp_path, ())
    with pytest.raises(ToolSchemaError):
        registry.dispatch(
            ToolCall(name="apply_patch", arguments={"patch": 1}),
            context(tmp_path),
        )


def test_apply_patch_preserves_partial_commit_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, _, changed_files = build_repository_tools(tmp_path, ())

    def fail_after_partial_commit(self: FilesystemTools, patch: str) -> object:
        del self, patch
        raise PatchCommitError("descriptor close failed", ("a.txt", "b.txt"))

    monkeypatch.setattr(FilesystemTools, "apply_patch", fail_after_partial_commit)
    result = registry.dispatch(
        ToolCall(name="apply_patch", arguments={"patch": "--- /dev/null\n+++ b/a.txt\n"}),
        context(tmp_path),
    )

    assert result.success is False
    assert result.error == "PatchCommitError"
    assert result.changed_files == ("a.txt", "b.txt")
    assert changed_files == ["a.txt", "b.txt"]
