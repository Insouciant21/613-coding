"""Installed console entrypoint."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import click

from .main import app
from .tui import TuiLaunchRequest, launch_tui, parse_tui_args

_MANAGEMENT_COMMANDS = frozenset({"credentials", "config", "run", "runs", "demo"})


def _first_command(argv: Sequence[str]) -> str | None:
    skip_value = False
    for value in argv:
        if skip_value:
            skip_value = False
            continue
        if value == "--":
            return None
        if value in {"--repo", "--resume"}:
            skip_value = True
            continue
        if value.startswith("-"):
            continue
        return value
    return None


def run_management(argv: Sequence[str]) -> int:
    try:
        app(args=list(argv), prog_name="613-coding", standalone_mode=False)
    except click.exceptions.Exit as error:
        return int(error.exit_code)
    return 0


def dispatch(argv: Sequence[str]) -> int:
    values = list(argv)
    if values in (["--help"], ["-h"]):
        try:
            parse_tui_args(values)
        except SystemExit as error:
            return int(error.code or 0)
    if _first_command(values) in _MANAGEMENT_COMMANDS:
        return run_management(values)
    request = parse_tui_args(values)
    launch_tui(request)
    return 0


def main() -> None:
    raise SystemExit(dispatch(sys.argv[1:]))


__all__ = ["TuiLaunchRequest", "dispatch", "launch_tui", "main", "run_management"]
