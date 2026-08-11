"""Manage user-wide LLM provider profiles without exposing API keys."""

from __future__ import annotations

from typing import Literal, cast

import typer

from coding613.application.credentials import CredentialError
from coding613.application.user_configuration import UserConfigurationService
from coding613.config import MAX_OUTPUT_TOKENS, LLMConfig, ModelConfig

app = typer.Typer(no_args_is_help=True)
models_app = typer.Typer(no_args_is_help=True)
app.add_typer(models_app, name="models")


def get_user_configuration_service() -> UserConfigurationService:
    return UserConfigurationService()


@app.command("list")
def list_providers() -> None:
    """List user provider profiles and the active selection."""

    service = get_user_configuration_service()
    profiles = service.profiles()
    if not profiles:
        typer.echo("No provider profiles configured")
        return
    for profile in profiles:
        marker = "*" if profile.active else " "
        key = profile.credential.source if profile.credential.configured else "missing"
        selected = profile.selected
        model_count = len(profile.config.models)
        typer.echo(
            f"{marker} {profile.name} | api={selected.api} | model={selected.model} "
            f"| models={model_count or 'legacy'} | base_url={selected.base_url} | key={key}"
        )


@app.command("show")
def show_provider(name: str) -> None:
    """Show one provider profile without its API key."""

    service = get_user_configuration_service()
    profile = next((item for item in service.profiles() if item.name == name), None)
    if profile is None:
        typer.echo(f"provider is not configured: {name}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        f"name={profile.name}\n"
        f"active={profile.active}\n"
        f"provider={profile.config.provider}\n"
        f"api={profile.selected.api}\n"
        f"base_url={profile.selected.base_url}\n"
        f"model={profile.selected.model}\n"
        f"active_model={profile.config.active_model or 'legacy'}\n"
        f"credential={profile.config.credential}\n"
        f"timeout_seconds={profile.config.timeout_seconds}\n"
        f"max_output_tokens={profile.selected.max_output_tokens}\n"
        f"context_window_chars={profile.selected.context_window_chars}\n"
        f"streaming={profile.selected.streaming}\n"
        f"reasoning_effort={profile.selected.reasoning_effort}\n"
        f"models={', '.join(sorted(profile.config.models)) or 'legacy'}\n"
        f"key_source={profile.credential.source if profile.credential.configured else 'missing'}"
    )


@app.command("use")
def use_provider(name: str) -> None:
    """Select the active provider profile for future runs."""

    try:
        get_user_configuration_service().select_provider(name)
    except (ValueError, CredentialError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"active provider: {name}")


@app.command("add")
def add_provider(
    name: str,
    base_url: str = typer.Option(..., help="OpenAI-compatible API base URL"),
    model: str = typer.Option(..., help="Model identifier"),
    provider_kind: str = typer.Option(
        "openai-compatible", "--provider", help="Provider kind/adapter label"
    ),
    api: Literal["chat_completions", "responses", "anthropic", "messages"] = typer.Option(
        "responses", help="API surface"
    ),
    credential: str | None = typer.Option(None, help="Keyring reference; defaults to NAME"),
    timeout_seconds: float = typer.Option(120.0, min=0.001),
    max_output_tokens: int = typer.Option(MAX_OUTPUT_TOKENS, min=1, max=MAX_OUTPUT_TOKENS),
    context_window_chars: int = typer.Option(256_000, min=1, max=4_000_000),
    streaming: bool = typer.Option(False, help="Enable provider streaming"),
    reasoning_effort: str = typer.Option("low", help="Provider-defined reasoning level"),
    make_active: bool = typer.Option(False, "--active", help="Select after saving"),
) -> None:
    """Create or replace a user provider profile; use key-set for its secret."""

    profile = LLMConfig(
        provider=provider_kind,
        base_url=base_url,
        model=model,
        credential=credential or name,
        api=api,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
        context_window_chars=context_window_chars,
        streaming=streaming,
        reasoning_effort=reasoning_effort,
    )
    try:
        get_user_configuration_service().upsert_provider(name, profile, make_active=make_active)
    except (ValueError, CredentialError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"provider saved: {name}")


