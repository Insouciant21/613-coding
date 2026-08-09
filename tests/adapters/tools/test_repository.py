from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from coding613.adapters.tools.repository import build_repository_tools
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
