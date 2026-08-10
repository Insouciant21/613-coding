"""Validated domain values shared by the coding harness."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from .actions import ActionEnvelope, ToolCall
from .conversation import RunOptions
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
    DEPENDENCY_ERROR = "dependency_error"


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
    EXECUTING = "executing"
    CONSUMED = "consumed"


class ApprovalRequest(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID | None = None
    action: ToolCall
    reason: str = Field(min_length=1)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    resolved_at: datetime | None = None

    @field_validator("created_at", "expires_at", "resolved_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class SchemaValidationEvidence(DomainModel):
    valid: bool
    target: Literal["model_response", "tool_call", "finish"]
    error_type: str | None = None


class PolicyDecisionEvidence(DomainModel):
    effect: Literal["allow", "ask", "deny"]
    rule_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class IterationRecord(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    iteration: int = Field(ge=1)
    state_before: RunState
    state_after: RunState
    context_summary: str = ""
    model_response: dict[str, Any] | None = None
    action: ActionEnvelope | None = None
    schema_validation: SchemaValidationEvidence | None = None
    policy_decision: PolicyDecisionEvidence | None = None
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


class ResourceUsage(DomainModel):
    agent_turns: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    wall_time_seconds: float = Field(default=0, ge=0)
    provider_cost: float = Field(default=0, ge=0)


class LoopSession(DomainModel):
    run_id: UUID
    state: RunState = RunState.RUNNING
    stop_reason: StopReason | None = None
    iteration: int = Field(default=0, ge=0)
    pending_call: ToolCall | None = None
    pending_request: UUID | None = None
    validation_result: dict[str, Any] | None = None
    validation_revision: str | None = None
    validation_evidence: tuple[dict[str, Any], ...] = ()
    approvals: tuple[UUID, ...] = ()
    unresolved_risks: tuple[str, ...] = ()
    completion_blockers: tuple[FeedbackKind, ...] = ()
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage)
    budget_limits: dict[str, Any] | None = None
    classifier_state: dict[str, Any] | None = None
    changed_files: tuple[str, ...] = ()
    context_summary: str = ""


class Run(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID | None = None
    session_id: UUID | None = None
    options: RunOptions = Field(default_factory=RunOptions)
    task: str = Field(min_length=1)
    permission_mode: PermissionMode = PermissionMode.BALANCED
    state: RunState = RunState.RUNNING
    stop_reason: StopReason | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_aware_run_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_run_state(self) -> Run:
        if self.state.is_terminal and self.stop_reason is None:
            raise ValueError("terminal run requires stop_reason")
        if not self.state.is_terminal and self.stop_reason is not None:
            raise ValueError("non-terminal run cannot have stop_reason")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self


class Project(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    canonical_root: Path
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("canonical_root")
    @classmethod
    def require_canonical_directory(cls, value: Path) -> Path:
        root = value.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("canonical_root must be a directory")
        return root

    @field_validator("created_at")
    @classmethod
    def require_aware_project_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class MemoryType(StrEnum):
    PROJECT_CONVENTION = "project_convention"
    VALIDATION_CONFIG = "validation_config"
    GOVERNANCE_DECISION = "governance_decision"
    TASK_SUMMARY = "task_summary"
    FAILURE_PATTERN = "failure_pattern"


class EmbeddingStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class MemoryEntry(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    memory_type: MemoryType
    text: str = Field(min_length=1)
    permission_tags: frozenset[str] = Field(default_factory=frozenset)
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("permission_tags")
    @classmethod
    def validate_permission_tags(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not tag or not tag.replace("-", "").replace("_", "").isalnum() for tag in value):
            raise ValueError("permission tags must be alphanumeric identifiers")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_aware_memory_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class RunSummary(DomainModel):
    run_id: UUID
    status: RunState
    stop_reason: StopReason | None = None
    changed_files: tuple[str, ...] = ()
    validation_evidence: tuple[dict[str, Any], ...] = ()
    approvals: tuple[UUID, ...] = ()
    unresolved_risks: tuple[str, ...] = ()
    completion_blockers: tuple[FeedbackKind, ...] = ()
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage)
