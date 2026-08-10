from __future__ import annotations

from pathlib import Path

from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.application.permissions import PermissionRuleService
from coding613.domain.models import Project


def test_permission_rule_service_manages_project_tool_rules(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.sqlite")
    project = Project(canonical_root=tmp_path)
    store.create_project(project)
    service = PermissionRuleService(project.id, store)

    assert service.list_rules() == []
    assert service.allow_tool("read_file").effect == "allow"
    assert service.list_rules()[0].pattern == "read_file"

    assert service.deny_tool("read_file").effect == "deny"
    assert service.list_rules()[0].effect == "deny"

    service.clear_tool("read_file")
    assert service.list_rules() == []
