from __future__ import annotations

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
