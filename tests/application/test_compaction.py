from __future__ import annotations

from pathlib import Path

from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.application.context import ContextService
from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import Project, Run


class FakeCompactor:
    def __init__(self, text: str = "compact summary") -> None:
        self.text = text
        self.calls: list[tuple[object, int]] = []

    def compact(self, transcript, max_chars: int) -> str:
        self.calls.append((transcript, max_chars))
        return self.text


def test_context_report_counts_omitted_entries_without_deleting_transcript(
    tmp_path: Path,
) -> None:
    store = SqliteEventStore(tmp_path / "state.sqlite")
    project = Project(canonical_root=tmp_path)
    store.create_project(project)
    session = InteractiveSession(project_id=project.id)
    store.create_interactive_session(session)
    for index in range(3):
        store.create_run(
            Run(project_id=project.id, session_id=session.id, task=f"history {index}")
        )
    compactor = FakeCompactor()
    service = ContextService(store, compactor=compactor, max_entries=2, max_chars=64)

    summary = service.report(session.id)
    before = store.list_runs_for_session(session.id)
    compacted = service.compact(session.id)

    assert summary.estimated_tokens > 0
    assert summary.omitted_sources
    assert store.list_runs_for_session(session.id) == before
    assert compacted.estimated_tokens > 0
    assert compactor.calls
    assert store.get_context_summary(session.id) is not None


def test_failed_compaction_does_not_persist_a_summary(tmp_path: Path) -> None:
    class FailingCompactor:
        def compact(self, transcript, max_chars: int) -> str:
            del transcript, max_chars
            raise RuntimeError("compactor unavailable")

    store = SqliteEventStore(tmp_path / "state.sqlite")
    project = Project(canonical_root=tmp_path)
    store.create_project(project)
    session = InteractiveSession(project_id=project.id)
    store.create_interactive_session(session)
    store.create_run(Run(project_id=project.id, session_id=session.id, task="history"))
    service = ContextService(store, compactor=FailingCompactor())

    try:
        service.compact(session.id)
    except RuntimeError:
        pass
    else:
        raise AssertionError("failed compaction must propagate")

    assert store.get_context_summary(session.id) is None
