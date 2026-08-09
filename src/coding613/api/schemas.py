"""Validated HTTP request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from coding613.domain.models import PermissionMode


class CreateRunRequest(BaseModel):
    task: str = Field(min_length=1)
    permission_mode: PermissionMode = PermissionMode.BALANCED


class ApprovalRequestBody(BaseModel):
    decision: Literal["approve", "reject"]
