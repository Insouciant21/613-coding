from __future__ import annotations

from uuid import uuid4

import pytest

from coding613.tui.commands import SlashCommand


@pytest.mark.parametrize(
    ("text", "name", "arguments"),
    [
        ("/help", "help", ()),
        ("/model", "model", ()),
        ("/permissions", "permissions", ()),
        ("/permissions strict", "permissions", ("strict",)),
        ("/resume", "resume", ("latest",)),
        ("/resume latest", "resume", ("latest",)),
        (f"/resume {uuid4()}", "resume", None),
        ("/runs", "runs", ()),
        ("/clear", "clear", ()),
        ("/quit", "quit", ()),
    ],
)
def test_slash_command_parses_supported_commands(text, name, arguments) -> None:
    parsed = SlashCommand.parse(text)
    assert parsed.name == name
    if arguments is not None:
        assert parsed.arguments == arguments
    else:
        assert len(parsed.arguments) == 1


@pytest.mark.parametrize(
    "text",
    ["help", "/unknown", "/help extra", "/permissions unsafe", "/resume nope", "/quit now"],
)
def test_slash_command_rejects_invalid_input(text: str) -> None:
    with pytest.raises(ValueError):
        SlashCommand.parse(text)
