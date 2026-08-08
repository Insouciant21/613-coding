"""Repository configuration loaded from ``harness.toml``.

Configuration is deliberately small and strict.  The loader owns TOML and
path handling; policy and budget decisions remain in their application
services.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from coding_harness.application.budgets import BudgetLimits
from coding_harness.application.policy import RepositoryPolicyConfig
from coding_harness.domain.models import PermissionMode
from coding_harness.domain.models_base import DomainModel


class LLMConfig(DomainModel):
    """Non-secret metadata for one lower-level OpenAI-compatible provider."""

    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    credential: str = "openai"
    timeout_seconds: float = Field(default=60.0, gt=0, allow_inf_nan=False)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if value != "openai-compatible":
            raise ValueError("provider must be openai-compatible")
        return value

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


class HarnessConfig(DomainModel):
    """Validated configuration for one repository."""

    repository_root: Path
    permission_mode: PermissionMode = PermissionMode.BALANCED
    validation_commands: tuple[tuple[str, ...], ...] = ()
    allow_network: bool = False
    allow_dependency_install: bool = False
    allow_git_writes: bool = False
    allow_writes: bool = True
    denied_tools: frozenset[str] = Field(default_factory=frozenset)
    budgets: BudgetLimits = Field(default_factory=BudgetLimits)
    llm: LLMConfig | None = None

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
    raw: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("rb") as stream:
            loaded = tomllib.load(stream)
        if not isinstance(loaded, dict):
            raise ValueError("harness.toml must contain a TOML table")
        raw = loaded

    policy = _section(raw, "policy")
    run = _section(raw, "run")
    budgets = _section(raw, "budgets", "budget")
    validation = _section(raw, "validation")
    llm = _section(raw, "llm")

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
    unknown = (set(raw) - {"policy", "run", "budgets", "budget", "validation", "llm", *allowed})
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
    config = HarnessConfig(
        repository_root=root,
        permission_mode=PermissionMode(mode_value),
        **policy_values,
        budgets=BudgetLimits.model_validate(budgets),
        llm=LLMConfig.model_validate(llm) if "llm" in raw else None,
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
    if config.budgets.unattended and (
        config.budgets.total_model_calls is None and config.budgets.provider_cost is None
    ):
        raise ValueError("unattended runs require a model-call or provider-cost budget")
