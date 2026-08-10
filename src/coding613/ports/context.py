"""Ports for deterministic context accounting and persisted summaries."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from coding613.domain.conversation import ContextSummary


class TranscriptSource(Protocol):
    role: Literal["user", "assistant"]
    text: str
    run_id: UUID


class ContextCompactor(Protocol):
    def compact(self, transcript: tuple[TranscriptSource, ...], max_chars: int) -> str: ...


class ContextSummaryStore(Protocol):
    def save_context_summary(
        self, session_id: UUID, revision: str, text: str, created_at: datetime
    ) -> None: ...

    def get_context_summary(
        self, session_id: UUID
    ) -> tuple[str, str, datetime] | None: ...


class ContextAccounting(Protocol):
    def report(self, session_id: UUID) -> ContextSummary: ...

    def compact(self, session_id: UUID) -> ContextSummary: ...


__all__ = ["ContextAccounting", "ContextCompactor", "ContextSummaryStore", "TranscriptSource"]
