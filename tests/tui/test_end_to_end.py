from __future__ import annotations

from pathlib import Path

import pytest

from coding613.adapters.llm.mock import ScriptedLLM
from coding613.application.composition import build_services
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.models import PermissionMode
from coding613.ports.llm import LLMResponse
from coding613.tui.app import CodingApp
from coding613.tui.renderers import AssistantMessage, DetailMessage


def _response(action: object, content: str = "working") -> LLMResponse:
    return LLMResponse(content=content, actions=(ActionEnvelope(action=action),))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_tui_prompt_drives_real_harness_repository_change(tmp_path: Path) -> None:
    (tmp_path / "answer.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "harness.toml").write_text(
        '[validation]\ncommands = [["python", "-c", "print(\'ok\')"]]\n',
        encoding="utf-8",
    )
    provider = ScriptedLLM(
        (
            _response(
                ToolCall(
                    name="edit_file",
                    arguments={"path": "answer.txt", "content": "after\n"},
                )
            ),
            _response(
                ToolCall(
                    name="run_validation",
                    arguments={"argv": ["python", "-c", "print('ok')"]},
                )
            ),
            _response(FinishAction(summary="updated"), content="updated"),
        )
    )
    services = build_services(tmp_path, provider=provider)
    app = CodingApp(
        services=services,
        initial_task="update answer",
        permission_mode=PermissionMode.AUTONOMOUS,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(200):
            await pilot.pause(0.01)
            if len(provider.contexts) == 3 and any(
                "Run: completed" in item.display_text for item in app.query(DetailMessage)
            ):
                break

        assert (tmp_path / "answer.txt").read_text(encoding="utf-8") == "after\n"
        assert len(provider.contexts) == 3
        assert app.query(AssistantMessage)
        assert any("Run: completed" in item.display_text for item in app.query(DetailMessage))
