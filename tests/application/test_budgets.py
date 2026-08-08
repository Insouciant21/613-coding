from __future__ import annotations

import pytest
from pydantic import ValidationError

from coding_harness.application.budgets import BudgetLimits, BudgetTracker
from coding_harness.domain.models import StopReason


def test_interactive_budget_has_no_implicit_five_turn_cap() -> None:
    tracker = BudgetTracker(BudgetLimits())
    for _ in range(20):
        assert tracker.consume(turns=1, calls=1, seconds=1, cost=0).allowed


def test_unattended_budget_requires_call_or_cost_limit() -> None:
    with pytest.raises(ValidationError):
        BudgetLimits(unattended=True, wall_time_seconds=60)


@pytest.mark.parametrize(
    "limits",
    [
        BudgetLimits(per_agent_turns=1),
        BudgetLimits(total_model_calls=1),
        BudgetLimits(wall_time_seconds=1),
        BudgetLimits(provider_cost=1),
    ],
)
def test_each_budget_stops_after_exhaustion(limits: BudgetLimits) -> None:
    tracker = BudgetTracker(limits)
    decision = tracker.consume(turns=2, calls=2, seconds=2, cost=2)
    assert not decision.allowed
    assert decision.stop_reason is StopReason.BUDGET_EXHAUSTED


def test_negative_consumption_is_rejected() -> None:
    with pytest.raises(ValueError):
        BudgetTracker(BudgetLimits()).consume(turns=-1, calls=0, seconds=0, cost=0)
