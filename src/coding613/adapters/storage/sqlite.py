"""SQLite source-of-truth storage for runs, iterations, and events."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from coding613.domain.conversation import RunOptions
from coding613.domain.events import Event, redact_payload
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import (
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
from coding613.domain.permissions import PermissionRule
from coding613.domain.redaction import redact_text


class SqliteEventStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self._transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._execute_schema(connection, schema)
            self._migrate_interactive_sessions(connection)
            self._normalize_run_and_session_timestamps(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as connection, connection:
            yield connection

    @staticmethod
    def _execute_schema(connection: sqlite3.Connection, schema: str) -> None:
        statement = ""
        for line in schema.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                connection.execute(statement)
                statement = ""
        if statement.strip():
            raise ValueError("schema contains an incomplete SQL statement")

    @staticmethod
    def _migrate_interactive_sessions(connection: sqlite3.Connection) -> None:
        run_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(runs)")
        }
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS interactive_sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        if "session_id" not in run_columns:
            connection.execute(
                """
                ALTER TABLE runs ADD COLUMN session_id TEXT
                REFERENCES interactive_sessions(id) ON DELETE SET NULL
                """
            )
        if "options_json" not in run_columns:
            connection.execute(
                "ALTER TABLE runs ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'"
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runs_session_created
            ON runs(session_id, created_at)
            """
        )
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            connection.execute("PRAGMA user_version = 1")

    @staticmethod
    def _normalize_run_and_session_timestamps(connection: sqlite3.Connection) -> None:
        for table in ("runs", "interactive_sessions"):
            rows = connection.execute(
                f"SELECT id, created_at, updated_at FROM {table}"
            ).fetchall()
            for row in rows:
                created_at = SqliteEventStore._serialize_datetime(
                    SqliteEventStore._parse_datetime(row["created_at"])
                )
                updated_at = SqliteEventStore._serialize_datetime(
                    SqliteEventStore._parse_datetime(row["updated_at"])
                )
                if (
                    created_at != row["created_at"]
                    or updated_at != row["updated_at"]
                ):
                    connection.execute(
                        f"UPDATE {table} SET created_at = ?, updated_at = ? WHERE id = ?",
                        (created_at, updated_at, row["id"]),
                    )

    def create_run(self, run: Run) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    id, project_id, session_id, options_json, task, permission_mode, state,
                    stop_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run.id),
                    str(run.project_id) if run.project_id else None,
                    str(run.session_id) if run.session_id else None,
                    self._redacted_json(run.options.model_dump(mode="json")),
                    run.task,
                    run.permission_mode.value,
                    run.state.value,
                    run.stop_reason.value if run.stop_reason else None,
                    self._serialize_datetime(run.created_at),
                    self._serialize_datetime(run.updated_at),
                ),
            )
            if run.session_id is not None:
                row = connection.execute(
                    "SELECT updated_at FROM interactive_sessions WHERE id = ?",
                    (str(run.session_id),),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown interactive session: {run.session_id}")
                updated_at = max(self._parse_datetime(row["updated_at"]), run.updated_at)
                connection.execute(
                    "UPDATE interactive_sessions SET updated_at = ? WHERE id = ?",
                    (self._serialize_datetime(updated_at), str(run.session_id)),
                )

    def create_interactive_session(self, session: InteractiveSession) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO interactive_sessions (id, project_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(session.id),
                    str(session.project_id),
                    session.title,
                    self._serialize_datetime(session.created_at),
                    self._serialize_datetime(session.updated_at),
                ),
            )

    def get_interactive_session(self, session_id: UUID) -> InteractiveSession | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM interactive_sessions WHERE id = ?", (str(session_id),)
            ).fetchone()
        if row is None:
            return None
        return self._interactive_session_from_row(row)

    def list_interactive_sessions(
        self, project_id: UUID, limit: int = 50
    ) -> list[InteractiveSession]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM interactive_sessions
                WHERE project_id = ?
                ORDER BY updated_at DESC, id ASC
                LIMIT ?
                """,
                (str(project_id), limit),
            ).fetchall()
        return [self._interactive_session_from_row(row) for row in rows]

    def list_runs_for_session(self, session_id: UUID) -> list[Run]:
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM runs
                WHERE session_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (str(session_id),),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

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

    def get_project_by_root(self, canonical_root: str | Path) -> Project | None:
        root = Path(canonical_root).resolve(strict=True)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE canonical_root = ?", (str(root),)
            ).fetchone()
        if row is None:
            return None
        return Project(
            id=UUID(row["id"]),
            canonical_root=Path(row["canonical_root"]),
            created_at=self._parse_datetime(row["created_at"]),
        )

    def save_permission_rule(self, project_id: UUID, rule: PermissionRule) -> None:
        """Persist one validated project-scoped permission rule."""

        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO permission_rules (
                    project_id, scope, pattern, effect, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, scope, pattern) DO UPDATE SET
                    effect = excluded.effect,
                    created_at = excluded.created_at
                """,
                (
                    str(project_id),
                    rule.scope,
                    rule.pattern,
                    rule.effect,
                    self._serialize_datetime(datetime.now(UTC)),
                ),
            )

    def list_permission_rules(self, project_id: UUID) -> list[PermissionRule]:
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT scope, pattern, effect
                FROM permission_rules
                WHERE project_id = ?
                ORDER BY scope, pattern
                """,
                (str(project_id),),
            ).fetchall()
        return [
            PermissionRule(
                scope=row["scope"], pattern=row["pattern"], effect=row["effect"]
            )
            for row in rows
        ]

    def delete_permission_rule(self, project_id: UUID, rule: PermissionRule) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                DELETE FROM permission_rules
                WHERE project_id = ? AND scope = ? AND pattern = ?
                """,
                (str(project_id), rule.scope, rule.pattern),
            )

    def save_context_summary(
        self, session_id: UUID, revision: str, text: str, created_at: datetime
    ) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO context_summaries (session_id, revision, summary_text, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    revision = excluded.revision,
                    summary_text = excluded.summary_text,
                    created_at = excluded.created_at
                """,
                (
                    str(session_id),
                    revision,
                    redact_text(text),
                    self._serialize_datetime(created_at),
                ),
            )

    def get_context_summary(
        self, session_id: UUID
    ) -> tuple[str, str, datetime] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT revision, summary_text, created_at
                FROM context_summaries
                WHERE session_id = ?
                """,
                (str(session_id),),
            ).fetchone()
        if row is None:
            return None
        return (
            row["revision"],
            row["summary_text"],
            self._parse_datetime(row["created_at"]),
        )

    def get_run(self, run_id: UUID) -> Run | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE id = ?", (str(run_id),)
            ).fetchone()
        if row is None:
            return None
        return self._run_from_row(row)

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> Run:
        return Run(
            id=UUID(row["id"]),
            project_id=UUID(row["project_id"]) if row["project_id"] else None,
            session_id=UUID(row["session_id"]) if row["session_id"] else None,
            options=RunOptions.model_validate_json(row["options_json"] or "{}"),
            task=row["task"],
            permission_mode=PermissionMode(row["permission_mode"]),
            state=RunState(row["state"]),
            stop_reason=StopReason(row["stop_reason"]) if row["stop_reason"] else None,
            created_at=SqliteEventStore._parse_datetime(row["created_at"]),
            updated_at=SqliteEventStore._parse_datetime(row["updated_at"]),
        )

    @staticmethod
    def _interactive_session_from_row(row: sqlite3.Row) -> InteractiveSession:
        return InteractiveSession(
            id=UUID(row["id"]),
            project_id=UUID(row["project_id"]),
            title=row["title"],
            created_at=SqliteEventStore._parse_datetime(row["created_at"]),
            updated_at=SqliteEventStore._parse_datetime(row["updated_at"]),
        )

    def compare_and_set_run(self, expected: Run, replacement: Run) -> bool:
        if expected.id != replacement.id:
            raise ValueError("replacement run id does not match expected run id")
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET project_id = ?, session_id = ?, task = ?, permission_mode = ?, state = ?,
                    stop_reason = ?, options_json = ?, updated_at = ?
                WHERE id = ?
                    AND project_id IS ?
                    AND session_id IS ?
                    AND task = ?
                    AND permission_mode = ?
                    AND state = ?
                    AND stop_reason IS ?
                    AND options_json = ?
                    AND created_at = ?
                    AND updated_at = ?
                """,
                (
                    str(replacement.project_id) if replacement.project_id else None,
                    str(replacement.session_id) if replacement.session_id else None,
                    replacement.task,
                    replacement.permission_mode.value,
                    replacement.state.value,
                    replacement.stop_reason.value if replacement.stop_reason else None,
                    self._redacted_json(replacement.options.model_dump(mode="json")),
                    self._serialize_datetime(replacement.updated_at),
                    str(expected.id),
                    str(expected.project_id) if expected.project_id else None,
                    str(expected.session_id) if expected.session_id else None,
                    expected.task,
                    expected.permission_mode.value,
                    expected.state.value,
                    expected.stop_reason.value if expected.stop_reason else None,
                    self._redacted_json(expected.options.model_dump(mode="json")),
                    self._serialize_datetime(expected.created_at),
                    self._serialize_datetime(expected.updated_at),
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

    @staticmethod
    def _serialize_datetime(value: datetime) -> str:
        return value.astimezone(UTC).isoformat()
