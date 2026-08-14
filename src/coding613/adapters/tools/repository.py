"""Tool executors used by the local application composition."""

from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Sequence
from pathlib import Path

from coding613.adapters.tools.dependencies import DependencyInstaller, DependencyInstallResult
from coding613.adapters.tools.filesystem import FilesystemTools
from coding613.adapters.tools.git import GitTools
from coding613.adapters.tools.patch import PatchCommitError, PatchConflictError, PatchError
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
_PATCH_GUIDANCE_LIMIT = 8_000


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


def _patch_conflict_guidance(tools: FilesystemTools, error: Exception) -> str:
    """Return bounded, redacted context that lets the model repair a stale patch."""

    reason = redact_text(str(error)).strip()
    path = _patch_error_path(str(error))
    if path is None:
        return (
            "Patch rejected because repository context changed; re-read the affected file "
            "with read_file and submit a fresh patch."
        )
    try:
        current = redact_text(tools.read_file(path))
    except Exception:  # noqa: BLE001 - the original conflict remains actionable
        return (
            f"Patch rejected for {path}: {reason}. Re-read {path} with read_file "
            "and submit a fresh patch."
        )
    excerpt = current
    if len(excerpt) > _PATCH_GUIDANCE_LIMIT:
        excerpt = (
            f"{excerpt[:_PATCH_GUIDANCE_LIMIT]}\n"
            f"... current file truncated ({len(current) - _PATCH_GUIDANCE_LIMIT} characters omitted)"
        )
    return (
        f"Patch rejected for {path}: {reason}. re-read {path} and submit a fresh patch.\n"
        "Current file content (bounded; use this instead of the stale patch context):\n"
        f"{excerpt}"
    )


def _patch_error_path(message: str) -> str | None:
    match = re.search(
        r"(?:hunk context does not match|hunk context is ambiguous|hunk offset is out of range|"
        r"missing patch source|add target already exists|delete patch does not consume source):\s*([^;]+)",
        message,
    )
    if match is None:
        return None
    path = match.group(1).strip()
    return path or None


