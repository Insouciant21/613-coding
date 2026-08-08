"""Worker role context values."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from .models_base import DomainModel
from .sandbox import WorkArtifact
from .tasks import WorkerRole


class WorkerContext(DomainModel):
    run_id: UUID
    project_root: Path
    prior_artifacts: tuple[WorkArtifact, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)
    role: WorkerRole | None = None

    @field_validator("project_root")
    @classmethod
    def normalize_root(cls, value: Path) -> Path:
        return value.expanduser().resolve()
