"""Authoritative SQLite repository for redacted memory text."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from coding_harness.domain.models import (
    EmbeddingStatus,
    MemoryEntry,
    MemoryType,
)
from coding_harness.domain.redaction import redact_text

from .sqlite import SqliteEventStore


class MemoryRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        SqliteEventStore(self.path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def put(self, entry: MemoryEntry) -> None:
        redacted = redact_text(entry.text)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_entries (
                    id, project_id, memory_type, redacted_text, permission_tags_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    memory_type = excluded.memory_type,
                    redacted_text = excluded.redacted_text,
                    permission_tags_json = excluded.permission_tags_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(entry.id),
                    str(entry.project_id),
                    entry.memory_type.value,
                    redacted,
                    json.dumps(sorted(entry.permission_tags), separators=(",", ":")),
                    entry.created_at.isoformat(),
                    entry.updated_at.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO embedding_status (memory_id, status, indexed_at, error)
                VALUES (?, ?, NULL, NULL)
                ON CONFLICT(memory_id) DO UPDATE SET status = excluded.status
                """,
                (str(entry.id), entry.embedding_status.value),
            )

    def get(self, memory_id: UUID) -> MemoryEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT m.*, e.status AS embedding_state
                FROM memory_entries AS m
                JOIN embedding_status AS e ON e.memory_id = m.id
                WHERE m.id = ?
                """,
                (str(memory_id),),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_many(self, memory_ids: tuple[UUID, ...]) -> list[MemoryEntry]:
        return [entry for memory_id in memory_ids if (entry := self.get(memory_id)) is not None]

    def search_keyword(
        self, query: str, project_id: UUID, limit: int = 10
    ) -> list[MemoryEntry]:
        if limit < 1:
            raise ValueError("limit must be positive")
        terms = tuple(dict.fromkeys(query.strip().split()))[:8]
        escaped_terms = tuple(
            term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            for term in terms
        )
        if not escaped_terms:
            return []
        keyword_clause = " OR ".join(
            "m.redacted_text LIKE ? ESCAPE '\\'" for _ in escaped_terms
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT m.*, e.status AS embedding_state
                FROM memory_entries AS m
                JOIN embedding_status AS e ON e.memory_id = m.id
                WHERE m.project_id = ? AND ({keyword_clause})
                ORDER BY m.updated_at DESC, m.id
                LIMIT ?
                """,
                (str(project_id), *(f"%{term}%" for term in escaped_terms), limit),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def project_for_run(self, run_id: UUID) -> UUID | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM runs WHERE id = ?", (str(run_id),)
            ).fetchone()
        return UUID(row["project_id"]) if row is not None and row["project_id"] else None

    def delete_project(self, project_id: UUID) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM projects WHERE id = ?", (str(project_id),))

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=UUID(row["id"]),
            project_id=UUID(row["project_id"]),
            memory_type=MemoryType(row["memory_type"]),
            text=row["redacted_text"],
            permission_tags=frozenset(json.loads(row["permission_tags_json"])),
            embedding_status=EmbeddingStatus(row["embedding_state"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
