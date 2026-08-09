from __future__ import annotations

import pytest

from coding613.tui.app import CodingApp
from coding613.tui.widgets import ConversationLog, StatusFooter, TaskComposer


@pytest.mark.asyncio
async def test_tui_shell_focuses_composer_and_inserts_initial_task() -> None:
    app = CodingApp(initial_task="repair tests")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        composer = app.query_one(TaskComposer)
        assert app.focused is composer
        assert composer.text == "repair tests"
        assert app.query_one(ConversationLog).size.height > 0
        assert app.query_one(StatusFooter).size.height == 1


@pytest.mark.asyncio
async def test_tui_shell_stays_stable_in_narrow_terminal() -> None:
    app = CodingApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        composer = app.query_one(TaskComposer)
        footer = app.query_one(StatusFooter)
        log = app.query_one(ConversationLog)
        assert composer.region.width == footer.region.width == log.region.width == 60
        assert composer.region.height >= 3
        assert footer.region.y >= composer.region.bottom
