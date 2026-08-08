"""Validated values shared by sandbox runtimes and their consumers."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from .models_base import DomainModel


class NetworkPolicy(StrEnum):
    DENY = "deny"
    ALLOWLIST = "allowlist"


class ResourceLimits(DomainModel):
    """Finite limits applied to one worker sandbox."""

    cpu_seconds: float = Field(default=300.0, gt=0)
    memory_bytes: int = Field(default=512 * 1024 * 1024, gt=0)
    pids: int = Field(default=128, gt=0)
    disk_bytes: int = Field(default=2 * 1024 * 1024 * 1024, gt=0)
    timeout_seconds: float = Field(default=300.0, gt=0)
    output_bytes: int = Field(default=1024 * 1024, gt=0)


class SandboxSpec(DomainModel):
    image_digest: str = Field(min_length=71)
    workspace_path: Path
    network_policy: NetworkPolicy = NetworkPolicy.DENY
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    environment_allowlist: tuple[str, ...] = ()
    worker_id: str = Field(min_length=1)
    run_as_user: int = Field(default=65532, gt=0)
    read_only_root: bool = True
    capabilities: tuple[str, ...] = ()

    @field_validator("image_digest")
    @classmethod
    def require_sha256_digest(cls, value: str) -> str:
        if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", value) is None:
            raise ValueError("image_digest must be a pinned sha256 digest")
        return value

    @field_validator("workspace_path")
    @classmethod
    def normalize_workspace_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("environment_allowlist")
    @classmethod
    def validate_environment_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
                raise ValueError("environment allowlist entries must be variable names")
        return value

    @model_validator(mode="after")
    def enforce_worker_defaults(self) -> SandboxSpec:
        if self.run_as_user == 0:
            raise ValueError("sandbox workers cannot run as root")
        if self.capabilities:
            raise ValueError("sandbox capabilities must be dropped")
        if not self.read_only_root:
            raise ValueError("sandbox root filesystem must be read-only")
        return self


class SandboxHandle(DomainModel):
    """Opaque runtime identity; host/container metadata is deliberately absent."""

    id: UUID = Field(default_factory=uuid4)
    workspace_path: Path

    @field_validator("workspace_path")
    @classmethod
    def normalize_workspace_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()


class CommandResult(DomainModel):
    command: tuple[str, ...] = Field(min_length=1)
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = Field(default=0.0, ge=0)
    timed_out: bool = False
    resource_exhausted: bool = False
    output_truncated: bool = False

    @model_validator(mode="after")
    def validate_status(self) -> CommandResult:
        if self.timed_out and self.exit_code is not None:
            raise ValueError("timed-out command cannot have an exit code")
        return self


class WorkArtifact(DomainModel):
    version: int = Field(default=1, ge=1)
    patch: str = ""
    changed_files: tuple[str, ...] = ()
    summary: str = ""
    verification_evidence: tuple[dict[str, Any], ...] = ()
    assumptions: tuple[str, ...] = ()
    follow_up_requests: tuple[str, ...] = ()
