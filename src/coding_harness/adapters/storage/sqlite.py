"""SQLite source-of-truth storage for runs, iterations, and events."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from coding_harness.domain.events import Event, redact_payload
from coding_harness.domain.models import (
    IterationRecord,
    PermissionMode,
    Project,
    Run,
    RunState,
    StopReason,
)


class SqliteEventStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self._connect() as connection:
            connection.executescript(schema)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def create_run(self, run: Run) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    id, project_id, task, permission_mode, state, stop_reason,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run.id),
                    str(run.project_id) if run.project_id else None,
                    run.task,
                    run.permission_mode.value,
                    run.state.value,
                    run.stop_reason.value if run.stop_reason else None,
                    run.created_at.isoformat(),
                    run.updated_at.isoformat(),
                ),
            )

    def create_project(self, project: Project) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO projects (id, canonical_root, created_at) VALUES (?, ?, ?)",
                (
                    str(project.id),
                    str(project.canonical_root),
                    project.created_at.isoformat(),
                ),
            )

    def get_run(self, run_id: UUID) -> Run | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE id = ?", (str(run_id),)
            ).fetchone()
        if row is None:
            return None
        return Run(
            id=UUID(row["id"]),
            project_id=UUID(row["project_id"]) if row["project_id"] else None,
            task=row["task"],
            permission_mode=PermissionMode(row["permission_mode"]),
            state=RunState(row["state"]),
            stop_reason=StopReason(row["stop_reason"]) if row["stop_reason"] else None,
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def append(self, event: Event) -> None:
        payload = redact_payload(event.payload)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events (id, run_id, version, event_type, payload_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event.id),
                    str(event.run_id),
                    event.version,
                    event.event_type,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    event.timestamp.isoformat(),
                ),
            )

    def list_for_run(self, run_id: UUID) -> list[Event]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY sequence", (str(run_id),)
            ).fetchall()
        return [
            Event(
                id=UUID(row["id"]),
                version=row["version"],
                event_type=row["event_type"],
                run_id=UUID(row["run_id"]),
                payload=json.loads(row["payload_json"]),
                timestamp=self._parse_datetime(row["timestamp"]),
            )
            for row in rows
        ]

    def save_iteration(self, iteration: IterationRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO iterations (id, run_id, iteration_number, record_json, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(iteration.id),
                    str(iteration.run_id),
                    iteration.iteration,
                    iteration.model_dump_json(),
                    iteration.timestamp.isoformat(),
                ),
            )

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value)
