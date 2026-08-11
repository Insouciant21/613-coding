"""Validated actions emitted by a model and accepted by the application."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from .models_base import DomainModel


class ToolCall(DomainModel):
    kind: Literal["tool"] = "tool"
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]
    # Provider-specific continuation metadata is kept outside ``arguments`` so
    # local tool schemas stay strict. Responses client-side tools (shell,
    # apply_patch, computer) use this to correlate a governed result with the
    # provider's call id without exposing transport fields to the model.
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def reject_blank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tool name must not be blank")
        return value


class FinishAction(DomainModel):
    kind: Literal["finish"] = "finish"
    summary: str = Field(min_length=1)


class ActionEnvelope(DomainModel):
    action: Annotated[ToolCall | FinishAction, Field(discriminator="kind")]