@models_app.command("list")
def list_models(provider: str) -> None:
    """List model aliases and their reasoning settings for a provider."""

    service = get_user_configuration_service()
    try:
        models = service.models(provider)
    except (ValueError, CredentialError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    if not models:
        typer.echo("No selectable models configured (legacy provider model is active)")
        return
    for item in models:
        marker = "*" if item.active else " "
        config = item.config
        details = [f"reasoning={config.reasoning_effort}"]
        if config.max_output_tokens is not None:
            details.append(f"max_output_tokens={config.max_output_tokens}")
        if config.context_window_chars is not None:
            details.append(f"context_window_chars={config.context_window_chars}")
        if config.streaming is not None:
            details.append(f"streaming={config.streaming}")
        typer.echo(f"{marker} {item.alias} | model={config.model} | " + " | ".join(details))


@models_app.command("use")
def use_model(provider: str, alias: str) -> None:
    """Select a configured model alias for a provider."""

    try:
        get_user_configuration_service().select_model(provider, alias)
    except (ValueError, CredentialError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"active model for {provider}: {alias}")


@models_app.command("reasoning")
def set_model_reasoning(
    provider: str,
    alias: str,
    reasoning_effort: str = typer.Argument(..., help="Provider-defined reasoning level"),
) -> None:
    """Set a provider-defined reasoning level for one model alias."""

    try:
        get_user_configuration_service().set_model_reasoning(
            provider, alias, reasoning_effort
        )
    except (ValueError, CredentialError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"reasoning for {provider}/{alias}: {reasoning_effort}")


@models_app.command("add")
def add_model(
    provider: str,
    alias: str,
    model: str = typer.Option(..., help="Provider model identifier"),
    reasoning_effort: str = typer.Option("low", help="Provider-defined reasoning level"),
    max_output_tokens: int | None = typer.Option(None, min=1, max=MAX_OUTPUT_TOKENS),
    context_window_chars: int | None = typer.Option(None, min=1, max=4_000_000),
    streaming: bool | None = typer.Option(None, help="Override provider streaming"),
    make_active: bool = typer.Option(False, "--active", help="Select after saving"),
) -> None:
    """Create or replace a model alias within a provider profile."""

    try:
        get_user_configuration_service().upsert_model(
            provider,
            alias,
            ModelConfig(
                model=model,
                reasoning_effort=reasoning_effort,
                max_output_tokens=max_output_tokens,
                context_window_chars=context_window_chars,
                streaming=streaming,
            ),
            make_active=make_active,
        )
    except (ValueError, CredentialError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"model saved: {provider}/{alias}")


@models_app.command("remove")
def remove_model(provider: str, alias: str) -> None:
    """Remove a model alias from a provider profile."""

    try:
        get_user_configuration_service().remove_model(provider, alias)
    except (ValueError, CredentialError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"model removed: {provider}/{alias}")


@app.command("remove")
def remove_provider(name: str) -> None:
    """Remove a provider profile; keyring entries are retained until key-clear."""

    try:
        get_user_configuration_service().remove_provider(name)
    except (ValueError, CredentialError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"provider removed: {name}")


@app.command("key-set")
def set_provider_key(name: str) -> None:
    """Store a provider API key using hidden terminal input."""

    value = cast(str, typer.prompt("API key", hide_input=True, confirmation_prompt=False))
    try:
        get_user_configuration_service().set_api_key(name, value)
    except (ValueError, CredentialError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"API key configured for provider: {name}")


@app.command("key-status")
def provider_key_status(name: str) -> None:
    """Show provider key status without revealing key material."""

    service = get_user_configuration_service()
    try:
        profile = next(item for item in service.profiles() if item.name == name)
    except StopIteration as error:
        typer.echo(f"provider is not configured: {name}", err=True)
        raise typer.Exit(code=1) from error
    state = profile.credential.source if profile.credential.configured else "missing"
    typer.echo(f"{name}: {state}")


@app.command("key-clear")
def clear_provider_key(name: str) -> None:
    """Remove a provider API key from the OS keyring."""

    try:
        get_user_configuration_service().clear_api_key(name)
    except (ValueError, CredentialError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"API key cleared for provider: {name}")


__all__ = ["app", "get_user_configuration_service"]
