"""Typer adapters for local harness commands."""

import typer

from .config import app as config_app
from .credentials import app as credentials_app

app = typer.Typer()
app.add_typer(credentials_app, name="credentials")
app.add_typer(config_app, name="config")

__all__ = ["app", "config_app", "credentials_app"]

