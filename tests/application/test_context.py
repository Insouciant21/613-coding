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
from coding613.domain.options import RunOptions


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


def test_context_loads_repository_instructions_and_builds_deterministic_ledger(
    tmp_path: Path,
) -> None:
    repository, project, run, _, _ = setup_memory(tmp_path)
    project_root = tmp_path / "repo"
    (project_root / "AGENTS.md").write_text(
        "Use the repository's existing test command. Never edit generated files.\n",
        encoding="utf-8",
    )
    assembler = ContextAssembler(
        repository,
        FakeIndex(),
        RecordingEmbedding(),
        repository_root=project_root,
    )
    events = (
        Event.new(
            "tool.completed",
            run.id,
            {
                "success": True,
                "call": {"name": "read_file", "arguments": {"path": "src/main.py"}},
                "output": "read evidence",
                "changed_files": [],
            },
            datetime.now(UTC),
        ),
        Event.new(
            "validation.completed",
            run.id,
            {"passed": True, "command": ["pytest"], "changed_files": []},
            datetime.now(UTC),
        ),
    )

    context = assembler.build(run.id, "inspect the repository", events)

    assert project.canonical_root == project_root
    assert any(
        "Never edit generated files" in message.content
        for message in context.messages
        if message.role == "system"
    )
    assert context.metadata["instruction_files"] == ["AGENTS.md"]
    assert context.metadata["ledger"]["last_validation"] == "passed"
    assert any(
        message.role == "user" and message.content.startswith("Run ledger")
        for message in context.messages
    )


def test_context_keeps_task_in_stable_prefix_before_changing_run_evidence(
    tmp_path: Path,
) -> None:
    repository, _, run, _, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(repository, FakeIndex(), RecordingEmbedding())
    event = Event.new(
        "tool.completed",
        run.id,
        {
            "success": True,
            "call": {"name": "read_file", "arguments": {"path": "src/app.py"}},
            "output": "fresh evidence",
            "changed_files": [],
        },
        datetime.now(UTC),
    )

    baseline = assembler.build(run.id, "inspect the repository", ())
    changed = assembler.build(run.id, "inspect the repository", (event,))
    task_index = next(
        index
        for index, message in enumerate(baseline.messages)
        if message.content == "inspect the repository"
    )

    assert all(message.role == "system" for message in baseline.messages[:task_index])
    assert tuple(baseline.messages[: task_index + 1]) == tuple(
        changed.messages[: task_index + 1]
    )
    assert baseline.metadata["cache_prefix_sha256"] == changed.metadata["cache_prefix_sha256"]
    assert changed.messages[task_index + 1].content.startswith("Run ledger (")


def test_context_compacts_old_event_messages_without_losing_task_or_latest_evidence(
    tmp_path: Path,
) -> None:
    repository, _, run, _, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(
        repository,
        FakeIndex(),
        RecordingEmbedding(),
        max_recent_events=8,
        max_message_chars=100,
        max_context_chars=520,
    )
    events = tuple(
        Event.new(
            "tool.completed",
            run.id,
            {
                "success": True,
                "call": {"name": "read_file", "arguments": {"path": f"{index}.py"}},
                "output": f"evidence-{index}-" + ("x" * 90),
                "changed_files": [],
            },
            datetime.now(UTC),
        )
        for index in range(6)
    )

    context = assembler.build(run.id, "inspect the latest evidence", events)

    assert context.messages[-1].content.startswith("Context compaction:")
    assert any(message.content == "inspect the latest evidence" for message in context.messages)
    assert context.metadata["omitted_event_count"] > 0
    assert "evidence-5" in context.model_dump_json()


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


def test_context_pins_recent_successful_read_evidence_after_event_tail_rollover(
    tmp_path: Path,
) -> None:
    repository, _, run, _, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(
        repository,
        FakeIndex(),
        RecordingEmbedding(),
        max_recent_events=2,
        max_pinned_tool_events=1,
    )
    read = Event.new(
        "tool.completed",
        run.id,
        {
            "success": True,
            "call": {"name": "read_file", "arguments": {"path": "state.ts"}},
            "output": "canonical CubeState contract",
            "changed_files": [],
        },
        datetime.now(UTC),
    )
    noise = tuple(
        Event.new("state.transition", run.id, {"step": index}, datetime.now(UTC))
        for index in range(3)
    )

    context = assembler.build(run.id, "repair the cube state", (read, *noise))

    assert any("canonical CubeState contract" in message.content for message in context.messages)
    assert any(message.content.startswith("Event state.transition:") for message in context.messages)


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
    assert any(
        message.content == "implement the missing file" for message in context.messages
    )
    assert context.messages[-1].content.startswith("Event feedback.tool_error:")


