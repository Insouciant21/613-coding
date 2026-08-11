from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

from coding613.adapters.tools.repository import build_repository_tools
from coding613.application.tool_registry import ToolSchemaError
from coding613.domain.actions import ToolCall
from coding613.domain.models import PermissionMode
from coding613.ports.tools import ToolContext


def test_repository_tools_expose_and_track_file_deletion(tmp_path: Path) -> None:
    target = tmp_path / "obsolete.py"
    target.write_text("obsolete\n", encoding="utf-8")
    registry, _, changed_files = build_repository_tools(tmp_path, ())
    context = ToolContext(
        run_id=uuid4(),
        repository_root=tmp_path,
        permission_mode=PermissionMode.BALANCED,
    )

    assert "delete_file" in {definition.name for definition in registry.definitions()}
    result = registry.dispatch(
        ToolCall(name="delete_file", arguments={"path": "obsolete.py"}),
        context,
    )

    assert result.success
    assert result.changed_files == ("obsolete.py",)
    assert changed_files == ["obsolete.py"]
    assert not target.exists()


def test_repository_delete_rejects_invalid_arguments(tmp_path: Path) -> None:
    registry, _, _ = build_repository_tools(tmp_path, ())
    context = ToolContext(
        run_id=uuid4(),
        repository_root=tmp_path,
        permission_mode=PermissionMode.BALANCED,
    )

    with pytest.raises(ToolSchemaError):
        registry.dispatch(ToolCall(name="delete_file", arguments={}), context)


@pytest.mark.parametrize(
    ("path", "expected_error"),
    [("missing.py", "FileNotFoundError"), ("directory", "IsADirectoryError")],
)
def test_repository_delete_reports_invalid_targets(
    tmp_path: Path, path: str, expected_error: str
) -> None:
    (tmp_path / "directory").mkdir()
    registry, _, changed_files = build_repository_tools(tmp_path, ())
    context = ToolContext(
        run_id=uuid4(),
        repository_root=tmp_path,
        permission_mode=PermissionMode.BALANCED,
    )

    result = registry.dispatch(
        ToolCall(name="delete_file", arguments={"path": path}),
        context,
    )

    assert not result.success
    assert result.error == expected_error
    assert changed_files == []


def test_run_validation_reports_undeclared_command_and_declared_alternative(
    tmp_path: Path,
) -> None:
    registry, _, _ = build_repository_tools(
        tmp_path,
        (("bash", "scripts", "verify.sh"),),
    )
    result = registry.dispatch(
        ToolCall(
            name="run_validation",
            arguments={"argv": ["npm", "test", "--prefix", "apps/web"]},
        ),
        ToolContext(
            run_id=uuid4(),
            repository_root=tmp_path,
            permission_mode=PermissionMode.BALANCED,
        ),
    )

    assert not result.success
    assert result.error is not None
    assert "validation command is not declared" in result.error
    assert '["bash", "scripts", "verify.sh"]' in result.error
    definition = next(
        item for item in registry.definitions() if item.name == "run_validation"
    )
    assert '["bash", "scripts", "verify.sh"]' in definition.description


def test_run_validation_accepts_legacy_shell_formatted_argv(tmp_path: Path) -> None:
    (tmp_path / "verify.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    registry, _, _ = build_repository_tools(tmp_path, (("bash", "verify.sh"),))

    result = registry.dispatch(
        ToolCall(
            name="run_validation",
            arguments={"argv": ["bash verify.sh"]},
        ),
        ToolContext(
            run_id=uuid4(),
            repository_root=tmp_path,
            permission_mode=PermissionMode.BALANCED,
        ),
    )

    assert result.success
    assert result.output is not None
    assert '"command":["bash","verify.sh"]' in result.output


def test_apply_patch_reports_actionable_conflict_reason(tmp_path: Path) -> None:
    (tmp_path / "value.txt").write_text("current\n", encoding="utf-8")
    registry, _, _ = build_repository_tools(tmp_path, ())

    result = registry.dispatch(
        ToolCall(
            name="apply_patch",
            arguments={
                "patch": "--- a/value.txt\n"
                "+++ b/value.txt\n"
                "@@ -1 +1 @@\n"
                "-before\n"
                "+after\n"
            },
        ),
        ToolContext(
            run_id=uuid4(),
            repository_root=tmp_path,
            permission_mode=PermissionMode.BALANCED,
        ),
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.startswith("PatchConflictError:")
    assert "expected 'before'" in result.error
    assert "found 'current'" in result.error
    assert "re-read" in result.output


def test_run_command_executes_argv_without_shell_interpolation(tmp_path: Path) -> None:
    registry, _, _ = build_repository_tools(tmp_path, ())

    result = registry.dispatch(
        ToolCall(
            name="run_command",
            arguments={"argv": [sys.executable, "-c", "print('$613_CODING_LITERAL')"]},
        ),
        ToolContext(
            run_id=uuid4(),
            repository_root=tmp_path,
            permission_mode=PermissionMode.BALANCED,
        ),
    )

    assert result.success
    assert "$613_CODING_LITERAL" in result.output
    assert "command" in result.output


def test_run_shell_executes_each_argv_command_without_shell_interpolation(tmp_path: Path) -> None:
    registry, _, _ = build_repository_tools(tmp_path, ())

    result = registry.dispatch(
        ToolCall(
            name="run_shell",
            arguments={
                "commands": [
                    {"argv": [sys.executable, "-c", "print('one')"]},
                    {"argv": [sys.executable, "-c", "print('two')"]},
                ]
            },
        ),
        ToolContext(
            run_id=uuid4(),
            repository_root=tmp_path,
            permission_mode=PermissionMode.BALANCED,
        ),
    )

    assert result.success
    assert "one" in result.output
    assert "two" in result.output


def test_apply_patch_accepts_responses_operation_shape(tmp_path: Path) -> None:
    target = tmp_path / "value.txt"
    target.write_text("old\n", encoding="utf-8")
    registry, _, changed_files = build_repository_tools(tmp_path, ())

    result = registry.dispatch(
        ToolCall(
            name="apply_patch",
            arguments={
                "operation": {
                    "type": "update_file",
                    "path": "value.txt",
                    "diff": "@@ -1 +1 @@\n-old\n+new\n",
                }
            },
        ),
        ToolContext(
            run_id=uuid4(),
            repository_root=tmp_path,
            permission_mode=PermissionMode.BALANCED,
        ),
    )

    assert result.success
    assert target.read_text(encoding="utf-8") == "new\n"
    assert changed_files == ["value.txt"]
