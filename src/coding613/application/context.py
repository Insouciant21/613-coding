"""Permission-filtered, bounded model context assembly."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from coding613.adapters.storage.lancedb_index import MemoryQuery, VectorHit
from coding613.adapters.storage.memory import MemoryRepository
from coding613.domain.events import Event
from coding613.domain.models import MemoryEntry
from coding613.domain.redaction import redact_text
from coding613.ports.embeddings import EmbeddingProvider
from coding613.ports.llm import ModelContext, ModelMessage


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
        messages = [
            ModelMessage(
                role="system",
                content=f"Memory ({entry.memory_type.value}): {entry.text}"[
                    : self._max_message_chars
                ],
            )
            for entry in memories
        ]
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
