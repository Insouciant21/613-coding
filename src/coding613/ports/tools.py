"""Tool execution port and bounded execution values."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import Field

from coding613.domain.actions import ToolCall
from coding613.domain.models import PermissionMode
from coding613.domain.models_base import DomainModel


class ToolContext(DomainModel):
    run_id: UUID
    repository_root: Path
    permission_mode: PermissionMode
    environment: dict[str, str] = Field(default_factory=dict)


class ToolResult(DomainModel):
    call: ToolCall
    success: bool
    output: str = ""
    error: str | None = None
    changed_files: tuple[str, ...] = ()


class ToolExecutor(Protocol):
    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult: ...
