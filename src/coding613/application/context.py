"""Permission-filtered, bounded model context assembly."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from coding613.adapters.storage.lancedb_index import MemoryQuery, VectorHit
from coding613.adapters.storage.memory import MemoryRepository
from coding613.application.interactive import InteractiveStore, transcript_for_runs
from coding613.domain.events import Event
from coding613.domain.models import MemoryEntry, Run
from coding613.domain.redaction import redact_text
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


class SessionContextStore(InteractiveStore, Protocol):
    def get_run(self, run_id: UUID) -> Run | None: ...


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
        if run is None or run.session_id is None:
            return context
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
        return context.model_copy(update={"messages": tuple(messages), "metadata": metadata})
