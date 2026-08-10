from __future__ import annotations

from pathlib import Path

from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.domain.models import Project
from coding613.domain.permissions import PermissionRule


def test_project_permission_rule_round_trip(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.sqlite")
    project = Project(canonical_root=tmp_path)
    store.create_project(project)
    rule = PermissionRule(scope="tool", pattern="read_file", effect="allow")

    store.save_permission_rule(project.id, rule)

    assert store.list_permission_rules(project.id) == [rule]
    store.delete_permission_rule(project.id, rule)
    assert store.list_permission_rules(project.id) == []
