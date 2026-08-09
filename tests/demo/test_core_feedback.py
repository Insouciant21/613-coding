from pathlib import Path

from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.demo.core_feedback import run_core_feedback_demo
from coding613.domain.models import RunState


def test_core_feedback_demo_is_offline_deterministic_and_complete(tmp_path: Path) -> None:
    result = run_core_feedback_demo(tmp_path)
    assert result.summary.status is RunState.COMPLETED
    assert result.feedback_observed
    assert result.guardrail_blocked
    assert result.memory_retrieved
    assert result.changed_file_text.endswith("return 2\n")
    store = SqliteEventStore(tmp_path / "demo-state.sqlite")
    persisted = store.get_run(result.summary.run_id)
    assert persisted is not None
    assert persisted.state is RunState.COMPLETED
