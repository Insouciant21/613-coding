"""Root Typer application."""

from __future__ import annotations

from uuid import UUID

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


@app.command("web")
def web(
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Start the local operations console."""

    import uvicorn

    from coding_harness.api.app import create_app

    class UnavailableServices:
        run_service = None

        @staticmethod
        def list_events(_run_id: UUID) -> list[object]:
            return []

    uvicorn.run(create_app(UnavailableServices()), host=host, port=port)

__all__ = ["app"]
