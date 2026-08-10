"""Permission-filtered, bounded model context assembly."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from coding613.adapters.storage.lancedb_index import MemoryQuery, VectorHit
from coding613.adapters.storage.memory import MemoryRepository
from coding613.application.interactive import InteractiveStore, transcript_for_runs
from coding613.domain.conversation import ContextSummary
from coding613.domain.events import Event
from coding613.domain.models import MemoryEntry, Run
from coding613.domain.options import RunOptions
from coding613.domain.redaction import redact_text
from coding613.ports.context import ContextCompactor, ContextSummaryStore, TranscriptSource
from coding613.ports.embeddings import EmbeddingProvider
from coding613.ports.llm import ModelContext, ModelMessage

_WORKER_SYSTEM_PROMPT = (
    "You are a 613 Coding repository worker. Act directly on the repository with "
    "the available tools to complete the user's task. Use read-only tools only to "
    "gather information that is still missing, then make the smallest required "
    "edits. Do not repeat successful read-only actions unless new evidence makes "
    "another read necessary. Treat objective validation as authoritative feedback: "
    "diagnose its concrete failure, edit the implicated files, rerun validation, "
    "and finish only after fresh validation passes."
)


class MemoryIndex(Protocol):
    def query(
        self, vector: tuple[float, ...], filters: MemoryQuery, limit: int
    ) -> list[VectorHit]: ...


class ContextAssembler:
    def __init__(
        self,
        repository: MemoryRepository,
        index: MemoryIndex,
        embedding: EmbeddingProvider,
        allowed_permission_tags: frozenset[str] = frozenset(),
        max_memories: int = 5,
        max_recent_events: int = 10,
        max_message_chars: int = 2_000,
    ) -> None:
        if min(max_memories, max_recent_events, max_message_chars) < 1:
            raise ValueError("context bounds must be positive")
        self._repository = repository
        self._index = index
        self._embedding = embedding
        self._allowed_tags = allowed_permission_tags
        self._max_memories = max_memories
        self._max_recent_events = max_recent_events
        self._max_message_chars = max_message_chars
        self.last_query: MemoryQuery | None = None

    def build(
        self, run_id: UUID, task: str, recent_events: Sequence[Event]
    ) -> ModelContext:
        project_id = self._repository.project_for_run(run_id)
        if project_id is None:
            raise ValueError("run has no project")
        safe_task = redact_text(task)
        query = MemoryQuery(
            project_id=project_id,
            allowed_permission_tags=self._allowed_tags,
        )
        self.last_query = query
        memories = self._retrieve(safe_task, query)
        messages = [ModelMessage(role="system", content=_WORKER_SYSTEM_PROMPT)]
        messages.extend(
            ModelMessage(
                role="system",
                content=f"Memory ({entry.memory_type.value}): {entry.text}"[
                    : self._max_message_chars
                ],
            )
            for entry in memories
        )
        messages.append(ModelMessage(role="user", content=safe_task[: self._max_message_chars]))
        for event in recent_events[-self._max_recent_events :]:
            payload = json.dumps(event.payload, sort_keys=True, separators=(",", ":"))
            messages.append(
                ModelMessage(
                    role="user",
                    content=f"Event {event.event_type}: {payload}"[: self._max_message_chars],
                )
            )
        return ModelContext(
            run_id=run_id,
            task=safe_task,
            messages=tuple(messages),
            metadata={"memory_ids": [str(entry.id) for entry in memories]},
        )

    def _retrieve(self, task: str, query: MemoryQuery) -> list[MemoryEntry]:
        try:
            vector = tuple(self._embedding.embed((task,))[0])
            hits = self._index.query(vector, query, self._max_memories * 3)
            entries = self._repository.get_many(tuple(hit.memory_id for hit in hits))
        except (IndexError, RuntimeError, ValueError):
            entries = self._repository.search_keyword(
                task, query.project_id, self._max_memories * 3
            )
        permitted = [
            entry
            for entry in entries
            if not entry.permission_tags or entry.permission_tags.issubset(self._allowed_tags)
        ]
        return permitted[: self._max_memories]


class SessionContextStore(InteractiveStore, ContextSummaryStore, Protocol):
    def get_run(self, run_id: UUID) -> Run | None: ...


class DeterministicContextCompactor:
    """Small deterministic compactor used when no model-backed compactor is injected."""

    def compact(self, transcript: tuple[TranscriptSource, ...], max_chars: int) -> str:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        lines = [f"{entry.role}: {redact_text(entry.text)}" for entry in transcript]
        return "\n".join(lines)[-max_chars:]


class ContextService:
    """Account for and persist context summaries without mutating transcripts."""

    def __init__(
        self,
        store: SessionContextStore,
        *,
        compactor: ContextCompactor | None = None,
        max_entries: int = 12,
        max_chars: int = 12_000,
    ) -> None:
        if min(max_entries, max_chars) < 1:
            raise ValueError("context bounds must be positive")
        self._store = store
        self._compactor = compactor or DeterministicContextCompactor()
        self._max_entries = max_entries
        self._max_chars = max_chars

    def report(self, session_id: UUID) -> ContextSummary:
        entries = self._entries(session_id)
        included, omitted = self._select(entries)
        text = self._render(included)
        return self._persist(session_id, text, included, omitted)

    def compact(self, session_id: UUID) -> ContextSummary:
        entries = self._entries(session_id)
        compacted = redact_text(self._compactor.compact(tuple(entries), self._max_chars))
        if not compacted.strip():
            raise ValueError("context compactor returned empty text")
        included = entries[-self._max_entries :]
        omitted = entries[: max(0, len(entries) - len(included))]
        return self._persist(session_id, compacted, included, omitted)

    def _entries(self, session_id: UUID) -> list[TranscriptSource]:
        session = self._store.get_interactive_session(session_id)
        if session is None:
            raise KeyError(f"unknown interactive session: {session_id}")
        runs = self._store.list_runs_for_session(session.id)
        return [entry for entry in transcript_for_runs(self._store, runs)]

    def _select(
        self, entries: list[TranscriptSource]
    ) -> tuple[list[TranscriptSource], list[TranscriptSource]]:
        selected: list[TranscriptSource] = []
        remaining = self._max_chars
        for entry in reversed(entries):
            if len(selected) >= self._max_entries or remaining <= 0:
                break
            text = redact_text(entry.text)[:remaining]
            if not text:
                continue
            selected.append(entry)
            remaining -= len(text)
        selected.reverse()
        selected_ids = {id(entry) for entry in selected}
        return selected, [entry for entry in entries if id(entry) not in selected_ids]

    @staticmethod
    def _render(entries: Sequence[TranscriptSource]) -> str:
        return "\n".join(f"{entry.role}: {redact_text(entry.text)}" for entry in entries)

    def _persist(
        self,
        session_id: UUID,
        text: str,
        included: Sequence[TranscriptSource],
        omitted: Sequence[TranscriptSource],
    ) -> ContextSummary:
        safe_text = redact_text(text)
        included_sources = tuple(self._source(entry) for entry in included)
        omitted_sources = tuple(self._source(entry) for entry in omitted)
        revision = hashlib.sha256(
            (safe_text + "\0" + "\0".join(included_sources + omitted_sources)).encode(
                "utf-8"
            )
        ).hexdigest()
        self._store.save_context_summary(
            session_id, revision, safe_text, datetime.now(UTC)
        )
        return ContextSummary(
            summary_revision=revision,
            included_sources=included_sources,
            omitted_sources=omitted_sources,
            estimated_tokens=(len(safe_text) + 3) // 4,
            max_tokens=max(1, self._max_chars // 4),
        )

    @staticmethod
    def _source(entry: TranscriptSource) -> str:
        return f"{entry.role}:{entry.run_id}"


class BaseContextBuilder(Protocol):
    def build(
        self, run_id: UUID, task: str, recent_events: Sequence[Event]
    ) -> ModelContext: ...


class SessionContextBuilder:
    def __init__(
        self,
        base: BaseContextBuilder,
        store: SessionContextStore,
        max_entries: int = 12,
        max_chars: int = 12_000,
    ) -> None:
        if min(max_entries, max_chars) < 1:
            raise ValueError("session context bounds must be positive")
        self._base = base
        self._store = store
        self._max_entries = max_entries
        self._max_chars = max_chars

    def build(
        self, run_id: UUID, task: str, recent_events: Sequence[Event]
    ) -> ModelContext:
        context = self._base.build(run_id, task, recent_events)
        run = self._store.get_run(run_id)
        if run is None:
            return context
        if run.session_id is None:
            metadata, messages = self._apply_options(
                dict(context.metadata), list(context.messages), run.options
            )
            return context.model_copy(update={"messages": tuple(messages), "metadata": metadata})
        runs = self._store.list_runs_for_session(run.session_id)
        prior_runs = list(runs[: next((i for i, item in enumerate(runs) if item.id == run_id), len(runs))])
        entries = list(transcript_for_runs(self._store, prior_runs))
        selected: list[ModelMessage] = []
        remaining = self._max_chars
        for entry in reversed(entries):
            if len(selected) >= self._max_entries or remaining <= 0:
                break
            text = redact_text(entry.text)[:remaining]
            if not text:
                continue
            selected.append(ModelMessage(role=entry.role, content=text))
            remaining -= len(text)
        selected.reverse()
        omitted = len(entries) - len(selected)

        messages = list(context.messages)
        insert_at = next(
            (index for index, message in enumerate(messages) if message.role != "system"),
            len(messages),
        )
        history: list[ModelMessage] = []
        if omitted:
            history.append(
                ModelMessage(
                    role="system",
                    content=f"Omitted {omitted} earlier transcript entries.",
                )
            )
        history.extend(selected)
        messages[insert_at:insert_at] = history
        metadata = dict(context.metadata)
        metadata["omitted_transcript_entries"] = omitted
        options = run.options
        metadata, messages = self._apply_options(metadata, messages, options)
        return context.model_copy(update={"messages": tuple(messages), "metadata": metadata})

    @staticmethod
    def _apply_options(
        metadata: dict[str, object],
        messages: list[ModelMessage],
        options: RunOptions,
    ) -> tuple[dict[str, object], list[ModelMessage]]:
        if options.model is not None:
            metadata["model"] = options.model
        prompt_messages: list[ModelMessage] = []
        if options.system_prompt:
            safe = redact_text(options.system_prompt)
            metadata["system_prompt"] = safe
            prompt_messages.append(ModelMessage(role="system", content=safe))
        if options.append_system_prompt:
            safe = redact_text(options.append_system_prompt)
            metadata["append_system_prompt"] = safe
            prompt_messages.append(ModelMessage(role="system", content=safe))
        if prompt_messages:
            insert_at = next(
                (index for index, message in enumerate(messages) if message.role != "system"),
                len(messages),
            )
            messages[insert_at:insert_at] = prompt_messages
        return metadata, messages
