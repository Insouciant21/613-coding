"""User-wide provider profiles, active-provider selection, and budgets."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coding613.adapters.credentials.keyring import KeyringCredentialStore
from coding613.application.budgets import BudgetLimits
from coding613.application.credentials import CredentialError, CredentialStatus, CredentialStore
from coding613.config import (
    LLMConfig,
    ModelConfig,
    UserConfig,
    default_user_config_path,
    load_user_config,
    save_user_config,
)

_BUDGET_FIELDS = {
    "per_agent_turns",
    "total_model_calls",
    "wall_time_seconds",
    "provider_cost",
    "unattended",
}


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Safe display data for one user provider profile."""

    name: str
    config: LLMConfig
    active: bool
    credential: CredentialStatus

    @property
    def selected(self) -> LLMConfig:
        """Return the provider metadata with its active model applied."""

        return self.config.effective()


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Safe display data for one model alias inside a provider profile."""

    provider: str
    alias: str
    config: ModelConfig
    active: bool


class UserConfigurationService:
    """Manage user-wide profiles while keeping API keys in the OS keyring."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        credential_store: CredentialStore | None = None,
    ) -> None:
        if path is None:
            self.path = default_user_config_path()
        else:
            candidate = Path(path).expanduser()
            self.path = candidate / "config.toml" if candidate.is_dir() else candidate
        self._credentials = credential_store or KeyringCredentialStore()

    def load(self) -> UserConfig:
        return load_user_config(self.path)

    def profiles(self) -> tuple[ProviderProfile, ...]:
        config = self.load()
        profiles: list[ProviderProfile] = []
        for name, provider in sorted(config.providers.items()):
            profiles.append(
                ProviderProfile(
                    name=name,
                    config=provider,
                    active=name == config.active_provider,
                    credential=self._status(provider.credential),
                )
            )
        return tuple(profiles)

    def active(self) -> ProviderProfile | None:
        config = self.load()
        if config.active_provider is None:
            return None
        provider = config.providers[config.active_provider]
        return ProviderProfile(
            name=config.active_provider,
            config=provider,
            active=True,
            credential=self._status(provider.credential),
        )

    def summary(self) -> str:
        config = self.load()
        lines = [f"User configuration: {self.path}"]
        lines.append(f"active_provider={config.active_provider or 'none'}")
        budgets = config.budgets.model_dump(exclude_none=True, mode="json")
        lines.append(f"budgets={budgets or 'none'}")
        for profile in self.profiles():
            selected = profile.selected
            model_names = ", ".join(sorted(profile.config.models)) or "legacy"
            lines.append(
                f"{profile.name}: api={selected.api}, model={selected.model}, "
                f"models={model_names}, base_url={selected.base_url}, "
                f"credential={selected.credential}, "
                f"key={profile.credential.source if profile.credential.configured else 'missing'}"
            )
        return "\n".join(lines)

    def models(self, provider: str) -> tuple[ModelProfile, ...]:
        """List selectable model aliases for one provider."""

        normalized = _provider_name(provider)
        config = self._provider(normalized)
        return tuple(
            ModelProfile(
                provider=normalized,
                alias=alias,
                config=model,
                active=alias == config.active_model
                or (config.active_model is None and alias == config.model),
            )
            for alias, model in sorted(config.models.items())
        )

    def select_model(self, provider: str, alias: str) -> UserConfig:
        """Select an existing model alias for a provider."""

        normalized = _provider_name(provider)
        config = self.load()
        current = config.providers.get(normalized)
        if current is None:
            raise ValueError(f"provider is not configured: {normalized}")
        model_alias = _model_name(alias)
        if model_alias not in current.models:
            raise ValueError(f"model is not configured for {normalized}: {model_alias}")
        updated_provider = current.model_copy(update={"active_model": model_alias})
        providers = dict(config.providers)
        providers[normalized] = updated_provider
        return self._save(config.model_copy(update={"providers": providers}))

    def set_model_reasoning(
        self, provider: str, alias: str, reasoning_effort: str
    ) -> UserConfig:
        """Change the reasoning level stored for one model alias."""

        normalized = _provider_name(provider)
        model_alias = _model_name(alias)
        config = self.load()
        current = config.providers.get(normalized)
        if current is None:
            raise ValueError(f"provider is not configured: {normalized}")
        selected = current.models.get(model_alias)
        if selected is None:
            raise ValueError(f"model is not configured for {normalized}: {model_alias}")
        updated_model = ModelConfig.model_validate(
            selected.model_copy(update={"reasoning_effort": reasoning_effort}).model_dump()
        )
        models = dict(current.models)
        models[model_alias] = updated_model
        providers = dict(config.providers)
        providers[normalized] = current.model_copy(update={"models": models})
        return self._save(config.model_copy(update={"providers": providers}))

    def upsert_model(
        self,
        provider: str,
        alias: str,
        model: ModelConfig,
        *,
        make_active: bool = False,
    ) -> UserConfig:
        """Create or replace a model alias without changing credentials."""

        normalized = _provider_name(provider)
        model_alias = _model_name(alias)
        config = self.load()
        current = config.providers.get(normalized)
        if current is None:
            raise ValueError(f"provider is not configured: {normalized}")
        models = dict(current.models)
        models[model_alias] = model
        active_model = (
            model_alias
            if make_active or current.active_model is None and len(models) == 1
            else current.active_model
        )
        updated_provider = current.model_copy(
            update={"models": models, "active_model": active_model}
        )
        providers = dict(config.providers)
        providers[normalized] = updated_provider
        return self._save(config.model_copy(update={"providers": providers}))

    def remove_model(self, provider: str, alias: str) -> UserConfig:
        """Remove a model alias, selecting a deterministic replacement if needed."""

        normalized = _provider_name(provider)
        model_alias = _model_name(alias)
        config = self.load()
        current = config.providers.get(normalized)
        if current is None:
            raise ValueError(f"provider is not configured: {normalized}")
        if model_alias not in current.models:
            raise ValueError(f"model is not configured for {normalized}: {model_alias}")
        models = dict(current.models)
        del models[model_alias]
        active_model = current.active_model
        if active_model == model_alias:
            active_model = next(iter(sorted(models)), None)
        updated_provider = current.model_copy(
            update={"models": models, "active_model": active_model}
        )
        providers = dict(config.providers)
        providers[normalized] = updated_provider
        return self._save(config.model_copy(update={"providers": providers}))

    def select_provider(self, name: str) -> UserConfig:
        normalized = _provider_name(name)
        config = self.load()
        if normalized not in config.providers:
            raise ValueError(f"provider is not configured: {normalized}")
        return self._save(config.model_copy(update={"active_provider": normalized}))

    def upsert_provider(
        self,
        name: str,
        provider: LLMConfig,
        *,
        api_key: str | None = None,
        make_active: bool = False,
    ) -> UserConfig:
        normalized = _provider_name(name)
        config = self.load()
        providers = dict(config.providers)
        existing = providers.get(normalized)
        if existing is not None and not provider.models and existing.models:
            # Updating endpoint/credential metadata should not silently erase
            # the user's model catalogue; aliases have their own remove path.
            provider = provider.model_copy(
                update={"models": existing.models, "active_model": existing.active_model}
            )
        providers[normalized] = provider
        active = normalized if make_active or config.active_provider is None else config.active_provider
        updated = config.model_copy(update={"providers": providers, "active_provider": active})
        result = self._save(updated)
        if api_key is not None:
            self.set_api_key(normalized, api_key)
        return result

    def remove_provider(self, name: str) -> UserConfig:
        normalized = _provider_name(name)
        config = self.load()
        if normalized not in config.providers:
            raise ValueError(f"provider is not configured: {normalized}")
        providers = dict(config.providers)
        del providers[normalized]
        active = config.active_provider
        if active == normalized:
            active = next(iter(sorted(providers)), None)
        return self._save(config.model_copy(update={"providers": providers, "active_provider": active}))

    def set_api_key(self, name: str, value: str) -> CredentialStatus:
        normalized = _provider_name(name)
        provider = self._provider(normalized)
        if not value.strip():
            raise ValueError("API key must not be blank")
        self._credentials.set(provider.credential, value)
        return self._status(provider.credential)

    def clear_api_key(self, name: str) -> None:
        normalized = _provider_name(name)
        provider = self._provider(normalized)
        self._credentials.clear(provider.credential)

    def set_budget_value(self, name: str, value: str) -> UserConfig:
        """Update one user-wide budget from a TUI/CLI scalar value.

        The value is parsed before the TOML file is touched and then passed
        through ``BudgetLimits`` so unattended-run safety remains enforced by
        the typed configuration model.
        """

        field = name.strip().lower()
        if field not in _BUDGET_FIELDS:
            supported = ", ".join(sorted(_BUDGET_FIELDS))
            raise ValueError(f"unsupported user budget {name!r}; use one of: {supported}")
        config = self.load()
        values: dict[str, Any] = config.budgets.model_dump(mode="python")
        values[field] = _parse_budget_value(value, field)
        return self._save(
            config.model_copy(update={"budgets": BudgetLimits.model_validate(values)})
        )

    def _provider(self, name: str) -> LLMConfig:
        provider = self.load().providers.get(name)
        if provider is None:
            raise ValueError(f"provider is not configured: {name}")
        return provider

    def _status(self, credential: str) -> CredentialStatus:
        try:
            return self._credentials.status(credential)
        except (CredentialError, OSError, RuntimeError):
            # Listing profiles must remain useful on headless systems where
            # no Secret Service backend is available.  A failed lookup is
            # presented as missing; setting/clearing still reports its error.
            return CredentialStatus(provider=credential, configured=False, source="none")

    def _save(self, config: UserConfig) -> UserConfig:
        validated = UserConfig.model_validate(config.model_dump(mode="python"))
        save_user_config(validated, self.path)
        return validated