def test_context_escalates_after_repeated_validation_tool_errors_without_changes(
    tmp_path: Path,
) -> None:
    repository, _, run, _, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(repository, FakeIndex(), RecordingEmbedding())
    events = (
        Event.new(
            "feedback.tool_error",
            run.id,
            {"message": "objective validation produced tool_error", "details": {"changed_files": []}},
            datetime.now(UTC),
        ),
        Event.new(
            "validation.completed",
            run.id,
            {"passed": False, "stderr": "42 tests failed", "changed_files": []},
            datetime.now(UTC),
        ),
    )

    context = assembler.build(run.id, "repair the cube domain", events)

    assert any(
        "must edit" in message.content.lower()
        and "do not repeat read-only" in message.content.lower()
        and "run validation" in message.content.lower()
        for message in context.messages
    )


def test_context_gives_fresh_patch_guidance_after_patch_conflict(tmp_path: Path) -> None:
    repository, _, run, _, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(repository, FakeIndex(), RecordingEmbedding())
    event = Event.new(
        "feedback.tool_error",
        run.id,
        {
            "message": "apply_patch conflicted with repository content",
            "details": {
                "tool": "apply_patch",
                "error": "PatchConflictError: hunk context does not match",
                "changed_files": [],
            },
        },
        datetime.now(UTC),
    )

    context = assembler.build(run.id, "update the parser", (event,))

    assert any(
        "fresh patch" in message.content.lower()
        and "re-read" in message.content.lower()
        for message in context.messages
    )


def test_context_adds_explicit_repair_prompt_after_actionless_response(
    tmp_path: Path,
) -> None:
    repository, _, run, _, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(repository, FakeIndex(), RecordingEmbedding())
    event = Event.new(
        "feedback.invalid_action",
        run.id,
        {
            "message": (
                "provider response contained no tool action; call a repository tool"
            )
        },
        datetime.now(UTC),
    )

    context = assembler.build(run.id, "inspect the repository", (event,))

    assert any(
        message.role == "system"
        and "previous model response contained no tool action" in message.content.lower()
        and "call the appropriate repository tool" in message.content.lower()
        for message in context.messages
    )


def test_context_keeps_static_prefix_stable_during_repair_escalation(
    tmp_path: Path,
) -> None:
    repository, _, run, _, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(repository, FakeIndex(), RecordingEmbedding())
    events = (
        Event.new(
            "validation.completed",
            run.id,
            {"passed": False, "changed_files": []},
            datetime.now(UTC),
        ),
    )

    baseline = assembler.build(run.id, "repair the cube domain", ())
    repair = assembler.build(run.id, "repair the cube domain", events)

    def static_prefix(context: object) -> tuple[str, ...]:
        messages = context.messages  # type: ignore[attr-defined]
        prefix: list[str] = []
        for message in messages:
            if message.role != "system":
                break
            prefix.append(message.content)
        return tuple(prefix)

    assert static_prefix(repair) == static_prefix(baseline)
    assert "must edit" in repair.messages[-1].content.lower()


def test_worker_prompt_limits_initial_read_only_loop(tmp_path: Path) -> None:
    repository, _, run, _, _ = setup_memory(tmp_path)
    assembler = ContextAssembler(repository, FakeIndex(), RecordingEmbedding())

    context = assembler.build(run.id, "implement the missing state module", ())

    prompt = context.messages[0].content
    assert "at most two" in prompt.lower()
    assert "write action" in prompt.lower()
    action_messages = [
        message
        for message in context.messages
        if message.role == "system" and "select a write action" in message.content.lower()
    ]
    assert action_messages
    assert any(
        "read-only inspection tasks" in message.content.lower()
        and "do not invoke `run_validation`" in message.content
        for message in context.messages
        if message.role == "system"
    )

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
    assert any(message.content == "current task" for message in context.messages)


def test_session_context_merges_run_system_prompts_and_model_metadata(tmp_path: Path) -> None:
    repository, project, _, _, _ = setup_memory(tmp_path)
    store = SqliteEventStore(repository.path)
    session = InteractiveSession(project_id=project.id)
    store.create_interactive_session(session)
    run = Run(
        project_id=project.id,
        session_id=session.id,
        task="current",
        options=RunOptions(
            model="gpt-test",
            system_prompt="Use this repository convention.",
            append_system_prompt="Do not expose sk-test-secret-1234.",
        ),
    )
    store.create_run(run)
    builder = SessionContextBuilder(
        ContextAssembler(repository, FakeIndex(), RecordingEmbedding()), store
    )

    context = builder.build(run.id, run.task, ())

    assert context.metadata["model"] == "gpt-test"
    assert any("Use this repository convention." in message.content for message in context.messages)
    assert all("sk-test-secret-1234" not in message.content for message in context.messages)


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
