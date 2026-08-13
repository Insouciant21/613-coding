from __future__ import annotations

from uuid import uuid4

import pytest

from coding613.tui.commands import CommandCatalog, SlashCommand


@pytest.mark.parametrize(
    ("text", "name", "arguments"),
    [
        ("/help", "help", ()),
        ("/model", "model", ()),
        ("/config", "config", ()),
        ("/config show", "config", ("show",)),
        ("/config set budgets.total_model_calls 5", "config", ("set", "budgets.total_model_calls", "5")),
        ("/provider", "provider", ()),
        ("/provider list", "provider", ("list",)),
        ("/provider use ai2", "provider", ("use", "ai2")),
        ("/provider add", "provider", ("add",)),
        ("/provider edit ai2", "provider", ("edit", "ai2")),
        ("/provider remove ai2", "provider", ("remove", "ai2")),
        ("/provider delete ai2", "provider", ("delete", "ai2")),
        ("/provider key ai2", "provider", ("key", "ai2")),
        ("/provider clear-key ai2", "provider", ("clear-key", "ai2")),
        ("/permissions", "permissions", ()),
        ("/permissions strict", "permissions", ("strict",)),
        ("/permissions bypass", "permissions", ("bypass",)),
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
    [
        "help",
        "/unknown",
        "/help extra",
        "/config invalid",
        "/config set budgets.total_model_calls",
        "/provider use",
        "/provider edit",
        "/provider add extra",
        "/permissions unsafe",
        "/resume nope",
        "/quit now",
    ],
)
def test_slash_command_rejects_invalid_input(text: str) -> None:
    with pytest.raises(ValueError):
        SlashCommand.parse(text)


def test_catalog_lists_and_parses_all_commands() -> None:
    catalog = CommandCatalog.default()
    assert {
        "help",
        "clear",
        "compact",
        "context",
        "config",
        "cost",
        "doctor",
        "model",
        "provider",
        "permissions",
        "resume",
        "runs",
        "status",
        "quit",
    } <= set(catalog.names())
    assert catalog.parse("/resume latest").arguments == ("latest",)
    with pytest.raises(ValueError, match="unknown slash command"):
        catalog.parse("/not-a-command")


def test_catalog_completes_only_top_level_slash_prefixes() -> None:
    catalog = CommandCatalog.default()

    assert catalog.complete("/co") == (
        "/config",
        "/compact",
        "/context",
        "/cost",
    )
    assert catalog.complete("/") == tuple(f"/{name}" for name in catalog.names())
    assert catalog.complete("/config ") == ()
    assert catalog.complete("repair") == ()


def test_help_explains_command_discovery_and_literal_slash_escape() -> None:
    help_text = CommandCatalog.default().help()

    assert "Tab" in help_text
    assert "//" in help_text
