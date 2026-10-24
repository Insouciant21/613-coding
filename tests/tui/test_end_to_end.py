from __future__ import annotations

from pathlib import Path

import pytest

from coding613.adapters.llm.mock import ScriptedLLM
from coding613.application.composition import build_services
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.models import PermissionMode
from coding613.ports.llm import LLMResponse, ModelContext, ToolDefinition
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


@pytest.mark.asyncio
async def test_tui_accepts_second_submission_after_completed_run(
    tmp_path: Path,
) -> None:
    from coding613.tui.widgets import TaskComposer

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
            _response(FinishAction(summary="second done"), content="second done"),
        )
    )
    services = build_services(tmp_path, provider=provider)
    app = CodingApp(
        services=services,
        initial_task="update answer",
        permission_mode=PermissionMode.AUTONOMOUS,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(300):
            await pilot.pause(0.01)
            if len(provider.contexts) == 3 and any(
                "Run: completed" in item.display_text for item in app.query(DetailMessage)
            ):
                break
        assert len(provider.contexts) == 3
        composer = app.query_one(TaskComposer)
        state = {"executing": app._executing, "disabled": composer.disabled,
                 "focused": type(app.focused).__name__ if app.focused else None}
        composer.load_text("inspect again and finish")
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(300):
            await pilot.pause(0.01)
            if len(provider.contexts) >= 4:
                break
        assert len(provider.contexts) >= 4, (
            f"second submission never started; state after first run: {state}"
        )


@pytest.mark.asyncio
async def test_tui_accepts_second_submission_after_streamed_run(
    tmp_path: Path,
) -> None:
    from collections import deque
    from collections.abc import Callable, Sequence

    from coding613.adapters.llm.mock import MockScriptExhausted
    from coding613.application.progress import ProviderCancelledError
    from coding613.ports.llm import StreamingLLMProvider
    from coding613.tui.widgets import TaskComposer

    class StreamingScriptedLLM(StreamingLLMProvider):
        def __init__(self, responses: Sequence[LLMResponse]) -> None:
            self._responses = deque(responses)
            self.contexts: list[ModelContext] = []
            self.tools: list[tuple[ToolDefinition, ...]] = []
            self.streaming_enabled = True

        def complete(
            self, context: ModelContext, tools: Sequence[ToolDefinition]
        ) -> LLMResponse:
            self.contexts.append(context.model_copy(deep=True))
            self.tools.append(tuple(t.model_copy(deep=True) for t in tools))
            if not self._responses:
                raise MockScriptExhausted("scripted LLM response sequence is exhausted")
            return self._responses.popleft()

        def complete_stream(
            self,
            context: ModelContext,
            tools: Sequence[ToolDefinition],
            on_text_delta: Callable[[str], None],
            cancelled: Callable[[], bool],
        ) -> LLMResponse:
            on_text_delta("working ")
            if cancelled():
                raise ProviderCancelledError("cancelled")
            return self.complete(context, tools)

    (tmp_path / "answer.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "harness.toml").write_text(
        '[validation]\ncommands = [["python", "-c", "print(\'ok\')"]]\n',
        encoding="utf-8",
    )
    provider = StreamingScriptedLLM(
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
            _response(FinishAction(summary="second done"), content="second done"),
        )
    )
    services = build_services(tmp_path, provider=provider)
    app = CodingApp(
        services=services,
        initial_task="update answer",
        permission_mode=PermissionMode.AUTONOMOUS,
    )

    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(300):
            await pilot.pause(0.01)
            if len(provider.contexts) == 3 and any(
                "Run: completed" in item.display_text for item in app.query(DetailMessage)
            ):
                break
        composer = app.query_one(TaskComposer)
        state = {"executing": app._executing, "disabled": composer.disabled,
                 "focused": type(app.focused).__name__ if app.focused else None}
        composer.load_text("inspect again and finish")
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(300):
            await pilot.pause(0.01)
            if len(provider.contexts) >= 4:
                break
        assert len(provider.contexts) >= 4, (
            f"second submission never started after streamed run; state: {state}"
        )


@pytest.mark.asyncio
async def test_slash_command_output_visible_and_input_cleared_after_run(
    tmp_path: Path,
) -> None:
    from coding613.tui.widgets import ConversationLog, TaskComposer

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

    async with app.run_test(size=(80, 10)) as pilot:  # tiny screen forces overflow
        for _ in range(300):
            await pilot.pause(0.01)
            if len(provider.contexts) == 3 and any(
                "Run: completed" in item.display_text for item in app.query(DetailMessage)
            ):
                break
        assert len(provider.contexts) == 3
        log_widget = app.query_one(ConversationLog)
        composer = app.query_one(TaskComposer)

        composer.load_text("/cost")
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(100):
            await pilot.pause(0.01)

        assert composer.text == "", "slash command submission must clear the composer"
        assert any(
            "Resource usage" in getattr(child, "display_text", getattr(child, "renderable", ""))
            if hasattr(child, "display_text")
            else "Resource usage" in str(getattr(child, "renderable", ""))
            for child in log_widget.children
        ), "command output must be mounted"
        assert log_widget.max_scroll_y > 0, "test setup must overflow the tiny screen"
        assert (
            log_widget.scroll_offset.y >= log_widget.max_scroll_y - 1
        ), "log must scroll to the newest command output instead of hiding it below the fold"
