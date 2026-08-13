"""Installed console entrypoint."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import click

from .main import app
from .prompt import parse_root_args, run_print
from .tui import TuiLaunchRequest, launch_tui

_MANAGEMENT_COMMANDS = frozenset(
    {"credentials", "providers", "config", "run", "runs", "demo"}
)
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
_ROOT_FLAG_OPTIONS = frozenset(
    {
        "-p",
        "--print",
        "--continue",
        "--dangerously-skip-permissions",
        "--verbose",
    }
)
_ROOT_WORKFLOW_VALUE_OPTIONS = _ROOT_VALUE_OPTIONS - {"--repo"}


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


def _selects_root_workflow(argv: Sequence[str]) -> bool:
    """Return whether a root-only selector appears before the first command."""

    skip_value = False
    for value in argv:
        if skip_value:
            skip_value = False
            continue
        if value == "--":
            return True
        if value in _ROOT_VALUE_OPTIONS:
            if value in _ROOT_WORKFLOW_VALUE_OPTIONS:
                return True
            skip_value = True
            continue
        if value in _ROOT_FLAG_OPTIONS:
            return True
        if not value.startswith("-"):
            return False
    return False


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
    if (
        _first_command(values) in _MANAGEMENT_COMMANDS
        and not _selects_root_workflow(values)
    ):
        return run_management(values)
    request = parse_root_args(values)
    if request.print_mode:
        return run_print(request)
    launch_tui(
        TuiLaunchRequest(
            repo=request.repo,
            initial_task=request.prompt,
            resume=request.resume or ("latest" if request.continue_latest else None),
            continue_latest=request.continue_latest,
            permission_mode=request.permission_mode,
            options=request.options,
        )
    )
    return 0


def main() -> None:
    raise SystemExit(dispatch(sys.argv[1:]))


__all__ = ["TuiLaunchRequest", "dispatch", "launch_tui", "main", "run_management"]
