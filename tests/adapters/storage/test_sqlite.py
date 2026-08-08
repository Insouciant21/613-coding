from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from coding_harness.adapters.storage.sqlite import SqliteEventStore
from coding_harness.domain.actions import ActionEnvelope, ToolCall
from coding_harness.domain.events import Event
from coding_harness.domain.models import (
    ApprovalRequest,
    IterationRecord,
    LoopSession,
    PermissionMode,
    Run,
    RunState,
)


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
        "iterations",
        "loop_sessions",
        "events",
        "approvals",
        "task_graphs",
        "artifacts",
        "memory_entries",
        "embedding_status",
    } <= tables


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
