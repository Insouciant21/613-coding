from __future__ import annotations

from pathlib import Path

from coding613.adapters.llm.mock import ScriptedLLM
from coding613.application.composition import build_services
from coding613.application.progress import CancellationToken
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.conversation import PromptRequest
from coding613.domain.models import RunState
from coding613.ports.llm import LLMResponse
from coding613.ports.progress import NullProgressSink


def test_conversation_service_selects_latest_session_and_executes(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        "[validation]\ncommands = [[\"python\", \"-c\", \"print('ok')\"]]\n",
        encoding="utf-8",
    )
    validate = LLMResponse(
        actions=(
            ActionEnvelope(
                action=ToolCall(
                    name="run_validation",
                    arguments={"argv": ["python", "-c", "print('ok')"]},
                )
            ),
        )
    )
    finish = LLMResponse(
        content="done",
        actions=(ActionEnvelope(action=FinishAction(summary="done")),),
    )
    provider = ScriptedLLM((validate, finish, validate, finish))
    services = build_services(tmp_path, provider=provider)
    conversation = services.conversation

    first = conversation.submit(
        PromptRequest(project_id=services.run_service.project.id, text="first")
    )
    services.run_service.resume(first.id, progress=NullProgressSink(), cancellation=CancellationToken())
    second = conversation.submit(
        PromptRequest(
            project_id=services.run_service.project.id,
            text="second",
            continue_latest=True,
        )
    )

    assert second.session_id == first.session_id
    summary = conversation.execute(second.id, NullProgressSink(), CancellationToken())
    assert summary.status is RunState.COMPLETED
    snapshot = conversation.snapshot(second.session_id)  # type: ignore[arg-type]
    assert [run.id for run in snapshot.runs] == [first.id, second.id]
