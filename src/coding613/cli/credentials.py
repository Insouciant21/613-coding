"""Credential commands backed by the application credential service."""

from __future__ import annotations

from typing import cast

import typer

from coding613.adapters.credentials.keyring import KeyringCredentialStore
from coding613.application.credentials import CredentialError, CredentialService

app = typer.Typer(no_args_is_help=True)


def get_credential_service() -> CredentialService:
    """Create the default OS-keyring-backed service.

    Kept as a factory so callers and tests can inject a credential boundary.
    """

    return CredentialService(KeyringCredentialStore())


def _hidden_value(action: str) -> str:
    return cast(
        str,
        typer.prompt(f"Credential to {action}", hide_input=True, confirmation_prompt=False),
    )


def _run(action: str, provider: str, value: str | None = None) -> None:
    service = get_credential_service()
    try:
        if action == "set":
            service.set(provider, value if value is not None else _hidden_value("set"))
        elif action == "update":
            service.update(provider, value if value is not None else _hidden_value("update"))
        elif action == "clear":
            service.clear(provider)
        else:  # pragma: no cover - guarded by command declarations
            raise RuntimeError(f"unsupported credential action: {action}")
    except CredentialError as error:
        typer.echo(f"credential {action} failed: {error}", err=True)
        raise typer.Exit(code=1) from error


@app.command("set")
def set_credential(provider: str) -> None:
    """Store a provider credential using hidden terminal input."""

    _run("set", provider)
    typer.echo(f"credential configured for {provider.strip()}")


@app.command("update")
def update_credential(provider: str) -> None:
    """Replace a provider credential using hidden terminal input."""

    _run("update", provider)
    typer.echo(f"credential updated for {provider.strip()}")


@app.command("status")
def status(provider: str) -> None:
    """Show whether a provider is configured without resolving its secret."""

    try:
        result = get_credential_service().status(provider)
    except CredentialError as error:
        typer.echo(f"credential status failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    state = "configured" if result.configured else "not configured"
    typer.echo(f"{result.provider}: {state} (source={result.source})")


@app.command("clear")
def clear(provider: str) -> None:
    """Remove a provider credential from the keyring."""

    _run("clear", provider)
    typer.echo(f"credential cleared for {provider.strip()}")
