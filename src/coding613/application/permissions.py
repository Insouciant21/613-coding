"""Application use cases for project-scoped permission rules."""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from coding613.domain.permissions import PermissionRule, ToolFilter


class PermissionRuleStore(Protocol):
    def save_permission_rule(self, project_id: UUID, rule: PermissionRule) -> None: ...

    def list_permission_rules(self, project_id: UUID) -> list[PermissionRule]: ...

    def delete_permission_rule(self, project_id: UUID, rule: PermissionRule) -> None: ...


class PermissionRuleService:
    """Validate and persist tool permission changes outside UI adapters."""

    def __init__(self, project_id: UUID, store: PermissionRuleStore) -> None:
        self._project_id = project_id
        self._store = store

    def list_rules(self) -> list[PermissionRule]:
        return self._store.list_permission_rules(self._project_id)

    def allow_tool(self, name: str) -> PermissionRule:
        return self._set_tool(name, "allow")

    def deny_tool(self, name: str) -> PermissionRule:
        return self._set_tool(name, "deny")

    def clear_tool(self, name: str) -> None:
        self._validate_tool_name(name)
        for effect in ("allow", "deny"):
            self._store.delete_permission_rule(
                self._project_id,
                PermissionRule(scope="tool", pattern=name, effect=effect),
            )

    def _set_tool(
        self, name: str, effect: Literal["allow", "deny"]
    ) -> PermissionRule:
        self._validate_tool_name(name)
        rule = PermissionRule(scope="tool", pattern=name, effect=effect)
        self._store.save_permission_rule(self._project_id, rule)
        return rule

    @staticmethod
    def _validate_tool_name(name: str) -> None:
        ToolFilter(allowed=frozenset({name}))
