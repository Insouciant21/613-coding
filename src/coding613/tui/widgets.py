"""Stable shell widgets for the terminal conversation surface."""

from __future__ import annotations

from collections.abc import Mapping

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Select, Static, TextArea
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


class ProviderEditorScreen(ModalScreen[dict[str, str] | None]):
    """Modal form for adding or editing provider metadata.

    The screen only collects strings.  Validation, persistence, and keyring
    writes stay in the application service that owns provider configuration.
    A blank API-key field deliberately means "leave the current key alone".
    """

    def __init__(
        self,
        initial: Mapping[str, str] | None = None,
        *,
        editing: bool = False,
    ) -> None:
        super().__init__()
        self._initial = dict(initial or {})
        self._editing = editing

    def compose(self) -> ComposeResult:
        values = self._initial
        yield Container(
            Static("Edit provider" if self._editing else "Add provider", classes="provider-form-title"),
            Static(
                "API keys are stored in the OS keyring. Leave API key blank to keep the current key.",
                classes="provider-form-help",
            ),
            VerticalScroll(
                Input(
                    values.get("name", ""),
                    placeholder="Provider name",
                    id="provider-name",
                    disabled=self._editing,
                ),
                Input(values.get("provider", "openai-compatible"), placeholder="Provider kind", id="provider-kind"),
                Select(
                    (("Responses", "responses"), ("Chat Completions", "chat_completions"), ("Anthropic Messages", "anthropic"), ("Messages alias", "messages")),
                    value=values.get("api", "responses"),
                    prompt="API surface",
                    allow_blank=False,
                    id="provider-api",
                ),
                Input(values.get("base_url", ""), placeholder="Base URL", id="provider-base-url"),
                Input(values.get("model", ""), placeholder="Default model", id="provider-model"),
                Input(values.get("credential", ""), placeholder="Keyring credential name", id="provider-credential"),
                Input(values.get("timeout_seconds", "120"), placeholder="Timeout seconds", id="provider-timeout"),
                Input(values.get("max_output_tokens", "128000"), placeholder="Max output tokens", id="provider-max-output"),
                Input(values.get("context_window_chars", "256000"), placeholder="Context window characters", id="provider-context"),
                Select(
                    (("Streaming off", "false"), ("Streaming on", "true")),
                    value=values.get("streaming", "false"),
                    prompt="Streaming",
                    allow_blank=False,
                    id="provider-streaming",
                ),
                Input(values.get("reasoning_effort", "low"), placeholder="Reasoning level", id="provider-reasoning"),
                Input("", placeholder="API key (optional)", password=True, id="provider-api-key"),
                Select(
                    (("Keep inactive", "false"), ("Make active", "true")),
                    value=values.get("make_active", "false"),
                    prompt="Activation",
                    allow_blank=False,
                    id="provider-active",
                ),
            ),
            Horizontal(
                Button("Save", variant="success", id="provider-save"),
                Button("Cancel", variant="default", id="provider-cancel"),
                classes="provider-form-actions",
            ),
            id="provider-editor",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "provider-cancel":
            self.dismiss(None)
            return
        if event.button.id != "provider-save":
            return
        values: dict[str, str] = {}
        input_fields = {
            "name": "name",
            "provider": "kind",
            "base_url": "base-url",
            "model": "model",
            "credential": "credential",
            "timeout_seconds": "timeout",
            "max_output_tokens": "max-output",
            "context_window_chars": "context",
            "reasoning_effort": "reasoning",
            "api_key": "api-key",
        }
        for field, selector in input_fields.items():
            values[field] = self.query_one(f"#provider-{selector}", Input).value
        for field in ("api", "streaming", "active"):
            selected = self.query_one(f"#provider-{field}", Select).value
            values[field] = "" if selected is Select.BLANK else str(selected)
        self.dismiss(values)

    def on_key(self, event: object) -> None:
        if getattr(event, "key", None) == "escape":
            stop = getattr(event, "stop", None)
            if callable(stop):
                stop()
            self.dismiss(None)


class ProviderKeyScreen(ModalScreen[str | None]):
    """Hidden-input modal for setting one provider's API key."""

    def __init__(self, provider: str) -> None:
        super().__init__()
        self.provider = provider

    def compose(self) -> ComposeResult:
        yield Container(
            Static(f"Set API key: {self.provider}", classes="provider-form-title"),
            Static("The key is written directly to the OS keyring and never shown in the log.", classes="provider-form-help"),
            Input(placeholder="API key", password=True, id="provider-key-value"),
            Horizontal(
                Button("Save key", variant="success", id="provider-key-save"),
                Button("Cancel", id="provider-key-cancel"),
                classes="provider-form-actions",
            ),
            id="provider-key-editor",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "provider-key-cancel":
            self.dismiss(None)
        elif event.button.id == "provider-key-save":
            self.dismiss(self.query_one("#provider-key-value", Input).value)

    def on_key(self, event: object) -> None:
        if getattr(event, "key", None) == "escape":
            stop = getattr(event, "stop", None)
            if callable(stop):
                stop()
            self.dismiss(None)


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
