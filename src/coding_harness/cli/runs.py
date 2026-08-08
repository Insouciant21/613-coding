"""Typer commands for run lifecycle operations."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import typer

from coding_harness.adapters.sandbox.fake import FakeSandboxRuntime
from coding_harness.application.run_service import RunRequest
from coding_harness.demo.core_feedback import run_core_feedback_demo
from coding_harness.demo.multi_agent import run_multi_agent_demo
from coding_harness.demo.sandbox import run_sandbox_demo

run_app = typer.Typer(no_args_is_help=True)
runs_app = typer.Typer(no_args_is_help=True)
_REPO_OPTION = typer.Option(Path("."), "--repo", exists=True, file_okay=False)

_service_factory: Callable[[Path | None], Any] | None = None


def configure_run_service(factory: Callable[[Path | None], Any]) -> None:
    """Install the application-service factory used by CLI adapters."""

    global _service_factory
    _service_factory = factory


def get_run_service(repo_root: Path | None = None) -> Any:
    if _service_factory is None:
        from coding_harness.application.composition import build_services

        return build_services(repo_root or Path(".")).run_service
    return _service_factory(repo_root)


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(_json_value(value), sort_keys=True, default=str))
        return
    if hasattr(value, "model_dump"):
        for key, item in _json_value(value).items():
            typer.echo(f"{key}: {item}")
    elif isinstance(value, (list, tuple)):
        for item in value:
            typer.echo(str(item))
    else:
        typer.echo(str(value))


def _fail(error: Exception) -> None:
    typer.echo(f"command failed: {error}", err=True)
    raise typer.Exit(code=1) from error


@run_app.command("task")
def run_task(
    task: str,
    repo: Path = typer.Option(Path("."), "--repo", exists=True, file_okay=False),  # noqa: B008
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    try:
        run = get_run_service(repo.resolve()).create_run(RunRequest(task=task))
    except Exception as error:  # application errors are CLI failures  # noqa: BLE001
        _fail(error)
    _emit(run, as_json)


@runs_app.command("status")
def status(
    run_id: UUID,
    repo: Path = _REPO_OPTION,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    try:
        _emit(get_run_service(repo.resolve()).get_summary(run_id), as_json)
    except Exception as error:  # noqa: BLE001
        _fail(error)


@runs_app.command("events")
def events(
    run_id: UUID,
    repo: Path = _REPO_OPTION,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    try:
        service = get_run_service(repo.resolve())
        values = service.list_events(run_id)
        _emit(values, as_json)
    except Exception as error:  # noqa: BLE001
        _fail(error)


@runs_app.command("approve")
def approve(
    approval_id: UUID,
    repo: Path = _REPO_OPTION,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    try:
        _emit(get_run_service(repo.resolve()).approve(approval_id), as_json)
    except Exception as error:  # noqa: BLE001
        _fail(error)


@runs_app.command("reject")
def reject(
    approval_id: UUID,
    repo: Path = _REPO_OPTION,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    try:
        _emit(get_run_service(repo.resolve()).reject(approval_id), as_json)
    except Exception as error:  # noqa: BLE001
        _fail(error)


@runs_app.command("resume")
def resume(
    run_id: UUID,
    repo: Path = _REPO_OPTION,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    try:
        _emit(get_run_service(repo.resolve()).resume(run_id), as_json)
    except Exception as error:  # noqa: BLE001
        _fail(error)


@runs_app.command("cancel")
def cancel(
    run_id: UUID,
    repo: Path = _REPO_OPTION,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    try:
        _emit(get_run_service(repo.resolve()).cancel(run_id), as_json)
    except Exception as error:  # noqa: BLE001
        _fail(error)


def run_demo(name: str, repo: Path) -> Any:
    if name == "core":
        return run_core_feedback_demo(repo)
    if name == "sandbox":
        return run_sandbox_demo(FakeSandboxRuntime())
    if name == "multi-agent":
        return run_multi_agent_demo()
    raise ValueError(f"unknown demo: {name}")


def demo(
    name: str = typer.Argument(..., help="core, sandbox, or multi-agent"),
    repo: Path = typer.Option(Path("."), "--repo", exists=True, file_okay=False),  # noqa: B008
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    try:
        if name not in {"core", "sandbox", "multi-agent"}:
            raise ValueError("demo must be core, sandbox, or multi-agent")
        _emit(run_demo(name, repo.resolve()), as_json)
    except Exception as error:  # noqa: BLE001
        _fail(error)


def demo_command(
    name: str = typer.Argument(...),
    repo: Path = typer.Option(Path("."), "--repo", exists=True, file_okay=False),  # noqa: B008
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    try:
        _emit(run_demo(name, repo.resolve()), as_json)
    except Exception as error:  # noqa: BLE001
        _fail(error)
