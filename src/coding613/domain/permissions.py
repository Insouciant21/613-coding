"""Validated invocation filters and project permission rules."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from coding613.ports.policy import PolicyDecision, PolicyEffect

from .actions import ToolCall
from .models_base import DomainModel


class ToolFilter(DomainModel):
    allowed: frozenset[str] = Field(default_factory=frozenset)
    disallowed: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("allowed", "disallowed")
    @classmethod
    def validate_names(cls, value: frozenset[str]) -> frozenset[str]:
        if any(
            not name
            or len(name) > 128
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for character in name
            )
            for name in value
        ):
            raise ValueError("tool filters must contain valid tool names")
        return value

    @model_validator(mode="after")
    def reject_overlap(self) -> ToolFilter:
        overlap = self.allowed & self.disallowed
        if overlap:
            raise ValueError("tool filters cannot allow and disallow the same tool")
        return self

    def apply(self, call: ToolCall | str, decision: PolicyDecision) -> PolicyDecision:
        """Apply invocation filters without changing an existing hard denial."""

        if decision.effect is PolicyEffect.DENY:
            return decision
        tool_name = call.name if isinstance(call, ToolCall) else call
        if tool_name in self.disallowed:
            return decision.model_copy(
                update={
                    "effect": PolicyEffect.DENY,
                    "rule_id": "invocation.tool_disallowed",
                    "reason": "invocation denylist rejected tool",
                }
            )
        if self.allowed and tool_name not in self.allowed:
            return decision.model_copy(
                update={
                    "effect": PolicyEffect.DENY,
                    "rule_id": "invocation.tool_not_allowed",
                    "reason": "invocation allowlist did not include tool",
                }
            )
        return decision


class PermissionRule(DomainModel):
    scope: Literal["tool", "path"]
    pattern: str = Field(min_length=1, max_length=4_096)
    effect: Literal["allow", "deny"]

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("permission rule pattern must be a safe nonblank value")
        return value

    @model_validator(mode="after")
    def validate_scope_pattern(self) -> PermissionRule:
        if self.scope == "tool":
            ToolFilter(allowed=frozenset({self.pattern}))
            return self
        path = Path(self.pattern)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("path permission rules must stay within the repository")
        if any(character in self.pattern for character in ";&|`$<>\n\r"):
            raise ValueError("path permission rules must not contain shell syntax")
        if set(path.parts) & {".aws", ".gnupg", ".ssh", "credentials", "id_rsa", "id_ed25519"}:
            raise ValueError("path permission rules must not target credential material")
        return self
