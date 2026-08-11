"""Tool executors used by the local application composition."""

from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from pathlib import Path

from coding613.adapters.tools.dependencies import DependencyInstaller, DependencyInstallResult
from coding613.adapters.tools.filesystem import FilesystemTools
from coding613.adapters.tools.git import GitTools
from coding613.adapters.tools.patch import PatchCommitError, PatchError
from coding613.adapters.tools.validation import ValidatorRunner
from coding613.application.tool_registry import ToolRegistry
from coding613.application.validation import (
    ValidationKind,
    ValidationLimits,
    ValidationResult,
)
from coding613.domain.actions import ToolCall
from coding613.domain.redaction import redact_text
from coding613.ports.llm import ToolDefinition
from coding613.ports.tools import ToolContext, ToolResult


class ValidationCommandError(ValueError):
    """A safe, model-visible explanation for a rejected validation command."""


_ERROR_DETAIL_LIMIT = 1_000


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _result(call: ToolCall, *, output: str = "", changed_files: tuple[str, ...] = ()) -> ToolResult:
    return ToolResult(call=call, success=True, output=output, changed_files=changed_files)


def _failure(call: ToolCall, error: Exception) -> ToolResult:
    detail = type(error).__name__
    if isinstance(error, (PatchError, ValidationCommandError)):
        reason = redact_text(str(error)).strip()
        if len(reason) > _ERROR_DETAIL_LIMIT:
            reason = f"{reason[:_ERROR_DETAIL_LIMIT]}..."
        if reason:
            detail += f": {reason}"
    return ToolResult(call=call, success=False, error=detail)


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


class _InstallDependencyExecutor:
    def __init__(self, installer: DependencyInstaller, changed_files: list[str]) -> None:
        self._installer = installer
        self._changed_files = changed_files

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        try:
            result: DependencyInstallResult = self._installer.install(
                manager=str(call.arguments["manager"]),
                packages=tuple(str(item) for item in call.arguments["packages"]),
                workspace=(
                    str(call.arguments["workspace"])
                    if call.arguments.get("workspace") is not None
                    else None
                ),
                dev=bool(call.arguments.get("dev", False)),
            )
        except Exception as error:  # noqa: BLE001 - normalize installer failures
            return _failure(call, error)
        for path in result.changed_files:
            if path not in self._changed_files:
                self._changed_files.append(path)
        if not result.success:
            return ToolResult(
                call=call,
                success=False,
                output=result.output,
                error=result.error or "dependency_install_failed",
                changed_files=result.changed_files,
            )
        return _result(call, output=result.output, changed_files=result.changed_files)


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
        declared_command = self._canonical_declared_command(command)
        if declared_command is None:
            declared = "; ".join(_argv_json(item) for item in self._commands) or "none"
            raise ValidationCommandError(
                "validation command is not declared; "
                f"use one of: {redact_text(declared)}"
            )
        result = self._run(declared_command)
        self._latest = result
        return result

    def _canonical_declared_command(
        self, command: tuple[str, ...]
    ) -> tuple[str, ...] | None:
        if command in self._commands:
            return command
        # Older model prompts showed shell-formatted commands. Accept that one
        # legacy shape only when parsing produces an exact declared argv; this
        # never executes a shell or broadens the repository policy.
        if len(command) == 1:
            try:
                parsed = tuple(shlex.split(command[0]))
            except ValueError:
                return None
            if parsed in self._commands:
                return parsed
        return None

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
    *,
    dependency_installer: DependencyInstaller | None = None,
) -> tuple[ToolRegistry, RepositoryValidator, list[str]]:
    filesystem = FilesystemTools(root)
    validator = RepositoryValidator(root, commands)
    changed_files: list[str] = []
    installer = dependency_installer or DependencyInstaller(root)
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="list_files",
            description="List repository files (read-only; independent reads may run together)",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        _ListFilesExecutor(filesystem),
    )
    registry.register(
        ToolDefinition(
            name="search_files",
            description="Search repository text (read-only; independent reads may run together)",
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
            description="Read a UTF-8 repository file (read-only; independent reads may run together)",
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
            description=(
                "Apply a validated unified or Codex-format patch to repository files; "
                "standard git diff wrappers are accepted"
            ),
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
            description="Show repository diff (read-only; independent reads may run together)",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        _GitDiffExecutor(GitTools(root)),
    )
    registry.register(
        ToolDefinition(
            name="install_dependency",
            description=(
                "Install explicitly named npm packages with scripts disabled; "
                "requires repository dependency-install policy"
            ),
            input_schema={
                "$id": "coding613.tool.install_dependency.v1",
                "type": "object",
                "properties": {
                    "manager": {"type": "string", "enum": ["npm"]},
                    "packages": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 128},
                        "minItems": 1,
                        "maxItems": 32,
                    },
                    "workspace": {"type": "string", "minLength": 1, "maxLength": 128},
                    "dev": {"type": "boolean"},
                },
                "required": ["manager", "packages"],
                "additionalProperties": False,
            },
        ),
        _InstallDependencyExecutor(installer, changed_files),
    )
    registry.register(
        ToolDefinition(
            name="run_validation",
            description=_validation_description(commands),
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


def _validation_description(commands: Sequence[tuple[str, ...]]) -> str:
    if not commands:
        return "Run one declared validation command; none are configured."
    declared = "; ".join(redact_text(_argv_json(command)) for command in commands)
    return (
        "Run one declared validation command. Pass `argv` as the exact JSON array shown. "
        f"Allowed argv: {declared}"
    )


def _argv_json(command: Sequence[str]) -> str:
    return json.dumps(list(command), ensure_ascii=False)
