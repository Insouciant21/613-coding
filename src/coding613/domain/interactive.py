"""Interactive coding session values."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from .models_base import DomainModel


class InteractiveSession(DomainModel):
    """A user-facing conversation grouping related coding runs."""

    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    title: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("title")
    @classmethod
    def require_nonblank_title(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title must not be blank")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> InteractiveSession:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self
