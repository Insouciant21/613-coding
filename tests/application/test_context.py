from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from coding613.adapters.embeddings.openai_compatible import OpenAICompatibleEmbedding
from coding613.adapters.storage.lancedb_index import MemoryQuery, VectorHit
from coding613.adapters.storage.memory import MemoryRepository
from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.application.context import ContextAssembler, SessionContextBuilder
from coding613.domain.events import Event
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import MemoryEntry, MemoryType, Project, Run


class RecordingEmbedding:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.texts: list[str] = []

    def embed(self, texts: tuple[str, ...]) -> list[list[float]]:
        self.texts.extend(texts)
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return [[1.0, 0.0] for _ in texts]


class FakeIndex:
    def __init__(self, memory_ids: tuple = (), fail: bool = False) -> None:
        self.memory_ids = memory_ids
        self.fail = fail
        self.queries: list[MemoryQuery] = []

    def query(self, vector: tuple[float, ...], filters: MemoryQuery, limit: int) -> list[VectorHit]:
        self.queries.append(filters)
        if self.fail:
            raise RuntimeError("index unavailable")
        return [VectorHit(memory_id=memory_id, distance=float(index)) for index, memory_id in enumerate(self.memory_ids[:limit])]


def setup_memory(tmp_path: Path) -> tuple[MemoryRepository, Project, Run, MemoryEntry, MemoryEntry]:
    database = tmp_path / "state.db"
    store = SqliteEventStore(database)
    root = tmp_path / "repo"
    root.mkdir()
    project = Project(canonical_root=root)
    store.create_project(project)
    run = Run(project_id=project.id, task="fix parser")
    store.create_run(run)
    repository = MemoryRepository(database)
    public = MemoryEntry(
        project_id=project.id,
        memory_type=MemoryType.PROJECT_CONVENTION,
        text="parser uses strict mode",
        permission_tags=frozenset({"public"}),
    )
    private = MemoryEntry(
        project_id=project.id,
        memory_type=MemoryType.PROJECT_CONVENTION,
        text="private parser note",
        permission_tags=frozenset({"private"}),
    )
    repository.put(public)
    repository.put(private)
    return repository, project, run, public, private


def test_context_uses_authoritative_text_and_final_permission_filter(tmp_path: Path) -> None:
    repository, project, run, public, private = setup_memory(tmp_path)
    embedding = RecordingEmbedding()
    assembler = ContextAssembler(
        repository,
        FakeIndex((private.id, public.id)),
        embedding,
        allowed_permission_tags=frozenset({"public"}),
        max_memories=3,
    )
    context = assembler.build(run.id, "fix sk-test-secret-1234 parser", ())
    assert embedding.texts == ["fix [REDACTED] parser"]
    assert context.metadata["memory_ids"] == [str(public.id)]
    assert any("parser uses strict mode" in message.content for message in context.messages)
    assert "private parser note" not in context.model_dump_json()
    assert assembler.last_query == MemoryQuery(
        project_id=project.id, allowed_permission_tags=frozenset({"public"})
    )


def test_context_falls_back_to_sqlite_keyword_search_and_bounds_events(tmp_path: Path) -> None:
    repository, _, run, public, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(
        repository,
        FakeIndex(fail=True),
        RecordingEmbedding(fail=True),
        allowed_permission_tags=frozenset({"public"}),
        max_memories=1,
        max_recent_events=1,
    )
    events = (
        Event.new("old", run.id, {"n": 1}, datetime.now(UTC)),
        Event.new("new", run.id, {"n": 2}, datetime.now(UTC)),
    )
    context = assembler.build(run.id, "fix parser", events)
    assert context.metadata["memory_ids"] == [str(public.id)]
    assert context.messages[-1].content.endswith('{"n":2}')
    assert all("old" not in message.content for message in context.messages)


def test_context_serializes_persisted_events_without_unmatched_tool_messages(
    tmp_path: Path,
) -> None:
    repository, _, run, _, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(repository, FakeIndex(), RecordingEmbedding())
    event = Event.new(
        "state.transition",
        run.id,
        {"from": "running", "to": "waiting_model"},
        datetime.now(UTC),
    )

    context = assembler.build(run.id, "fix parser", (event,))

    assert context.messages[-1].role == "user"
    assert context.messages[-1].content.startswith("Event state.transition:")


def test_context_keeps_goal_directed_worker_instructions_ahead_of_run_history(
    tmp_path: Path,
) -> None:
    repository, _, run, _, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(repository, FakeIndex(), RecordingEmbedding())
    event = Event.new(
        "feedback.tool_error",
        run.id,
        {"message": "objective validation failed"},
        datetime.now(UTC),
    )

    context = assembler.build(run.id, "implement the missing file", (event,))

    instruction = context.messages[0]
    assert instruction.role == "system"
    assert "Act directly on the repository" in instruction.content
    assert "Do not repeat successful read-only actions" in instruction.content
    assert "objective validation" in instruction.content
    assert context.messages[-2].content == "implement the missing file"
    assert context.messages[-1].content.startswith("Event feedback.tool_error:")


def test_session_context_bounds_and_redacts_prior_transcript(tmp_path: Path) -> None:
    repository, project, _, _, _ = setup_memory(tmp_path)
    store = SqliteEventStore(repository.path)
    session = InteractiveSession(project_id=project.id)
    store.create_interactive_session(session)
    prior: list[Run] = []
    for index in range(13):
        run = Run(
            project_id=project.id,
            session_id=session.id,
            task=f"history {index} sk-test-secret-1234",
        )
        store.create_run(run)
        prior.append(run)
    current = Run(project_id=project.id, session_id=session.id, task="current task")
    store.create_run(current)
    builder = SessionContextBuilder(
        ContextAssembler(repository, FakeIndex(), RecordingEmbedding()),
        store,
    )

    context = builder.build(current.id, current.task, ())

    transcript = [
        message for message in context.messages if message.role == "user" and "history" in message.content
    ]
    assert len(transcript) == 12
    assert all("sk-test-secret-1234" not in message.content for message in transcript)
    assert any(message.content == "Omitted 1 earlier transcript entries." for message in context.messages)
    assert context.messages[-1].content == "current task"


def test_openai_compatible_embedding_maps_single_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/embeddings"
        assert payload == {"input": ["a", "b"], "model": "embed-model"}
        return httpx.Response(
            200,
            json={"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbedding(
            base_url="https://provider.invalid/v1", model="embed-model", http_client=client
        )
        assert provider.embed(("a", "b")) == [[1.0, 0.0], [0.0, 1.0]]
