"""Bounded resource profiles selected by the model at the start of a run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from coding613.domain.models_base import DomainModel


class TaskBudgetRequest(DomainModel):
    """Versioned schema for the model's one-time difficulty decision."""

    difficulty: Literal["standard", "complex"]


@dataclass(frozen=True, slots=True)
class ResourceProfile:
    """One safe, explainable allocation for a task difficulty level."""

    name: str
    max_output_tokens: int


_PROFILE_TARGETS: dict[str, int] = {
    "standard": 16_384,
    "complex": 128_000,
}


def resource_profile(
    difficulty: str,
    *,
    configured_max_output_tokens: int,
) -> ResourceProfile:
    """Return an output-token profile clamped by the operator's ceiling.

    Conversation length is controlled by context compaction in the harness.  A
    difficulty profile may tune one response's output budget, but it never
    imposes an agent-turn limit.
    """

    key = difficulty.strip().lower()
    if key not in _PROFILE_TARGETS:
        raise ValueError("difficulty must be standard or complex")
    target_tokens = _PROFILE_TARGETS[key]
    max_output_tokens = min(target_tokens, configured_max_output_tokens)
    return ResourceProfile(
        name=key,
        max_output_tokens=max(1, max_output_tokens),
    )