def _provider_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("provider name must not be blank")
    # UserConfig performs the authoritative character/length validation.
    UserConfig.model_validate({"providers": {normalized: LLMConfig()}})
    return normalized


def _model_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("model alias must not be blank")
    # LLMConfig validates aliases when the profile is persisted; this small
    # early check gives the TUI and CLI a useful error before touching disk.
    try:
        LLMConfig(models={normalized: ModelConfig(model="placeholder")})
    except ValueError as error:
        raise ValueError(str(error)) from error
    return normalized


def _parse_budget_value(value: str, field: str) -> Any:
    raw = value.strip().lower()
    if not raw:
        raise ValueError("budget value must not be blank")
    if field == "unattended":
        if raw in {"true", "on", "yes", "1"}:
            return True
        if raw in {"false", "off", "no", "0"}:
            return False
        raise ValueError("unattended must be true or false")
    try:
        parsed = float(raw) if field in {"wall_time_seconds", "provider_cost"} else int(raw)
    except ValueError as error:
        kind = "number" if field in {"wall_time_seconds", "provider_cost"} else "integer"
        raise ValueError(f"budget value must be an {kind}") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError("budget value must be greater than zero")
    return parsed


__all__ = ["ModelProfile", "ProviderProfile", "UserConfigurationService"]
