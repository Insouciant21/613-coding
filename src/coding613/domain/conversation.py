"""Validated values shared by the interactive TUI and root CLI."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from .models_base import DomainModel


def _validate_tool_names(value: frozenset[str]) -> frozenset[str]:
    for name in value:
        if not name or len(name) > 128 or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in name
        ):
            raise ValueError("tool names must be non-empty identifier names")
    return value


class RunOptions(DomainModel):
    """Invocation-scoped options persisted with a run for safe resume."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, frozen=True
    )

    model: str | None = Field(default=None, min_length=1, max_length=256)
    allowed_tools: frozenset[str] = Field(default_factory=frozenset)
    disallowed_tools: frozenset[str] = Field(default_factory=frozenset)
    additional_dirs: tuple[str, ...] = ()
    system_prompt: str | None = Field(default=None, max_length=100_000)
    append_system_prompt: str | None = Field(default=None, max_length=100_000)
    budget_overrides: dict[str, Any] = Field(default_factory=dict)

    _validate_allowed = field_validator("allowed_tools")(staticmethod(_validate_tool_names))
    _validate_disallowed = field_validator("disallowed_tools")(
        staticmethod(_validate_tool_names)
    )

    @field_validator("additional_dirs")
    @classmethod
    def validate_additional_dirs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not path or len(path) > 4_096 for path in value):
            raise ValueError("additional directory paths must be non-empty and bounded")
        return value

    @model_validator(mode="after")
    def reject_overlapping_tools(self) -> RunOptions:
        overlap = self.allowed_tools & self.disallowed_tools
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ValueError(f"tools cannot be both allowed and disallowed: {names}")
        return self


class PromptRequest(DomainModel):
    """One user prompt and its selected session/invocation settings."""

    project_id: UUID
    text: str = Field(min_length=1, max_length=100_000)
    session_id: UUID | None = None
    continue_latest: bool = False
    options: RunOptions = Field(default_factory=RunOptions)

    @field_validator("text")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt text must not be blank")
        return value

    @model_validator(mode="after")
    def reject_conflicting_session_selection(self) -> PromptRequest:
        if self.session_id is not None and self.continue_latest:
            raise ValueError("session_id and continue_latest cannot be selected together")
        return self


class ContextSummary(DomainModel):
    summary_revision: str = Field(min_length=1)
    included_sources: tuple[str, ...] = ()
    omitted_sources: tuple[str, ...] = ()
    estimated_tokens: int = Field(ge=0)
    max_tokens: int = Field(ge=1)


class DiagnosticCheck(DomainModel):
    name: str = Field(min_length=1, max_length=128)
    status: Literal["pass", "warn", "fail"]
    detail: str = Field(min_length=1, max_length=4_096)


class DiagnosticReport(DomainModel):
    project_id: UUID
    checks: tuple[DiagnosticCheck, ...] = ()
