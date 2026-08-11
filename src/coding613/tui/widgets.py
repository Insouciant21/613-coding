"""Stable shell widgets for the terminal conversation surface."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import OptionList, Static, TextArea
from textual.widgets.option_list import Option


class ConversationLog(VerticalScroll):
    """Scrollable conversation output owned by the controller."""


class ConfigMenu(OptionList):
    """Keyboard-selectable menu for common project/user configuration edits."""

    def __init__(self, options: tuple[tuple[str, str], ...]) -> None:
        super().__init__(
            *(Option(label, id=action) for label, action in options),
            id="config-menu",
            classes="conversation-entry config-menu",
            markup=False,
        )


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
        self._completion_matches: tuple[str, ...] = ()
        self._completion_index = -1
        super().__init__(
            text,
            id="task-composer",
            soft_wrap=True,
            show_line_numbers=False,
        )

    @property
    def completion_matches(self) -> tuple[str, ...]:
        """Return the currently available top-level slash completions."""

        return self._completion_matches

    @property
    def completion_index(self) -> int:
        """Return the selected completion index, or ``-1`` for a prefix."""

        return self._completion_index

    def set_completion_matches(self, matches: tuple[str, ...]) -> None:
        """Update completion choices while retaining an already selected item."""

        self._completion_matches = tuple(matches)
        try:
            self._completion_index = self._completion_matches.index(self.text)
        except ValueError:
            self._completion_index = -1

    def cycle_completion(self, direction: int = 1) -> bool:
        """Replace a slash prefix with the next or previous completion."""

        if not self._completion_matches:
            return False
        if self._completion_index < 0:
            index = 0 if direction >= 0 else len(self._completion_matches) - 1
        else:
            index = (self._completion_index + (1 if direction >= 0 else -1)) % len(
                self._completion_matches
            )
        value = self._completion_matches[index]
        self.load_text(value)
        self.move_cursor((0, len(value)))
        self._completion_index = index
        return True

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


class CommandHints(Static):
    """Transient slash-command completion and discovery hints."""

    def __init__(self) -> None:
        super().__init__("", id="command-hints", classes="command-hints", markup=False)
        self.display = False

    def update_matches(self, matches: tuple[str, ...], selected: int = -1) -> None:
        if not matches:
            self.update("")
            self.display = False
            return
        choices = "  ".join(
            f"»{value}«" if index == selected else value
            for index, value in enumerate(matches)
        )
        self.update(
            f"Commands: {choices}\n"
            "Tab complete · ↑/↓ choose · Enter run · /help full list"
        )
        self.display = True


class UsageHints(Static):
    """Persistent keyboard and command-discovery hints."""

    def __init__(self) -> None:
        super().__init__(
            "Enter send · Ctrl+J newline · ↑/↓ history (or slash choices) · "
            "Esc pause · Ctrl+Q exit · Ctrl+T expand tool · A/R approval · /help commands",
            id="usage-hints",
            classes="usage-hints",
            markup=False,
        )
