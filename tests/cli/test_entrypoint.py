from __future__ import annotations

from pathlib import Path

import pytest

from coding613.cli import entrypoint
from coding613.cli.tui import TuiLaunchRequest, parse_tui_args


@pytest.mark.parametrize(
    ("argv", "expected_task"),
    [([], None), (["repair", "tests"], "repair tests"), (["--", "runs"], "runs")],
)
def test_root_invocations_launch_tui(monkeypatch, argv, expected_task) -> None:
    launched: list[TuiLaunchRequest] = []
    monkeypatch.setattr(entrypoint, "launch_tui", launched.append)
    assert entrypoint.dispatch(argv) == 0
    assert launched[0].initial_task == expected_task


@pytest.mark.parametrize("command", ["credentials", "config", "run", "runs", "demo"])
def test_reserved_management_commands_use_typer(monkeypatch, command) -> None:
    delegated: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        entrypoint,
        "run_management",
        lambda argv: delegated.append(tuple(argv)) or 0,
    )
    assert entrypoint.dispatch([command, "--help"]) == 0
    assert delegated == [(command, "--help")]


def test_parse_tui_args_resolves_repo_resume_and_task(tmp_path: Path) -> None:
    request = parse_tui_args(
        ["--repo", str(tmp_path), "--resume", "latest", "repair", "tests"]
    )
    assert request == TuiLaunchRequest(
        repo=tmp_path.resolve(), initial_task="repair tests", resume="latest"
    )


def test_parse_tui_args_rejects_unknown_option_and_missing_repo(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse_tui_args(["--unknown"])
    with pytest.raises(SystemExit):
        parse_tui_args(["--repo", str(tmp_path / "missing")])


def test_root_help_does_not_launch_tui(monkeypatch, capsys) -> None:
    launched: list[TuiLaunchRequest] = []
    monkeypatch.setattr(entrypoint, "launch_tui", launched.append)
    assert entrypoint.dispatch(["--help"]) == 0
    assert not launched
    assert "613-coding" in capsys.readouterr().out
