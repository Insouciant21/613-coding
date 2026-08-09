"""Strict slash-command parsing for the local TUI."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    name: str
    arguments: tuple[str, ...] = ()


class SlashCommand:
    _NO_ARGUMENTS = frozenset({"help", "model", "runs", "clear", "quit"})
    _PERMISSION_MODES = frozenset({"strict", "balanced", "autonomous"})

    @classmethod
    def parse(cls, text: str) -> ParsedCommand:
        if not text.startswith("/"):
            raise ValueError("slash command must start with /")
        try:
            parts = shlex.split(text[1:])
        except ValueError as error:
            raise ValueError("invalid slash command quoting") from error
        if not parts:
            raise ValueError("slash command must not be empty")
        name, *arguments = parts
        if name in cls._NO_ARGUMENTS:
            if arguments:
                raise ValueError(f"/{name} accepts no arguments")
            return ParsedCommand(name)
        if name == "permissions":
            if len(arguments) > 1 or (
                arguments and arguments[0] not in cls._PERMISSION_MODES
            ):
                raise ValueError("/permissions expects strict, balanced, or autonomous")
            return ParsedCommand(name, tuple(arguments))
        if name == "resume":
            if not arguments:
                return ParsedCommand(name, ("latest",))
            if len(arguments) != 1:
                raise ValueError("/resume expects latest or one session UUID")
            if arguments[0] != "latest":
                try:
                    UUID(arguments[0])
                except ValueError as error:
                    raise ValueError("/resume expects latest or a session UUID") from error
            return ParsedCommand(name, tuple(arguments))
        raise ValueError(f"unknown slash command: /{name}")
