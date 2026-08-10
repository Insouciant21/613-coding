"""Installed console entrypoint."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import click

from coding613.domain.models import PermissionMode

from .main import app
from .prompt import parse_root_args, run_print
from .tui import TuiLaunchRequest, launch_tui

_MANAGEMENT_COMMANDS = frozenset({"credentials", "config", "run", "runs", "demo"})
_ROOT_VALUE_OPTIONS = frozenset(
    {
        "--repo",
        "--resume",
        "--add-dir",
        "--input-format",
        "--output-format",
        "--model",
        "--permission-mode",
        "--allowed-tools",
        "--allowedTools",
        "--disallowed-tools",
        "--disallowedTools",
        "--max-turns",
        "--max-model-calls",
        "--max-wall-time",
        "--max-cost",
        "--system-prompt",
        "--append-system-prompt",
    }
)


def _first_command(argv: Sequence[str]) -> str | None:
    skip_value = False
    for value in argv:
        if skip_value:
            skip_value = False
            continue
        if value == "--":
            return None
        if value in _ROOT_VALUE_OPTIONS:
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
            parse_root_args(values)
        except SystemExit as error:
            return int(error.code or 0)
    if _first_command(values) in _MANAGEMENT_COMMANDS:
        return run_management(values)
    request = parse_root_args(values)
    if request.print_mode:
        return run_print(request)
    launch_tui(
        TuiLaunchRequest(
            repo=request.repo,
            initial_task=request.prompt,
            resume=request.resume,
            permission_mode=request.permission_mode or PermissionMode.BALANCED,
            options=request.options,
        )
    )
    return 0


def main() -> None:
    raise SystemExit(dispatch(sys.argv[1:]))


__all__ = ["TuiLaunchRequest", "dispatch", "launch_tui", "main", "run_management"]
