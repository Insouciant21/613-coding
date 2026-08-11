from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from coding613.adapters.llm.mock import ScriptedLLM
from coding613.application.composition import build_services
from coding613.application.interactive import ConversationInteractiveAdapter
from coding613.application.progress import CancellationToken
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.conversation import RunOptions
from coding613.domain.models import RunState
from coding613.ports.llm import LLMResponse
from coding613.ports.progress import NullProgressSink


def _configured_repo(path: Path) -> None:
    (path / "answer.txt").write_text("answer\n", encoding="utf-8")
    (path / "harness.toml").write_text(
        """
[validation]
commands = [["python", "-c", "print('ok')"]]
""",
        encoding="utf-8",
    )


def _turn(final_text: str) -> tuple[LLMResponse, LLMResponse, LLMResponse]:
    return (
        LLMResponse(
            content="working",
            actions=(
                ActionEnvelope(
                    action=ToolCall(name="read_file", arguments={"path": "answer.txt"})
                ),
            ),
        ),
        LLMResponse(
            actions=(
                ActionEnvelope(
                    action=ToolCall(
                        name="run_validation",
                        arguments={"argv": ["python", "-c", "print('ok')"]},
                    )
                ),
            ),
        ),
        LLMResponse(
            content=final_text,
            actions=(ActionEnvelope(action=FinishAction(summary=final_text)),),
        ),
    )


def test_interactive_session_restores_distinct_runs_and_transcript(tmp_path: Path) -> None:
    _configured_repo(tmp_path)
    provider = ScriptedLLM((*_turn("first final"), *_turn("second final")))
    services = build_services(tmp_path, provider=provider)
    session = services.interactive.create("Repair tests")

    first = services.interactive.submit(session.id, "first task")
    first_summary = services.interactive.execute(
        first.id, NullProgressSink(), CancellationToken()
    )
    second = services.interactive.submit(session.id, "second task")
    second_summary = services.interactive.execute(
        second.id, NullProgressSink(), CancellationToken()
    )

    assert first.id != second.id
    assert first.session_id == second.session_id == session.id
    assert first_summary.status is second_summary.status is RunState.COMPLETED

    restarted = build_services(tmp_path)
    snapshot = restarted.interactive.resume_session(session.id)
    assert [run.id for run in snapshot.runs] == [first.id, second.id]
    assert snapshot.active_run is None
    assert [(entry.role, entry.text) for entry in snapshot.transcript] == [
        ("user", "first task"),
        ("assistant", "first final"),
        ("user", "second task"),
        ("assistant", "second final"),
    ]


def test_interactive_snapshot_returns_latest_paused_run_as_active(tmp_path: Path) -> None:
    services = build_services(tmp_path)
    session = services.interactive.create()
    run = services.interactive.submit(session.id, "pause me")

    services.run_service.pause(run.id)
    snapshot = services.interactive.resume_session(session.id)

    assert snapshot.active_run is not None
    assert snapshot.active_run.id == run.id
    assert snapshot.active_run.state is RunState.PAUSED


def test_finish_summary_is_used_when_final_model_content_is_empty(tmp_path: Path) -> None:
    _configured_repo(tmp_path)
    provider = ScriptedLLM(
        (
            LLMResponse(content="I will inspect the project first."),
            LLMResponse(
                actions=(
                    ActionEnvelope(
                        action=FinishAction(summary="docker compose up -d")
                    ),
                )
            ),
        )
    )
    services = build_services(tmp_path, provider=provider)
    session = services.interactive.create("Startup command")
    run = services.interactive.submit(session.id, "give me the startup command")

    summary = services.interactive.execute(
        run.id, NullProgressSink(), CancellationToken()
    )
    snapshot = services.interactive.resume_session(session.id)

    assert summary.status is RunState.COMPLETED
    assert [(entry.role, entry.text) for entry in snapshot.transcript] == [
        ("user", "give me the startup command"),
        ("assistant", "docker compose up -d"),
    ]


@pytest.mark.parametrize("message", ["", "   ", "x" * 100_001])
def test_interactive_submit_rejects_invalid_message(tmp_path: Path, message: str) -> None:
    services = build_services(tmp_path)
    session = services.interactive.create()

    with pytest.raises(ValueError):
        services.interactive.submit(session.id, message)


def test_legacy_interactive_adapter_delegates_to_conversation_service() -> None:
    class FakeConversation:
        def create_session(self, title=None):
            return ("session", title)

        def submit(self, request):
            return request

        def execute(self, run_id, sink, cancellation):
            return (run_id, sink, cancellation)

        def snapshot(self, session_id):
            return ("snapshot", session_id)

        def sessions(self):
            return ["session"]

    adapter = ConversationInteractiveAdapter(FakeConversation(), uuid4())
    session = adapter.create("title")
    session_id = uuid4()
    submitted = adapter.submit(session_id, "repair", options=RunOptions(model="test"))

    assert session == ("session", "title")
    assert submitted.text == "repair"
    assert submitted.session_id == session_id
    assert adapter.resume_session(session_id) == ("snapshot", session_id)
    assert adapter.list_sessions() == ["session"]
