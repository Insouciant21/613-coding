"""Validated values shared by the interactive TUI and root CLI."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .models import PermissionMode
from .models_base import DomainModel
from .options import RunOptions

__all__ = [
    "ContextSummary",
    "DiagnosticCheck",
    "DiagnosticReport",
    "PromptRequest",
    "RunOptions",
]

class PromptRequest(DomainModel):
    """One user prompt and its selected session/invocation settings."""

    project_id: UUID
    text: str = Field(min_length=1, max_length=100_000)
    session_id: UUID | None = None
    continue_latest: bool = False
    permission_mode: PermissionMode | None = None
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
