"""Validated objective-validation results and freshness tracking."""

from __future__ import annotations

import os
from enum import StrEnum

from pydantic import Field, model_validator

from coding_harness.domain.models_base import DomainModel


def _default_environment() -> dict[str, str]:
    allowed = ("LANG", "LC_ALL", "PATH")
    return {name: os.environ[name] for name in allowed if name in os.environ}


class ValidationKind(StrEnum):
    TEST = "test"
    LINT = "lint"
    TYPE = "type"
    OTHER = "other"


class ValidationLimits(DomainModel):
    timeout_seconds: float = Field(gt=0)
    max_output_bytes: int = Field(gt=0)
    max_memory_bytes: int | None = Field(default=None, gt=0)
    max_processes: int | None = Field(default=None, gt=0)
    environment: dict[str, str] = Field(default_factory=_default_environment)


class ValidationResult(DomainModel):
    command: tuple[str, ...] = Field(min_length=1)
    kind: ValidationKind
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = Field(ge=0)
    timed_out: bool = False
    resource_exhausted: bool = False
    output_truncated: bool = False

    @model_validator(mode="after")
    def validate_status(self) -> ValidationResult:
        if self.timed_out and self.exit_code is not None:
            raise ValueError("timed-out validation cannot have an exit code")
        return self

    @property
    def passed(self) -> bool:
        return (
            self.exit_code == 0
            and not self.timed_out
            and not self.resource_exhausted
        )


class ValidationTracker:
    def __init__(self) -> None:
        self._result: ValidationResult | None = None
        self._revision: str | None = None

    def record(self, result: ValidationResult, revision: str) -> None:
        if not revision:
            raise ValueError("revision must not be empty")
        self._result = result
        self._revision = revision

    def is_fresh_and_passing(self, revision: str) -> bool:
        return self._revision == revision and self._result is not None and self._result.passed
