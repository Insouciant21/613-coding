from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from coding_harness.adapters.embeddings.mock import DeterministicEmbedding
from coding_harness.adapters.storage.lancedb_index import (
    LanceMemoryIndex,
    MemoryQuery,
    VectorEntry,
)
from coding_harness.adapters.storage.memory import MemoryRepository
from coding_harness.adapters.storage.sqlite import SqliteEventStore
from coding_harness.domain.models import MemoryEntry, MemoryType, Project


def test_sqlite_memory_is_authoritative_and_redacted(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    store = SqliteEventStore(database)
    root = tmp_path / "repo"
    root.mkdir()
    project = Project(canonical_root=root)
    store.create_project(project)
    repository = MemoryRepository(database)
    entry = MemoryEntry(
        project_id=project.id,
        memory_type=MemoryType.FAILURE_PATTERN,
        text="parser failed with sk-test-secret-1234",
        permission_tags=frozenset({"public"}),
    )
    repository.put(entry)
    restored = repository.get(entry.id)
    assert restored is not None
    assert "sk-test-secret-1234" not in restored.text
    assert "[REDACTED]" in restored.text
    assert repository.search_keyword("parser", project.id) == [restored]
    assert b"sk-test-secret-1234" not in database.read_bytes()


def test_lancedb_top_k_filters_project_type_and_permissions(tmp_path: Path) -> None:
    first_project = uuid4()
    second_project = uuid4()
    public_id = uuid4()
    private_id = uuid4()
    other_id = uuid4()
    index = LanceMemoryIndex(tmp_path / "vectors", dimension=3)
    index.upsert(
        (
            VectorEntry(
                memory_id=public_id,
                project_id=first_project,
                memory_type=MemoryType.PROJECT_CONVENTION,
                permission_tags=frozenset({"public"}),
                vector=(1.0, 0.0, 0.0),
            ),
            VectorEntry(
                memory_id=private_id,
                project_id=first_project,
                memory_type=MemoryType.PROJECT_CONVENTION,
                permission_tags=frozenset({"private"}),
                vector=(0.99, 0.01, 0.0),
            ),
            VectorEntry(
                memory_id=other_id,
                project_id=second_project,
                memory_type=MemoryType.PROJECT_CONVENTION,
                permission_tags=frozenset({"public"}),
                vector=(1.0, 0.0, 0.0),
            ),
        )
    )
    hits = index.query(
        (1.0, 0.0, 0.0),
        MemoryQuery(
            project_id=first_project,
            memory_types=frozenset({MemoryType.PROJECT_CONVENTION}),
            allowed_permission_tags=frozenset({"public"}),
        ),
        limit=5,
    )
    assert [hit.memory_id for hit in hits] == [public_id]


def test_project_delete_removes_sqlite_and_lance_rows(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    store = SqliteEventStore(database)
    root = tmp_path / "repo"
    root.mkdir()
    project = Project(canonical_root=root)
    store.create_project(project)
    repository = MemoryRepository(database)
    entry = MemoryEntry(
        project_id=project.id,
        memory_type=MemoryType.TASK_SUMMARY,
        text="summary",
    )
    repository.put(entry)
    index = LanceMemoryIndex(tmp_path / "vectors", dimension=2)
    index.upsert(
        (
            VectorEntry(
                memory_id=entry.id,
                project_id=project.id,
                memory_type=entry.memory_type,
                vector=(1.0, 0.0),
            ),
        )
    )
    repository.delete_project(project.id)
    index.delete_project(project.id)
    assert repository.get(entry.id) is None
    assert index.query(
        (1.0, 0.0), MemoryQuery(project_id=project.id), limit=5
    ) == []


def test_mock_embedding_is_deterministic_and_dimensioned() -> None:
    provider = DeterministicEmbedding(dimension=6)
    assert provider.embed(("same",))[0] == provider.embed(("same",))[0]
    assert len(provider.embed(("same",))[0]) == 6
    assert provider.embed(("same",))[0] != provider.embed(("different",))[0]
