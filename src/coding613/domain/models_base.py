"""Shared strict Pydantic base model for domain modules."""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)
