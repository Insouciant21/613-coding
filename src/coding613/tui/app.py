"""Claude Code-like local Textual shell."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding

from .widgets import ActiveOperation, ConversationLog, StatusFooter, TaskComposer

if TYPE_CHECKING:
    from coding613.application.composition import LocalServices


class CodingApp(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "613 Coding"
    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("enter", "submit_task", "Submit", priority=True),
        Binding("ctrl+j", "insert_newline", "New line", show=False, priority=True),
        Binding("escape", "pause_run", "Pause", priority=True),
        Binding("ctrl+c", "confirm_exit", "Pause / exit", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(
        self,
        *,
        services: LocalServices | None = None,
        initial_task: str | None = None,
        resume: str | None = None,
    ) -> None:
        super().__init__()
        self.services = services
        self.initial_task = initial_task
        self.resume = resume

    def compose(self) -> ComposeResult:
        yield ConversationLog(id="conversation-log")
        yield ActiveOperation()
        yield TaskComposer(self.initial_task or "")
        yield StatusFooter()

    def on_mount(self) -> None:
        self.query_one(TaskComposer).focus()

    def action_submit_task(self) -> None:
        self.query_one(TaskComposer).submit()

    def action_insert_newline(self) -> None:
        self.query_one(TaskComposer).insert("\n")

    def action_pause_run(self) -> None:
        self.query_one(ActiveOperation).update("Pause requested")

    def action_confirm_exit(self) -> None:
        self.query_one(StatusFooter).update("Press Ctrl+Q to exit; Esc resumes editing")
