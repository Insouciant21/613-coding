"""Visible safety budgets for interactive and unattended runs.

Per-agent turns remain in persisted configuration for backward compatibility,
but are informational only. Context compaction, rather than a turn ceiling,
controls the length of an agent conversation.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from coding613.domain.models import ResourceUsage, StopReason
from coding613.domain.models_base import DomainModel


class BudgetLimits(DomainModel):
    per_agent_turns: int | None = Field(default=None, gt=0)
    total_model_calls: int | None = Field(default=None, gt=0)
    wall_time_seconds: float | None = Field(default=None, gt=0)
    provider_cost: float | None = Field(default=None, gt=0)
    unattended: bool = False

    @model_validator(mode="after")
    def validate_unattended_limit(self) -> BudgetLimits:
        if self.unattended and self.total_model_calls is None and self.provider_cost is None:
            raise ValueError("unattended runs require a model-call or provider-cost budget")
        return self


class BudgetDecision(DomainModel):
    allowed: bool
    stop_reason: StopReason | None = None
    exceeded: tuple[str, ...] = ()


class BudgetTracker:
    def __init__(self, limits: BudgetLimits, usage: ResourceUsage | None = None) -> None:
        self.limits = limits
        restored = usage or ResourceUsage()
        self.turns = restored.agent_turns
        self.calls = restored.model_calls
        self.seconds = restored.wall_time_seconds
        self.cost = restored.provider_cost

    @property
    def usage(self) -> ResourceUsage:
        return ResourceUsage(
            agent_turns=self.turns,
            model_calls=self.calls,
            wall_time_seconds=self.seconds,
            provider_cost=self.cost,
        )

    def consume(
        self,
        turns: int,
        calls: int,
        seconds: float,
        cost: float,
        *,
        commit_on_reject: bool = True,
    ) -> BudgetDecision:
        if turns < 0 or calls < 0 or seconds < 0 or cost < 0:
            raise ValueError("budget consumption cannot be negative")
        projected = (
            self.turns + turns,
            self.calls + calls,
            self.seconds + seconds,
            self.cost + cost,
        )
        exceeded = tuple(
            name
            for name, used, limit in (
                ("total_model_calls", projected[1], self.limits.total_model_calls),
                ("wall_time_seconds", projected[2], self.limits.wall_time_seconds),
                ("provider_cost", projected[3], self.limits.provider_cost),
            )
            if limit is not None and used > limit
        )
        if exceeded:
            if commit_on_reject:
                self.turns, self.calls, self.seconds, self.cost = projected
            return BudgetDecision(
                allowed=False,
                stop_reason=StopReason.BUDGET_EXHAUSTED,
                exceeded=exceeded,
            )
        self.turns, self.calls, self.seconds, self.cost = projected
        return BudgetDecision(allowed=True)
