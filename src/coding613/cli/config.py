"""Configuration inspection command."""

from __future__ import annotations

from pathlib import Path

import typer

from coding613.config import load_config

app = typer.Typer(no_args_is_help=True)
_REPO_OPTION = typer.Option(
    Path("."), "--repo", "--repo-root", exists=True, file_okay=False, dir_okay=True
)


@app.command("check")
def check(
    repo_root: Path = _REPO_OPTION,
) -> None:
    """Validate and summarize a repository's harness.toml."""

    try:
        config = load_config(repo_root)
    except (OSError, ValueError) as error:
        typer.echo(f"invalid configuration: {error}", err=True)
        raise typer.Exit(code=1) from error
    limits = config.budgets
    typer.echo(f"configuration valid: {config.repository_root}")
    typer.echo(f"mode={config.permission_mode.value}")
    typer.echo(
        "budgets="
        f"per_agent_turns:{limits.per_agent_turns},"
        f"total_model_calls:{limits.total_model_calls},"
        f"wall_time_seconds:{limits.wall_time_seconds},"
        f"provider_cost:{limits.provider_cost}"
    )
