"""Root Typer application."""

from __future__ import annotations

import typer

from .config import app as config_app
from .credentials import app as credentials_app
from .runs import demo_command, run_app, runs_app

app = typer.Typer(no_args_is_help=True)
app.add_typer(credentials_app, name="credentials")
app.add_typer(config_app, name="config")
app.add_typer(run_app, name="run")
app.add_typer(runs_app, name="runs")
app.command("demo")(demo_command)

__all__ = ["app"]
