"""Validated domain values shared by the coding harness."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from .actions import ActionEnvelope, ToolCall
from .models_base import DomainModel


class RunState(StrEnum):
    RUNNING = "running"
    WAITING_MODEL = "waiting_model"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class PermissionMode(StrEnum):
    STRICT = "strict"
    BALANCED = "balanced"
    AUTONOMOUS = "autonomous"


class FeedbackKind(StrEnum):
    PASS = "pass"
    TEST_FAILURE = "test_failure"
    LINT_FAILURE = "lint_failure"
    TYPE_FAILURE = "type_failure"
    ENVIRONMENT_FAILURE = "environment_failure"
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    POLICY_BLOCKED = "policy_blocked"
    TOOL_ERROR = "tool_error"
    INVALID_ACTION = "invalid_action"
    MERGE_CONFLICT = "merge_conflict"
    NO_PROGRESS = "no_progress"


class StopReason(StrEnum):
    SUCCESS = "success"
    BUDGET_EXHAUSTED = "budget_exhausted"
    USER_REQUESTED = "user_requested"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_REJECTED = "approval_rejected"
    VALIDATION_FAILED = "validation_failed"
    NO_PROGRESS = "no_progress"
    INVALID_ACTION = "invalid_action"
    PROVIDER_ERROR = "provider_error"


class Feedback(DomainModel):
    kind: FeedbackKind
    message: str = Field(min_length=1)
    fingerprint: str | None = Field(default=None, min_length=1)
    retryable: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalRequest(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    action: ToolCall
    reason: str = Field(min_length=1)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None

    @field_validator("created_at", "resolved_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class IterationRecord(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    iteration: int = Field(ge=1)
    state_before: RunState
    state_after: RunState
    context_summary: str = ""
    model_response: dict[str, Any] | None = None
    action: ActionEnvelope | None = None
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] | None = None
    feedback: Feedback | None = None
    stop_reason: StopReason | None = None
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_terminal_reason(self) -> IterationRecord:
        if self.state_after.is_terminal and self.stop_reason is None:
            raise ValueError("terminal state requires stop_reason")
        if not self.state_after.is_terminal and self.stop_reason is not None:
            raise ValueError("non-terminal state cannot have stop_reason")
        return self
