from __future__ import annotations

from pathlib import Path

import pytest

from coding613.cli import entrypoint
from coding613.cli.tui import TuiLaunchRequest, parse_tui_args
from coding613.domain.models import PermissionMode


@pytest.mark.parametrize(
    ("argv", "expected_task"),
    [([], None), (["repair", "tests"], "repair tests"), (["--", "runs"], "runs")],
)
def test_root_invocations_launch_tui(monkeypatch, argv, expected_task) -> None:
    launched: list[TuiLaunchRequest] = []
    monkeypatch.setattr(entrypoint, "launch_tui", launched.append)
    assert entrypoint.dispatch(argv) == 0
    assert launched[0].initial_task == expected_task


def test_dispatch_leaves_permission_mode_unspecified_for_repository_config(
    monkeypatch, tmp_path: Path
) -> None:
    launched: list[TuiLaunchRequest] = []
    monkeypatch.setattr(entrypoint, "launch_tui", launched.append)

    assert entrypoint.dispatch(["--repo", str(tmp_path)]) == 0

    assert launched[0].permission_mode is None


def test_dispatch_forwards_dangerous_alias_to_tui(monkeypatch, tmp_path: Path) -> None:
    launched: list[TuiLaunchRequest] = []
    monkeypatch.setattr(entrypoint, "launch_tui", launched.append)

    assert (
        entrypoint.dispatch(
            ["--repo", str(tmp_path), "--dangerously-skip-permissions", "inspect"]
        )
        == 0
    )

    assert launched[0].permission_mode is PermissionMode.BYPASS


@pytest.mark.parametrize(
    "selector",
    [
        ("--permission-mode", "bypass"),
        ("--dangerously-skip-permissions",),
    ],
)
def test_explicit_root_bypass_selector_wins_over_reserved_prompt_word(
    monkeypatch, tmp_path: Path, selector: tuple[str, ...]
) -> None:
    requests = []
    delegated: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        entrypoint, "run_print", lambda request: requests.append(request) or 0
    )
    monkeypatch.setattr(
        entrypoint,
        "run_management",
        lambda argv: delegated.append(tuple(argv)) or 0,
    )

    assert (
        entrypoint.dispatch(
            ["-p", "--repo", str(tmp_path), *selector, "run", "checks"]
        )
        == 0
    )

    assert delegated == []
    assert requests[0].prompt == "run checks"
    assert requests[0].permission_mode is PermissionMode.BYPASS


@pytest.mark.parametrize(
    "command", ["credentials", "providers", "config", "run", "runs", "demo"]
)
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
    with pytest.raises(SystemExit):
        parse_tui_args(["--repo", str(tmp_path), "--resume", "not-a-session"])


def test_root_help_does_not_launch_tui(monkeypatch, capsys) -> None:
    launched: list[TuiLaunchRequest] = []
    monkeypatch.setattr(entrypoint, "launch_tui", launched.append)
    assert entrypoint.dispatch(["--help"]) == 0
    assert not launched
    assert "613-coding" in capsys.readouterr().out


def test_print_dispatch_does_not_launch_tui(monkeypatch, tmp_path: Path) -> None:
    launched: list[TuiLaunchRequest] = []
    requests = []
    monkeypatch.setattr(entrypoint, "launch_tui", launched.append)
    monkeypatch.setattr(entrypoint, "run_print", lambda request: requests.append(request) or 0)

    assert entrypoint.dispatch(["-p", "--repo", str(tmp_path), "inspect"]) == 0
    assert not launched
    assert requests[0].print_mode is True


def test_continue_dispatch_resumes_latest_tui_session(monkeypatch, tmp_path: Path) -> None:
    launched: list[TuiLaunchRequest] = []
    monkeypatch.setattr(entrypoint, "launch_tui", launched.append)

    assert entrypoint.dispatch(["--continue", "--repo", str(tmp_path)]) == 0

    assert launched[0].resume == "latest"
    assert launched[0].continue_latest is True
