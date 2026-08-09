from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.domain.actions import ActionEnvelope, ToolCall
from coding613.domain.events import Event
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import (
    ApprovalRequest,
    IterationRecord,
    LoopSession,
    PermissionMode,
    Project,
    Run,
    RunState,
    StopReason,
)


class TrackingSqliteEventStore(SqliteEventStore):
    def __init__(self, path: Path) -> None:
        self.connections: list[sqlite3.Connection] = []
        super().__init__(path)

    def _connect(self) -> sqlite3.Connection:
        connection = super()._connect()
        self.connections.append(connection)
        return connection


def assert_connection_closed(connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_store_creates_required_schema(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    SqliteEventStore(path)
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        "projects",
        "runs",
        "interactive_sessions",
        "iterations",
        "loop_sessions",
        "events",
        "approvals",
        "task_graphs",
        "artifacts",
        "memory_entries",
        "embedding_status",
    } <= tables


def test_session_round_trip_and_ordered_runs(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    project = Project(canonical_root=tmp_path)
    store.create_project(project)
    session = InteractiveSession(project_id=project.id, title="Repair tests")
    store.create_interactive_session(session)
    assert store.get_interactive_session(session.id) == session
    first = Run(project_id=project.id, session_id=session.id, task="first")
    second = Run(project_id=project.id, session_id=session.id, task="second")
    store.create_run(first)
    store.create_run(second)

    assert store.list_runs_for_session(session.id) == [first, second]


def test_sessions_are_ordered_by_latest_activity_and_runs_update_activity(
    tmp_path: Path,
) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    project = Project(canonical_root=tmp_path)
    store.create_project(project)
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    older = InteractiveSession(
        project_id=project.id,
        title="older",
        created_at=created_at,
        updated_at=created_at,
    )
    newer = InteractiveSession(
        project_id=project.id,
        title="newer",
        created_at=created_at,
        updated_at=created_at + timedelta(minutes=1),
    )
    store.create_interactive_session(older)
    store.create_interactive_session(newer)
    run_time = created_at + timedelta(minutes=2)
    store.create_run(
        Run(
            project_id=project.id,
            session_id=older.id,
            task="revive older session",
            created_at=run_time,
            updated_at=run_time,
        )
    )

    sessions = store.list_interactive_sessions(project.id)

    assert sessions == [
        older.model_copy(update={"updated_at": run_time}),
        newer,
    ]


def test_legacy_database_migrates_without_losing_runs(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    project = Project(canonical_root=tmp_path)
    run = Run(project_id=project.id, task="legacy task")
    event = Event.new(
        "run.legacy",
        run.id,
        {"preserved": True},
        datetime.now(UTC),
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                canonical_root TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
                task TEXT NOT NULL,
                permission_mode TEXT NOT NULL,
                state TEXT NOT NULL,
                stop_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            PRAGMA user_version = 0;
            """
        )
        connection.execute(
            "INSERT INTO projects (id, canonical_root, created_at) VALUES (?, ?, ?)",
            (str(project.id), str(project.canonical_root), project.created_at.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, project_id, task, permission_mode, state, stop_reason,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(run.id),
                str(run.project_id),
                run.task,
                run.permission_mode.value,
                run.state.value,
                None,
                run.created_at.isoformat(),
                run.updated_at.isoformat(),
            ),
        )
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
                json.dumps(event.payload),
                event.timestamp.isoformat(),
            ),
        )

    SqliteEventStore(path)
    reopened = SqliteEventStore(path)

    assert reopened.get_run(run.id) == run
    assert reopened.get_run(run.id).session_id is None  # type: ignore[union-attr]
    assert reopened.list_for_run(run.id) == [event]
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert "session_id" in columns
    assert version == 1


def test_store_closes_connections_after_successful_operations(tmp_path: Path) -> None:
    store = TrackingSqliteEventStore(tmp_path / "state.db")
    assert_connection_closed(store.connections[-1])

    run = Run(task="close successful connections")
    store.create_run(run)
    assert_connection_closed(store.connections[-1])

    assert store.get_run(run.id) == run
    assert_connection_closed(store.connections[-1])


def test_store_closes_connection_after_exception_and_rolls_back(
    tmp_path: Path,
) -> None:
    store = TrackingSqliteEventStore(tmp_path / "state.db")
    missing_run = IterationRecord(
        run_id=uuid4(),
        iteration=1,
        state_before=RunState.RUNNING,
        state_after=RunState.WAITING_MODEL,
        timestamp=datetime.now(UTC),
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.save_iteration(missing_run)

    assert_connection_closed(store.connections[-1])
    with sqlite3.connect(store.path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM iterations").fetchone()[0]
    assert count == 0


def test_run_compare_and_set_rejects_a_stale_snapshot(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    original = Run(task="atomic status")
    store.create_run(original)
    paused = original.model_copy(
        update={
            "state": RunState.WAITING_APPROVAL,
            "updated_at": original.updated_at + timedelta(seconds=1),
        }
    )
    stale_terminal = original.model_copy(
        update={
            "state": RunState.CANCELLED,
            "stop_reason": StopReason.CANCELLED,
            "updated_at": original.updated_at + timedelta(seconds=2),
        }
    )

    assert store.compare_and_set_run(original, paused)
    assert not store.compare_and_set_run(original, stale_terminal)
    assert store.get_run(original.id) == paused


def test_run_and_events_round_trip_in_append_order(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    run = Run(task="fix parser", permission_mode=PermissionMode.BALANCED)
    store.create_run(run)
    assert store.get_run(run.id) == run

    timestamp = datetime.now(UTC)
    second = Event.new("run.second", run.id, {"order": 2}, timestamp)
    first = Event.new("run.first", run.id, {"order": 1}, timestamp)
    store.append(second)
    store.append(first)
    assert store.list_for_run(run.id) == [second, first]


def test_store_redacts_payload_even_for_direct_event_construction(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    run = Run(task="inspect config")
    store.create_run(run)
    event = Event(
        event_type="tool.completed",
        run_id=run.id,
        payload={"api_key": "must-not-persist", "ok": "visible"},
        timestamp=datetime.now(UTC),
    )
    store.append(event)
    restored = store.list_for_run(run.id)[0]
    assert restored.payload == {"api_key": "[REDACTED]", "ok": "visible"}
    assert b"must-not-persist" not in (tmp_path / "state.db").read_bytes()


def test_store_redacts_iteration_session_and_approval_payloads(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store = SqliteEventStore(path)
    run = Run(task="redact state")
    store.create_run(run)
    secret = "api_key=must-not-persist"
    call = ToolCall(
        name="edit_file", arguments={"path": "a.py", "content": secret}
    )
    store.save_iteration(
        IterationRecord(
            run_id=run.id,
            iteration=1,
            state_before=RunState.RUNNING,
            state_after=RunState.RUNNING,
            model_response={"content": secret},
            action=ActionEnvelope(action=call),
            tool_results=[{"stdout": secret}],
            validation={"stderr": secret},
            timestamp=datetime.now(UTC),
        )
    )
    store.save_loop_session(
        LoopSession(
            run_id=run.id,
            pending_call=call,
            validation_evidence=({"stdout": secret},),
            context_summary=secret,
        )
    )
    store.save_approval(
        ApprovalRequest(run_id=run.id, action=call, reason=secret)
    )

    assert b"must-not-persist" not in path.read_bytes()


def test_failed_iteration_write_rolls_back(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store = SqliteEventStore(path)
    missing_run = IterationRecord(
        run_id=uuid4(),
        iteration=1,
        state_before=RunState.RUNNING,
        state_after=RunState.WAITING_MODEL,
        timestamp=datetime.now(UTC),
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.save_iteration(missing_run)
    with sqlite3.connect(path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM iterations").fetchone()[0]
    assert count == 0


def test_iteration_and_session_update_roll_back_together(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    run = Run(task="atomic loop state")
    store.create_run(run)
    original = LoopSession(run_id=run.id, iteration=1)
    store.save_loop_session(original)
    first = IterationRecord(
        run_id=run.id,
        iteration=1,
        state_before=RunState.RUNNING,
        state_after=RunState.RUNNING,
        timestamp=datetime.now(UTC),
    )
    store.save_iteration(first)
    duplicate = first.model_copy(update={"id": uuid4()})

    with pytest.raises(sqlite3.IntegrityError):
        store.save_iteration_and_session(
            duplicate,
            LoopSession(run_id=run.id, iteration=2, state=RunState.PAUSED),
        )

    assert store.get_loop_session(run.id) == original


def test_concurrent_event_appends_are_serialized(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    run = Run(task="concurrency check")
    store.create_run(run)
    timestamp = datetime.now(UTC)
    events = [Event.new("worker.result", run.id, {"index": index}, timestamp) for index in range(20)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(store.append, events))
    restored = store.list_for_run(run.id)
    assert {event.payload["index"] for event in restored} == set(range(20))
