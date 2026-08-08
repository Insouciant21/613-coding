"""SQLite source-of-truth storage for runs, iterations, and events."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from coding_harness.domain.events import Event, redact_payload
from coding_harness.domain.models import (
    ApprovalRequest,
    ApprovalStatus,
    IterationRecord,
    LoopSession,
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
        with self._transaction() as connection:
            connection.executescript(schema)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as connection, connection:
            yield connection

    def create_run(self, run: Run) -> None:
        with self._transaction() as connection:
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
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO projects (id, canonical_root, created_at) VALUES (?, ?, ?)",
                (
                    str(project.id),
                    str(project.canonical_root),
                    project.created_at.isoformat(),
                ),
            )

    def get_run(self, run_id: UUID) -> Run | None:
        with self._transaction() as connection:
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

    def compare_and_set_run(self, expected: Run, replacement: Run) -> bool:
        if expected.id != replacement.id:
            raise ValueError("replacement run id does not match expected run id")
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET project_id = ?, task = ?, permission_mode = ?, state = ?,
                    stop_reason = ?, updated_at = ?
                WHERE id = ?
                    AND project_id IS ?
                    AND task = ?
                    AND permission_mode = ?
                    AND state = ?
                    AND stop_reason IS ?
                    AND created_at = ?
                    AND updated_at = ?
                """,
                (
                    str(replacement.project_id) if replacement.project_id else None,
                    replacement.task,
                    replacement.permission_mode.value,
                    replacement.state.value,
                    replacement.stop_reason.value if replacement.stop_reason else None,
                    replacement.updated_at.isoformat(),
                    str(expected.id),
                    str(expected.project_id) if expected.project_id else None,
                    expected.task,
                    expected.permission_mode.value,
                    expected.state.value,
                    expected.stop_reason.value if expected.stop_reason else None,
                    expected.created_at.isoformat(),
                    expected.updated_at.isoformat(),
                ),
            )
        return cursor.rowcount == 1

    def append(self, event: Event) -> None:
        payload = redact_payload(event.payload)
        with self._transaction() as connection:
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
        with self._transaction() as connection:
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
        record_json = self._redacted_json(iteration.model_dump(mode="json"))
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO iterations (id, run_id, iteration_number, record_json, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(iteration.id),
                    str(iteration.run_id),
                    iteration.iteration,
                    record_json,
                    iteration.timestamp.isoformat(),
                ),
            )

    def list_iterations(self, run_id: UUID) -> list[IterationRecord]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT record_json FROM iterations WHERE run_id = ? ORDER BY iteration_number",
                (str(run_id),),
            ).fetchall()
        return [IterationRecord.model_validate_json(row["record_json"]) for row in rows]

    def save_loop_session(self, session: LoopSession) -> None:
        session_json = self._redacted_json(session.model_dump(mode="json"))
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO loop_sessions (run_id, session_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    session_json = excluded.session_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(session.run_id),
                    session_json,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def save_iteration_and_session(
        self,
        iteration: IterationRecord,
        session: LoopSession,
        approval_update: ApprovalRequest | None = None,
    ) -> None:
        if iteration.run_id != session.run_id:
            raise ValueError("iteration and session must belong to the same run")
        record_json = self._redacted_json(iteration.model_dump(mode="json"))
        session_json = self._redacted_json(session.model_dump(mode="json"))
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO iterations (id, run_id, iteration_number, record_json, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(iteration.id),
                    str(iteration.run_id),
                    iteration.iteration,
                    record_json,
                    iteration.timestamp.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO loop_sessions (run_id, session_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    session_json = excluded.session_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(session.run_id),
                    session_json,
                    datetime.now(UTC).isoformat(),
                ),
            )
            if approval_update is not None:
                self._replace_claimed_approval(connection, approval_update)

    def get_loop_session(self, run_id: UUID) -> LoopSession | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT session_json FROM loop_sessions WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
        if row is None:
            return None
        return LoopSession.model_validate_json(row["session_json"])

    def save_approval(self, request: ApprovalRequest) -> None:
        if request.run_id is None:
            raise ValueError("approval request requires a run_id")
        request_json = self._redacted_json(request.model_dump(mode="json"))
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO approvals (
                    id, run_id, request_json, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    request_json = excluded.request_json,
                    resolved_at = excluded.resolved_at
                """,
                (
                    str(request.id),
                    str(request.run_id),
                    request_json,
                    request.created_at.isoformat(),
                    request.resolved_at.isoformat() if request.resolved_at else None,
                ),
            )

    def get_approval(self, request_id: UUID) -> ApprovalRequest | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT request_json FROM approvals WHERE id = ?",
                (str(request_id),),
            ).fetchone()
        if row is None:
            return None
        return ApprovalRequest.model_validate_json(row["request_json"])

    def list_approvals(self, run_id: UUID) -> list[ApprovalRequest]:
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT request_json FROM approvals
                WHERE run_id = ? ORDER BY created_at, id
                """,
                (str(run_id),),
            ).fetchall()
        return [ApprovalRequest.model_validate_json(row["request_json"]) for row in rows]

    def compare_and_set_approval(
        self,
        request_id: UUID,
        expected_status: ApprovalStatus,
        replacement: ApprovalRequest,
    ) -> bool:
        if replacement.id != request_id:
            raise ValueError("replacement approval id does not match request id")
        request_json = self._redacted_json(replacement.model_dump(mode="json"))
        with self._transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_json FROM approvals WHERE id = ?",
                (str(request_id),),
            ).fetchone()
            if row is None:
                return False
            current = ApprovalRequest.model_validate_json(row["request_json"])
            if current.status is not expected_status:
                return False
            connection.execute(
                """
                UPDATE approvals
                SET request_json = ?, resolved_at = ?
                WHERE id = ?
                """,
                (
                    request_json,
                    replacement.resolved_at.isoformat()
                    if replacement.resolved_at
                    else None,
                    str(request_id),
                ),
            )
        return True

    def _replace_claimed_approval(
        self,
        connection: sqlite3.Connection,
        replacement: ApprovalRequest,
    ) -> None:
        row = connection.execute(
            "SELECT request_json FROM approvals WHERE id = ?",
            (str(replacement.id),),
        ).fetchone()
        if row is None:
            raise KeyError(replacement.id)
        current = ApprovalRequest.model_validate_json(row["request_json"])
        expected = {
            ApprovalStatus.CONSUMED: {ApprovalStatus.EXECUTING},
            ApprovalStatus.REJECTED: {
                ApprovalStatus.PENDING,
                ApprovalStatus.APPROVED,
            },
        }.get(replacement.status, {current.status})
        if current.status not in expected:
            raise ValueError("approval status changed before loop-state commit")
        connection.execute(
            """
            UPDATE approvals
            SET request_json = ?, resolved_at = ?
            WHERE id = ?
            """,
            (
                self._redacted_json(replacement.model_dump(mode="json")),
                replacement.resolved_at.isoformat()
                if replacement.resolved_at
                else None,
                str(replacement.id),
            ),
        )

    @staticmethod
    def _redacted_json(value: object) -> str:
        return json.dumps(
            redact_payload(value),
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value)
