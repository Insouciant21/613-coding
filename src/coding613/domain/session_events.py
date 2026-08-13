"""Versioned event and final-output values for terminal adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, field_validator

from .conversation import DiagnosticReport
from .models import (
    FeedbackKind,
    PermissionMode,
    ResourceUsage,
    RunState,
    RunSummary,
    StopReason,
)
from .models_base import DomainModel


class EventType(StrEnum):
    SESSION_STARTED = "session.started"
    USER_MESSAGE = "user.message"
    ASSISTANT_DELTA = "assistant.delta"
    RUN_STATE = "run.state"
    TOOL_STARTED = "tool.started"
    TOOL_FINISHED = "tool.finished"
    VALIDATION_STARTED = "validation.started"
    VALIDATION_FINISHED = "validation.finished"
    APPROVAL_REQUESTED = "approval.requested"
    RUN_PAUSED = "run.paused"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    DIAGNOSTIC_COMPLETED = "diagnostic.completed"


class SessionEvent(DomainModel):
    """Ephemeral, redacted event shared by terminal adapters."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, frozen=True
    )

    event_id: UUID = Field(default_factory=uuid4)
    schema_version: int = Field(default=1, ge=1)
    sequence: int = Field(default=1, ge=1)
    session_id: UUID
    run_id: UUID
    type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class RunEnvelope(DomainModel):
    """Stable final output value for one non-interactive run."""

    schema_version: int = Field(default=1, ge=1)
    session_id: UUID
    run_id: UUID
    status: RunState
    permission_mode: PermissionMode = PermissionMode.BALANCED
    stop_reason: StopReason | None = None
    assistant_text: str = ""
    changed_files: tuple[str, ...] = ()
    validation_evidence: tuple[dict[str, Any], ...] = ()
    approvals: tuple[UUID, ...] = ()
    completion_blockers: tuple[FeedbackKind, ...] = ()
    resource_usage: ResourceUsage
    diagnostics: DiagnosticReport | None = None

    @classmethod
    def from_summary(
        cls,
        summary: RunSummary,
        session_id: UUID,
        assistant_text: str,
        permission_mode: PermissionMode = PermissionMode.BALANCED,
        diagnostics: DiagnosticReport | None = None,
    ) -> RunEnvelope:
        return cls(
            session_id=session_id,
            run_id=summary.run_id,
            status=summary.status,
            permission_mode=permission_mode,
            stop_reason=summary.stop_reason,
            assistant_text=assistant_text,
            changed_files=summary.changed_files,
            validation_evidence=summary.validation_evidence,
            approvals=summary.approvals,
            completion_blockers=summary.completion_blockers,
            resource_usage=summary.resource_usage,
            diagnostics=diagnostics,
        )


class SessionEnvelope(DomainModel):
    """Stable final output for ordered multiple prompt input."""

    schema_version: int = Field(default=1, ge=1)
    session_id: UUID
    runs: tuple[RunEnvelope, ...]
