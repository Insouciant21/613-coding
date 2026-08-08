"""Policy evaluation port and auditable decision values."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import Field

from coding_harness.domain.actions import ToolCall
from coding_harness.domain.models_base import DomainModel
from coding_harness.ports.tools import ToolContext


class PolicyEffect(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PolicyDecision(DomainModel):
    effect: PolicyEffect
    rule_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    action: ToolCall | None = None


class PolicyEvaluator(Protocol):
    def evaluate(self, call: ToolCall, context: ToolContext) -> PolicyDecision: ...
