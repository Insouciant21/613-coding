"""Configuration inspection command."""

from __future__ import annotations

from pathlib import Path

import typer

from coding613.application.user_configuration import UserConfigurationService
from coding613.config import load_config
from coding613.domain.models import PermissionMode

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
        user = UserConfigurationService()
        user_config = user.load()
    except (OSError, ValueError) as error:
        typer.echo(f"invalid configuration: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"configuration valid: {config.repository_root}")
    mode_line = f"mode={config.permission_mode.value}"
    if config.permission_mode is PermissionMode.BYPASS:
        mode_line += " (DANGEROUS: BYPASS)"
    typer.echo(mode_line)
    typer.echo("scope=project-policy-only")
    typer.echo(
        "validation="
        + ("; ".join(" ".join(command) for command in config.validation_commands) or "none")
    )
    typer.echo(f"user_config={user.path}")
    typer.echo(f"active_provider={user_config.active_provider or 'none'}")
    typer.echo(f"provider_profiles={len(user_config.providers)}")
    typer.echo(
        "budgets="
        + str(user_config.budgets.model_dump(exclude_none=True, mode="json"))
    )
