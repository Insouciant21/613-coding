"""Strict, shared slash-command catalog for the local TUI."""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    name: str
    arguments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    usage: str
    description: str
    argument_parser: Callable[[tuple[str, ...]], tuple[str, ...]]


def _no_arguments(arguments: tuple[str, ...]) -> tuple[str, ...]:
    if arguments:
        raise ValueError("command accepts no arguments")
    return ()


def _model_arguments(arguments: tuple[str, ...]) -> tuple[str, ...]:
    if len(arguments) > 1:
        raise ValueError("/model expects zero or one argument")
    return arguments


def _help_arguments(arguments: tuple[str, ...]) -> tuple[str, ...]:
    if len(arguments) > 1:
        raise ValueError("/help expects zero or one argument")
    if arguments and arguments[0] not in CommandCatalog.default().names():
        raise ValueError(f"unknown command: /{arguments[0]}")
    return arguments


def _permission_arguments(arguments: tuple[str, ...]) -> tuple[str, ...]:
    if not arguments:
        return ()
    if arguments[0] in {"strict", "balanced", "autonomous", "list"}:
        if len(arguments) != 1:
            raise ValueError("/permissions mode/list accepts no extra arguments")
        return arguments
    if arguments[0] in {"allow", "deny", "clear"}:
        if len(arguments) != 2 or not arguments[1]:
            raise ValueError("/permissions allow, deny, and clear expect a tool name")
        return arguments
    raise ValueError("/permissions expects a mode, list, allow, deny, or clear")


def _resume_arguments(arguments: tuple[str, ...]) -> tuple[str, ...]:
    if not arguments:
        return ("latest",)
    if len(arguments) != 1:
        raise ValueError("/resume expects latest or one session UUID")
    if arguments[0] != "latest":
        try:
            UUID(arguments[0])
        except ValueError:
            raise ValueError("/resume expects latest or a session UUID") from None
    return arguments


class CommandCatalog:
    def __init__(self, specs: Mapping[str, CommandSpec]) -> None:
        self._specs = dict(specs)

    @classmethod
    def default(cls) -> CommandCatalog:
        no_arg_commands = {
            "clear": ("/clear", "Start a fresh session view"),
            "compact": ("/compact", "Compact prior context"),
            "context": ("/context", "Show context accounting"),
            "cost": ("/cost", "Show resource usage"),
            "doctor": ("/doctor", "Run local diagnostics"),
            "runs": ("/runs", "List recent runs"),
            "status": ("/status", "Show active run status"),
            "quit": ("/quit", "Pause safely and exit"),
        }
        specs = {
            "help": CommandSpec("help", "/help [COMMAND]", "Show command help", _help_arguments),
            "model": CommandSpec("model", "/model [NAME]", "Show or choose a model", _model_arguments),
            "permissions": CommandSpec(
                "permissions",
                "/permissions [MODE|list|allow|deny|clear]",
                "Show or change permission rules",
                _permission_arguments,
            ),
            "resume": CommandSpec("resume", "/resume [ID|latest]", "Resume a session", _resume_arguments),
        }
        specs.update(
            {
                name: CommandSpec(name, usage, description, _no_arguments)
                for name, (usage, description) in no_arg_commands.items()
            }
        )
        return cls(specs)

    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def parse(self, text: str) -> ParsedCommand:
        if not text.startswith("/"):
            raise ValueError("slash command must start with /")
        try:
            parts = shlex.split(text[1:])
        except ValueError as error:
            raise ValueError("invalid slash command quoting") from error
        if not parts:
            raise ValueError("slash command must not be empty")
        name, *arguments = parts
        spec = self._specs.get(name)
        if spec is None:
            raise ValueError(f"unknown slash command: /{name}")
        try:
            validated = spec.argument_parser(tuple(arguments))
        except ValueError as error:
            message = str(error)
            if message.startswith("command accepts"):
                message = f"/{name} accepts no arguments"
            raise ValueError(message) from error
        return ParsedCommand(name, validated)

    def help(self, name: str | None = None) -> str:
        if name is not None:
            spec = self._specs.get(name)
            if spec is None:
                raise ValueError(f"unknown slash command: /{name}")
            return f"{spec.usage} — {spec.description}"
        return "\n".join(
            f"{spec.usage} — {spec.description}" for spec in self._specs.values()
        )


class SlashCommand:
    """Compatibility facade for callers that used the original parser."""

    @classmethod
    def parse(cls, text: str) -> ParsedCommand:
        return CommandCatalog.default().parse(text)
