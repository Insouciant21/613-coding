from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from coding_harness.adapters.storage.sqlite import SqliteEventStore
from coding_harness.domain.events import Event
from coding_harness.domain.models import IterationRecord, PermissionMode, Run, RunState


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
