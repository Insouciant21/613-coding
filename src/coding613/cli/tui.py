"""TUI launch argument parsing and composition."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from coding613.application.composition import LocalServices, build_services
from coding613.tui.app import CodingApp


@dataclass(frozen=True, slots=True)
class TuiLaunchRequest:
    repo: Path
    initial_task: str | None
    resume: str | None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="613-coding",
        description="Open the local 613 Coding terminal interface.",
    )
    parser.add_argument("--repo", default=".", help="Repository directory")
    parser.add_argument("--resume", help="Resume latest or a session UUID")
    parser.add_argument("task", nargs="*", help="Initial coding task")
    return parser


def parse_tui_args(argv: Sequence[str]) -> TuiLaunchRequest:
    values = list(argv)
    if values[:1] == ["--"]:
        values = values[1:]
    namespace = _parser().parse_args(values)
    repo = Path(namespace.repo).expanduser()
    try:
        repo = repo.resolve(strict=True)
    except FileNotFoundError:
        _parser().error(f"repository does not exist: {repo}")
    if not repo.is_dir():
        _parser().error(f"repository is not a directory: {repo}")
    task = " ".join(namespace.task).strip() or None
    return TuiLaunchRequest(repo=repo, initial_task=task, resume=namespace.resume)


def launch_tui(
    request: TuiLaunchRequest,
    services_factory: Callable[[str | Path], LocalServices] = build_services,
) -> None:
    services = services_factory(request.repo)
    CodingApp(
        services=services,
        initial_task=request.initial_task,
        resume=request.resume,
        permission_mode=services.permission_mode,
    ).run()
