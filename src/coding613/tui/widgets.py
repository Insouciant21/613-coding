"""Stable shell widgets for the terminal conversation surface."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static, TextArea


class ConversationLog(VerticalScroll):
    """Scrollable conversation output owned by the controller."""


class UserMessage(Static):
    """A bounded, non-markup user task entry."""

    def __init__(self, text: str) -> None:
        self.message_text = text
        super().__init__(f"> {text}", classes="conversation-entry user-message", markup=False)


class ActiveOperation(Static):
    """Single-line current operation state."""

    def __init__(self) -> None:
        super().__init__("Idle", id="active-operation")


class TaskComposer(TextArea):
    """Multiline task editor with explicit submission."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, text: str = "") -> None:
        self._history: tuple[str, ...] = ()
        self._history_index = 0
        self._draft = text
        super().__init__(
            text,
            id="task-composer",
            soft_wrap=True,
            show_line_numbers=False,
            tooltip="Task composer",
        )

    def set_history(self, entries: tuple[str, ...]) -> None:
        self._history = tuple(entry for entry in entries if entry.strip())
        self._history_index = len(self._history)

    def history_previous(self) -> None:
        if not self._history:
            return
        if self._history_index == len(self._history):
            self._draft = self.text
        self._history_index = max(0, self._history_index - 1)
        self.load_text(self._history[self._history_index])

    def history_next(self) -> None:
        if not self._history or self._history_index >= len(self._history):
            return
        self._history_index += 1
        self.load_text(
            self._draft if self._history_index == len(self._history) else self._history[self._history_index]
        )

    def submit(self) -> None:
        value = self.text.strip()
        if value:
            self.post_message(self.Submitted(value))


class StatusFooter(Static):
    """One-line status and mode footer."""

    def __init__(self) -> None:
        super().__init__("613 Coding  |  balanced  |  ready", id="status-footer")