def _responses_operation_patch(operation: object) -> str:
    """Translate an OpenAI Responses apply-patch operation to Codex syntax."""

    if not isinstance(operation, dict):
        raise TypeError("apply_patch operation must be an object")
    operation_type = operation.get("type")
    path = operation.get("path")
    if operation_type not in {"create_file", "update_file", "delete_file"}:
        raise ValueError("apply_patch operation type is unsupported")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("apply_patch operation path must be a non-empty string")
    diff = operation.get("diff", "")
    if diff is None:
        diff = ""
    if not isinstance(diff, str):
        raise TypeError("apply_patch operation diff must be a string")
    if diff.startswith("--- "):
        return diff
    if operation_type == "delete_file":
        return f"*** Begin Patch\n*** Delete File: {path}\n*** End Patch\n"
    if not diff.strip():
        raise ValueError("apply_patch operation requires a diff")
    if operation_type == "update_file":
        return f"*** Begin Patch\n*** Update File: {path}\n{diff.rstrip(chr(10))}\n*** End Patch\n"
    lines = diff.splitlines()
    if lines and lines[0].startswith("@@"):
        lines = [line for line in lines[1:] if line.startswith("+")]
    else:
        lines = [line if line.startswith("+") else f"+{line}" for line in lines]
    return (
        f"*** Begin Patch\n*** Add File: {path}\n"
        + "\n".join(lines)
        + "\n*** End Patch\n"
    )


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
            patch = call.arguments.get("patch")
            if not isinstance(patch, str):
                patch = _responses_operation_patch(call.arguments.get("operation"))
            result = self._tools.apply_patch(patch)
        except PatchCommitError as error:
            self._merge_changed(error.changed_files)
            return ToolResult(
                call=call,
                success=False,
                error=type(error).__name__,
                output=f"{type(error).__name__}: {redact_text(str(error))}",
                changed_files=error.changed_files,
            )
        except PatchConflictError as error:
            failure = _failure(call, error)
            return failure.model_copy(
                update={"output": _patch_conflict_guidance(self._tools, error)}
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


class _RunCommandExecutor:
    """Execute one argv command inside the repository boundary.

    This is intentionally not a shell interpreter: ``shell=False`` is enforced
    by ``ValidatorRunner`` and the model cannot provide an environment map.
    Policy decides whether an undeclared command needs approval before this
    executor is reached.
    """

    _MAX_TIMEOUT_SECONDS = 300.0
    _MAX_OUTPUT_BYTES = 10_000_000
    _ENVIRONMENT_NAMES = frozenset({"PATH", "LANG", "LC_ALL", "TMPDIR"})

    def __init__(self, root: Path) -> None:
        self._root = root.resolve(strict=True)
        self._runner = ValidatorRunner()

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        argv = tuple(str(item) for item in call.arguments["argv"])
        cwd_value = call.arguments.get("cwd")
        try:
            cwd = self._cwd(cwd_value)
            timeout = self._bounded_number(
                call.arguments.get("timeout_seconds", 300.0),
                "timeout_seconds",
                self._MAX_TIMEOUT_SECONDS,
            )
            output_bytes = self._bounded_integer(
                call.arguments.get("max_output_bytes", self._MAX_OUTPUT_BYTES),
                "max_output_bytes",
                self._MAX_OUTPUT_BYTES,
            )
            environment = {
                key: value
                for key, value in {**self._process_environment(), **context.environment}.items()
                if key in self._ENVIRONMENT_NAMES
            }
            result = self._runner.run(
                argv,
                cwd,
                ValidationLimits(
                    timeout_seconds=timeout,
                    max_output_bytes=output_bytes,
                    environment=environment,
                ),
                ValidationKind.OTHER,
            )
        except Exception as error:  # noqa: BLE001 - normalize executor failures
            return _failure(call, error)
        output = result.model_dump_json()
        if result.passed:
            return _result(call, output=output)
        if result.timed_out:
            command_error = "command_timeout"
        elif result.resource_exhausted:
            command_error = "command_resource_exhausted"
        else:
            command_error = f"command_exit_{result.exit_code}"
        return ToolResult(call=call, success=False, output=output, error=command_error)

    def _cwd(self, value: object) -> Path:
        if value is None:
            return self._root
        if not isinstance(value, str) or not value.strip():
            raise ValueError("cwd must be a non-empty repository-relative path")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("cwd must stay inside the repository")
        resolved = (self._root / path).resolve(strict=True)
        if not resolved.is_dir() or not resolved.is_relative_to(self._root):
            raise ValueError("cwd must be an existing repository directory")
        return resolved

    @staticmethod
    def _bounded_number(value: object, name: str, maximum: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be greater than zero and at most {maximum:g}")
        number = float(value)
        if number <= 0 or number > maximum:
            raise ValueError(f"{name} must be greater than zero and at most {maximum:g}")
        return number

    @staticmethod
    def _bounded_integer(value: object, name: str, maximum: int) -> int:
        if type(value) is not int or value <= 0 or value > maximum:
            raise ValueError(f"{name} must be greater than zero and at most {maximum}")
        return value

    @classmethod
    def _process_environment(cls) -> dict[str, str]:
        return {name: os.environ[name] for name in cls._ENVIRONMENT_NAMES if name in os.environ}


class _RunShellExecutor:
    """Execute a Responses shell call as ordered, argv-only commands."""

    def __init__(self, root: Path) -> None:
        self._single = _RunCommandExecutor(root)

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        commands = call.arguments.get("commands")
        if not isinstance(commands, list):
            return _failure(call, ValueError("commands must be an array"))
        results: list[dict[str, object]] = []
        for command in commands:
            if not isinstance(command, dict):
                return _failure(call, ValueError("each shell command must be an object"))
            nested = ToolCall(
                name="run_command",
                arguments=dict(command),
                provider_metadata=call.provider_metadata,
            )
            result = self._single.execute(nested, context)
            results.append(result.model_dump(mode="json"))
            if not result.success:
                return ToolResult(
                    call=call,
                    success=False,
                    output=_json(results),
                    error=result.error or "shell_command_failed",
                )
        return _result(call, output=_json(results))


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
                "oneOf": [
                    {
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
                    {
                        "properties": {
                            "operation": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["create_file", "update_file", "delete_file"],
                                    },
                                    "path": {"type": "string", "minLength": 1},
                                    "diff": {"type": "string", "maxLength": 1_000_000},
                                },
                                "required": ["type", "path"],
                                "additionalProperties": False,
                            }
                        },
                        "required": ["operation"],
                        "additionalProperties": False,
                    },
                ],
            },
        ),
        _ApplyPatchExecutor(filesystem, changed_files),
    )
    registry.register(
        ToolDefinition(
            name="run_shell",
            description=(
                "Execute an ordered Responses shell command batch as argv arrays; no shell "
                "interpolation or caller-provided environment is allowed"
            ),
            input_schema={
                "$id": "coding613.tool.run_shell.v1",
                "type": "object",
                "properties": {
                    "commands": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 64,
                        "items": {
                            "type": "object",
                            "properties": {
                                "argv": {
                                    "type": "array",
                                    "items": {"type": "string", "minLength": 1},
                                    "minItems": 1,
                                    "maxItems": 128,
                                },
                                "cwd": {"type": "string", "minLength": 1},
                                "timeout_seconds": {
                                    "type": "number",
                                    "exclusiveMinimum": 0,
                                    "maximum": 300,
                                },
                                "max_output_bytes": {
                                    "type": "integer",
                                    "exclusiveMinimum": 0,
                                    "maximum": 10_000_000,
                                },
                            },
                            "required": ["argv"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["commands"],
                "additionalProperties": False,
            },
        ),
        _RunShellExecutor(root),
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
    registry.register(
        ToolDefinition(
            name="run_command",
            description=(
                "Run one argv command in the repository without a shell. "
                "Commands not declared as validation require policy approval."
            ),
            input_schema={
                "$id": "coding613.tool.run_command.v1",
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "maxItems": 128,
                    },
                    "cwd": {"type": "string", "minLength": 1},
                    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 300},
                    "max_output_bytes": {
                        "type": "integer",
                        "exclusiveMinimum": 0,
                        "maximum": 10_000_000,
                    },
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        ),
        _RunCommandExecutor(root),
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
