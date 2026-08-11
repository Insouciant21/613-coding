"""Project policy and user-wide provider configuration.

``harness.toml`` is intentionally repository-local and policy-only.  Provider
profiles and resource budgets are user concerns and live in the per-user TOML
file returned by :func:`default_user_config_path`; API keys are resolved from
the operating-system keyring by the application service.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from coding613.application.budgets import BudgetLimits
from coding613.application.policy import RepositoryPolicyConfig
from coding613.domain.models import PermissionMode
from coding613.domain.models_base import DomainModel

DEFAULT_CONTEXT_WINDOW_CHARS = 256_000
MAX_OUTPUT_TOKENS = 128_000


class ModelConfig(DomainModel):
    """A selectable model variant owned by one provider profile.

    The table key is a user-facing alias while ``model`` may be any provider
    model identifier (including identifiers containing ``/``).  Optional
    values inherit the provider defaults, which keeps old one-model profiles
    fully compatible with the new model catalogue.
    """

    model: str = Field(min_length=1, max_length=256)
    reasoning_effort: str = Field(default="low", min_length=1, max_length=64)
    max_output_tokens: int | None = Field(default=None, gt=0, le=MAX_OUTPUT_TOKENS)
    context_window_chars: int | None = Field(default=None, gt=0, le=4_000_000)
    streaming: bool | None = None

    @field_validator("model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model must not be blank")
        return normalized

    @field_validator("reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reasoning_effort must not be blank")
        return normalized


class LLMConfig(DomainModel):
    """Non-secret metadata for one lower-level provider profile."""

    provider: str = "openai-compatible"
    api: Literal["chat_completions", "responses", "anthropic", "messages"] = "chat_completions"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    active_model: str | None = None
    models: dict[str, ModelConfig] = Field(default_factory=dict)
    credential: str = "openai"
    timeout_seconds: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    max_output_tokens: int = Field(default=MAX_OUTPUT_TOKENS, gt=0, le=MAX_OUTPUT_TOKENS)
    context_window_chars: int = Field(
        default=DEFAULT_CONTEXT_WINDOW_CHARS,
        gt=0,
        le=4_000_000,
    )
    streaming: bool = False
    reasoning_effort: str = Field(default="low", min_length=1, max_length=64)

    @field_validator("model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model must not be blank")
        return normalized

    @field_validator("reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reasoning_effort must not be blank")
        return normalized

    @field_validator("active_model")
    @classmethod
    def validate_active_model_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("active_model must not be blank")
        return normalized

    @field_validator("models")
    @classmethod
    def validate_model_aliases(cls, value: dict[str, ModelConfig]) -> dict[str, ModelConfig]:
        invalid = sorted(
            alias for alias in value if _MODEL_NAME_RE.fullmatch(alias) is None
        )
        if invalid:
            raise ValueError(
                "model aliases must match [A-Za-z0-9][A-Za-z0-9_-]{0,63}: "
                + ", ".join(invalid)
            )
        return value

    @model_validator(mode="after")
    def validate_selected_model(self) -> LLMConfig:
        if self.active_model is not None and self.active_model not in self.models:
            raise ValueError(f"active model is not configured: {self.active_model}")
        return self

    def effective(self) -> LLMConfig:
        """Return this profile with its selected model overrides applied."""

        alias = self.active_model
        if alias is None and self.model in self.models:
            alias = self.model
        if alias is None and self.models:
            alias = min(self.models)
        selected = self.models.get(alias) if alias is not None else None
        if selected is None:
            return self
        updates: dict[str, Any] = {
            "model": selected.model,
            "reasoning_effort": selected.reasoning_effort,
        }
        if selected.max_output_tokens is not None:
            updates["max_output_tokens"] = selected.max_output_tokens
        if selected.context_window_chars is not None:
            updates["context_window_chars"] = selected.context_window_chars
        if selected.streaming is not None:
            updates["streaming"] = selected.streaming
        return self.model_copy(update=updates)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 128:
            raise ValueError("provider must be a non-empty name of at most 128 characters")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", normalized):
            raise ValueError("provider contains unsupported characters")
        return normalized

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an HTTP(S) URL without credentials or query data")
        return value.rstrip("/")


_PROVIDER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class UserConfig(DomainModel):
    """User-wide provider profiles and safety budgets.

    The project ``harness.toml`` deliberately does not contain these values.
    Provider API keys are referenced by ``credential`` and live in the OS
    keyring, never in this TOML document.
    """

    active_provider: str | None = None
    providers: dict[str, LLMConfig] = Field(default_factory=dict)
    budgets: BudgetLimits = Field(default_factory=BudgetLimits)

    @field_validator("providers")
    @classmethod
    def validate_provider_names(cls, value: dict[str, LLMConfig]) -> dict[str, LLMConfig]:
        invalid = sorted(name for name in value if _PROVIDER_NAME_RE.fullmatch(name) is None)
        if invalid:
            raise ValueError(
                "provider names must match [A-Za-z0-9][A-Za-z0-9_-]{0,63}: "
                + ", ".join(invalid)
            )
        return value

    @model_validator(mode="after")
    def validate_active_provider(self) -> UserConfig:
        if self.active_provider is not None and self.active_provider not in self.providers:
            raise ValueError(f"active provider is not configured: {self.active_provider}")
        return self


class HarnessConfig(DomainModel):
    """Validated project policy loaded from a repository ``harness.toml``."""

    repository_root: Path
    permission_mode: PermissionMode = PermissionMode.BALANCED
    validation_commands: tuple[tuple[str, ...], ...] = ()
    allow_network: bool = False
    allow_dependency_install: bool = False
    allow_git_writes: bool = False
    allow_writes: bool = True
    denied_tools: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("repository_root")
    @classmethod
    def canonicalize_repository_root(cls, value: Path) -> Path:
        root = value.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("repository_root must be a directory")
        return root

    @field_validator("validation_commands", mode="before")
    @classmethod
    def validate_argv_commands(cls, value: Any) -> tuple[tuple[str, ...], ...]:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise TypeError("validation commands must be argv arrays")
        commands: list[tuple[str, ...]] = []
        for command in value:
            if not isinstance(command, (list, tuple)) or not command:
                raise ValueError("validation commands must be non-empty argv arrays")
            if not all(isinstance(argument, str) and argument for argument in command):
                raise ValueError("validation command argv entries must be non-empty strings")
            commands.append(tuple(command))
        return tuple(commands)

    @field_validator("denied_tools", mode="before")
    @classmethod
    def validate_denied_tools(cls, value: Any) -> frozenset[str]:
        if value is None:
            return frozenset()
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise TypeError("denied_tools must be an array of names")
        if not all(isinstance(item, str) and item for item in value):
            raise ValueError("denied_tools entries must be non-empty strings")
        return frozenset(value)

    @property
    def mode(self) -> PermissionMode:
        """Compatibility alias for callers that refer to the run mode."""

        return self.permission_mode

    @property
    def policy(self) -> RepositoryPolicyConfig:
        """Build the application policy value without moving policy logic here."""

        return RepositoryPolicyConfig(
            repository_root=self.repository_root,
            validation_commands=self.validation_commands,
            allow_network=self.allow_network,
            allow_dependency_install=self.allow_dependency_install,
            allow_git_writes=self.allow_git_writes,
            allow_writes=self.allow_writes,
            denied_tools=self.denied_tools,
        )


def _section(raw: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        section = raw.get(name)
        if section is not None:
            if not isinstance(section, dict):
                raise ValueError(f"{name} configuration must be a table")
            return dict(section)
    return {}


def _root_path(repo_root: str | Path) -> Path:
    root = Path(repo_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repository root must be a directory")
    return root


def load_config(repo_root: str | Path) -> HarnessConfig:
    """Load ``harness.toml`` beneath *repo_root*, or return safe defaults."""

    root = _root_path(repo_root)
    config_path = root / "harness.toml"
    raw = _read_config(config_path)
    return _build_config(root, raw)


def default_user_config_path() -> Path:
    """Return the per-user configuration path without creating it."""

    explicit = os.environ.get("CODING613_CONFIG_FILE")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "613-coding" / "config.toml"


def load_user_config(path: str | Path | None = None) -> UserConfig:
    """Load user-wide provider profiles and budgets, or safe defaults."""

    config_path = _normalize_user_config_path(path)
    if not config_path.exists():
        return UserConfig()
    with config_path.open("rb") as stream:
        loaded = tomllib.load(stream)
    if not isinstance(loaded, dict):
        raise TypeError("user configuration must contain a TOML table")
    unknown = set(loaded) - {"active_provider", "providers", "budgets"}
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"unknown user configuration key(s): {names}")
    return UserConfig.model_validate(loaded)


def save_user_config(config: UserConfig, path: str | Path | None = None) -> Path:
    """Atomically persist user configuration without writing any API key."""

    config = UserConfig.model_validate(config.model_dump(mode="python"))
    config_path = _normalize_user_config_path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_name(f".{config_path.name}.tmp")
    temporary.write_text(_dump_user_config(config), encoding="utf-8")
    os.replace(temporary, config_path)
    if os.name != "nt":
        os.chmod(config_path, 0o600)
    return config_path


def _normalize_user_config_path(path: str | Path | None) -> Path:
    candidate = Path(path).expanduser() if path is not None else default_user_config_path()
    if candidate.exists() and candidate.is_dir():
        candidate = candidate / "config.toml"
    return candidate


def _dump_user_config(config: UserConfig) -> str:
    lines: list[str] = []
    if config.active_provider is not None:
        lines.append(f"active_provider = {_toml_string(config.active_provider)}")
    budget_values = config.budgets.model_dump(exclude_none=True, mode="python")
    if budget_values:
        lines.extend(("", "[budgets]"))
        for key, value in budget_values.items():
            lines.append(f"{key} = {_toml_value(value)}")
    for name, provider in sorted(config.providers.items()):
        lines.extend(("", f"[providers.{name}]"))
        provider_values = provider.model_dump(exclude_none=True, mode="python")
        models = provider_values.pop("models", {})
        for key, value in provider_values.items():
            lines.append(f"{key} = {_toml_value(value)}")
        for alias, model in sorted(models.items()):
            lines.extend(("", f"[providers.{name}.models.{alias}]"))
            for key, value in model.items():
                lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines).lstrip() + "\n"


def _toml_string(value: str) -> str:
    # JSON double-quoted strings use the same escapes needed by TOML basic strings.
    import json

    return json.dumps(value, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    raise TypeError(f"unsupported user configuration value: {type(value).__name__}")


def load_config_text(repo_root: str | Path, text: str) -> HarnessConfig:
    """Validate a TOML document as the configuration for *repo_root*.

    This is used by the TUI configuration editor before it atomically replaces
    ``harness.toml``.  It deliberately shares the exact same parser and
    validators as :func:`load_config`.
    """

    root = _root_path(repo_root)
    loaded = tomllib.loads(text)
    if not isinstance(loaded, dict):
        raise TypeError("harness.toml must contain a TOML table")
    return _build_config(root, loaded)


def _read_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    with config_path.open("rb") as stream:
        loaded = tomllib.load(stream)
    if not isinstance(loaded, dict):
        raise TypeError("harness.toml must contain a TOML table")
    return loaded


def _build_config(root: Path, raw: dict[str, Any]) -> HarnessConfig:

    policy = _section(raw, "policy")
    run = _section(raw, "run")
    validation = _section(raw, "validation")

    mode_value = (
        raw.get("permission_mode", raw.get("mode"))
        or run.pop("permission_mode", run.pop("mode", None))
        or policy.pop("permission_mode", policy.pop("mode", None))
        or PermissionMode.BALANCED.value
    )
    commands = (
        raw.get("validation_commands")
        or validation.get("commands")
        or policy.pop("validation_commands", ())
    )
    allowed = {
        "permission_mode",
        "mode",
        "validation_commands",
        "allow_network",
        "allow_dependency_install",
        "allow_git_writes",
        "allow_writes",
        "denied_tools",
    }
    moved = set(raw) & {"budgets", "budget", "llm"}
    if moved:
        names = ", ".join(sorted(moved))
        raise ValueError(
            f"{names} configuration belongs in the user config "
            f"({default_user_config_path()}) rather than project harness.toml"
        )
    unknown = set(raw) - {"policy", "run", "validation", *allowed}
    unknown |= set(run) - allowed
    unknown |= set(policy) - allowed
    unknown |= set(validation) - {"commands"}
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"unknown configuration key(s): {names}")

    policy_values = {key: value for key, value in {**policy, **run}.items() if key in allowed}
    policy_values.pop("permission_mode", None)
    policy_values.pop("mode", None)
    policy_values["validation_commands"] = commands
    try:
        permission_mode = PermissionMode(mode_value)
    except ValueError as error:
        allowed_modes = ", ".join(item.value for item in PermissionMode)
        raise ValueError(
            f"invalid permission mode {mode_value!r}; use one of: {allowed_modes}"
        ) from error
    config = HarnessConfig(
        repository_root=root,
        permission_mode=permission_mode,
        **policy_values,
    )
    validate_config(config)
    return config


def validate_config(config: HarnessConfig) -> None:
    """Validate values that may have been assembled without Pydantic checks."""

    try:
        root = config.repository_root.expanduser().resolve(strict=True)
    except OSError as error:
        raise ValueError("repository_root must be an existing canonical directory") from error
    if not root.is_dir() or root != config.repository_root:
        raise ValueError("repository_root must be an existing canonical directory")
    HarnessConfig.model_validate(config)
