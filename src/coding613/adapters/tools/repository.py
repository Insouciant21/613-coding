"""Tool executors used by the local application composition."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from coding613.adapters.tools.filesystem import FilesystemTools
from coding613.adapters.tools.git import GitTools
from coding613.adapters.tools.patch import PatchCommitError
from coding613.adapters.tools.validation import ValidatorRunner
from coding613.application.tool_registry import ToolRegistry
from coding613.application.validation import (
    ValidationKind,
    ValidationLimits,
    ValidationResult,
)
from coding613.domain.actions import ToolCall
from coding613.ports.llm import ToolDefinition
from coding613.ports.tools import ToolContext, ToolResult


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _result(call: ToolCall, *, output: str = "", changed_files: tuple[str, ...] = ()) -> ToolResult:
    return ToolResult(call=call, success=True, output=output, changed_files=changed_files)


def _failure(call: ToolCall, error: Exception) -> ToolResult:
    return ToolResult(call=call, success=False, error=type(error).__name__)


class _ListFilesExecutor:
    def __init__(self, tools: FilesystemTools) -> None:
        self._tools = tools

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        try:
            return _result(call, output=_json(self._tools.list_files()))
        except Exception as error:  # noqa: BLE001
            return _failure(call, error)


class _SearchFilesExecutor:
    def __init__(self, tools: FilesystemTools) -> None:
        self._tools = tools

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        try:
            matches = self._tools.search_files(str(call.arguments["query"]))
            return _result(
                call,
                output=_json(
                    [
                        {
                            "path": match.path,
                            "line_number": match.line_number,
                            "line": match.line,
                        }
                        for match in matches
                    ]
                ),
            )
        except Exception as error:  # noqa: BLE001
            return _failure(call, error)


class _ReadFileExecutor:
    def __init__(self, tools: FilesystemTools) -> None:
        self._tools = tools

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        try:
            return _result(call, output=self._tools.read_file(str(call.arguments["path"])))
        except Exception as error:  # noqa: BLE001
            return _failure(call, error)


class _EditFileExecutor:
    def __init__(self, tools: FilesystemTools, changed_files: list[str]) -> None:
        self._tools = tools
        self._changed_files = changed_files

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        path = str(call.arguments["path"])
        try:
            self._tools.edit_file(path, str(call.arguments["content"]))
        except Exception as error:  # noqa: BLE001
            return _failure(call, error)
        if path not in self._changed_files:
            self._changed_files.append(path)
        return _result(call, changed_files=(path,))


class _DeleteFileExecutor:
    def __init__(self, tools: FilesystemTools, changed_files: list[str]) -> None:
        self._tools = tools
        self._changed_files = changed_files

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        path = str(call.arguments["path"])
        try:
            self._tools.delete_file(path)
        except Exception as error:  # noqa: BLE001
            return _failure(call, error)
        if path not in self._changed_files:
            self._changed_files.append(path)
        return _result(call, changed_files=(path,))


class _ApplyPatchExecutor:
    def __init__(self, tools: FilesystemTools, changed_files: list[str]) -> None:
        self._tools = tools
        self._changed_files = changed_files

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        try:
            result = self._tools.apply_patch(str(call.arguments["patch"]))
        except PatchCommitError as error:
            self._merge_changed(error.changed_files)
            return ToolResult(
                call=call,
                success=False,
                error=type(error).__name__,
                changed_files=error.changed_files,
            )
        except Exception as error:  # noqa: BLE001
            return _failure(call, error)
        self._merge_changed(result.changed_files)
        return _result(
            call,
            output=_json(
                {
                    "added": result.added,
                    "updated": result.updated,
                    "deleted": result.deleted,
                    "changed_files": list(result.changed_files),
                }
            ),
            changed_files=result.changed_files,
        )

    def _merge_changed(self, paths: tuple[str, ...]) -> None:
        for path in paths:
            if path not in self._changed_files:
                self._changed_files.append(path)


class _GitDiffExecutor:
    def __init__(self, tools: GitTools) -> None:
        self._tools = tools

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        try:
            return _result(call, output=self._tools.diff())
        except Exception as error:  # noqa: BLE001
            return _failure(call, error)


class RepositoryValidator:
    """Run declared validation commands and expose the latest result to the loop."""

    def __init__(self, root: Path, commands: Sequence[tuple[str, ...]]) -> None:
        self._root = root
        self._commands = tuple(commands)
        self._runner = ValidatorRunner()
        self._latest: ValidationResult | None = None
        self._limits = ValidationLimits(timeout_seconds=300, max_output_bytes=1_000_000)

    def validate(self) -> ValidationResult:
        if self._latest is not None:
            result, self._latest = self._latest, None
            return result
        if not self._commands:
            return ValidationResult(
                command=("validation-not-configured",),
                kind=ValidationKind.OTHER,
                exit_code=1,
                stderr="no validation commands are configured",
                duration_seconds=0,
            )
        results = [self._run(command) for command in self._commands]
        return next((result for result in results if not result.passed), results[-1])

    def run_declared(self, command: tuple[str, ...]) -> ValidationResult:
        if command not in self._commands:
            raise ValueError("validation command is not declared")
        result = self._run(command)
        self._latest = result
        return result

    def _run(self, command: tuple[str, ...]) -> ValidationResult:
        return self._runner.run(command, self._root, self._limits, _validation_kind(command))


class _RunValidationExecutor:
    def __init__(self, validator: RepositoryValidator) -> None:
        self._validator = validator

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        try:
            command = tuple(str(item) for item in call.arguments["argv"])
            result = self._validator.run_declared(command)
            return _result(call, output=result.model_dump_json())
        except Exception as error:  # noqa: BLE001
            return _failure(call, error)


def _validation_kind(command: tuple[str, ...]) -> ValidationKind:
    executable = Path(command[0]).name.lower()
    if executable in {"ruff", "flake8", "black"}:
        return ValidationKind.LINT
    if executable in {"mypy", "pyright"}:
        return ValidationKind.TYPE
    if executable in {"pytest", "unittest", "python", "python3"}:
        return ValidationKind.TEST
    return ValidationKind.OTHER


def build_repository_tools(
    root: Path,
    commands: Sequence[tuple[str, ...]],
) -> tuple[ToolRegistry, RepositoryValidator, list[str]]:
    filesystem = FilesystemTools(root)
    validator = RepositoryValidator(root, commands)
    changed_files: list[str] = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="list_files",
            description="List repository files",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        _ListFilesExecutor(filesystem),
    )
    registry.register(
        ToolDefinition(
            name="search_files",
            description="Search repository text",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "minLength": 1}},
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        _SearchFilesExecutor(filesystem),
    )
    registry.register(
        ToolDefinition(
            name="read_file",
            description="Read a UTF-8 repository file",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        _ReadFileExecutor(filesystem),
    )
    registry.register(
        ToolDefinition(
            name="delete_file",
            description="Delete one repository file",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        _DeleteFileExecutor(filesystem, changed_files),
    )
    registry.register(
        ToolDefinition(
            name="apply_patch",
            description="Apply a strict unified diff to repository files",
            input_schema={
                "$id": "coding613.tool.apply_patch.v1",
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1_000_000,
                    }
                },
                "required": ["patch"],
                "additionalProperties": False,
            },
        ),
        _ApplyPatchExecutor(filesystem, changed_files),
    )
    registry.register(
        ToolDefinition(
            name="edit_file",
            description="Replace a repository file",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        ),
        _EditFileExecutor(filesystem, changed_files),
    )
    registry.register(
        ToolDefinition(
            name="git_diff",
            description="Show repository diff",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        _GitDiffExecutor(GitTools(root)),
    )
    registry.register(
        ToolDefinition(
            name="run_validation",
            description="Run one declared validation command",
            input_schema={
                "type": "object",
                "properties": {
                    "argv": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1}
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        ),
        _RunValidationExecutor(validator),
    )
    return registry, validator, changed_files
