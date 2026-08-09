from __future__ import annotations

from pathlib import Path

import pytest

from coding613.config import HarnessConfig, load_config, validate_config
from coding613.domain.models import PermissionMode


def test_load_config_parses_toml_and_canonicalizes_repository_root(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        """
[policy]
mode = "strict"
validation_commands = [["pytest", "-q"], ["ruff", "check", "."]]
allow_network = true

[budgets]
per_agent_turns = 4
total_model_calls = 12
wall_time_seconds = 90.0
provider_cost = 1.25
unattended = true
""",
        encoding="utf-8",
    )

    config = load_config(tmp_path / ".")

    assert config.repository_root == tmp_path.resolve()
    assert config.permission_mode is PermissionMode.STRICT
    assert config.validation_commands == (("pytest", "-q"), ("ruff", "check", "."))
    assert config.allow_network is True
    assert config.budgets.total_model_calls == 12
    assert config.budgets.provider_cost == 1.25


def test_default_mode_and_budgets_are_safe_for_interactive_runs(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.permission_mode is PermissionMode.BALANCED
    assert config.budgets.unattended is False
    assert config.budgets.total_model_calls is None


def test_validation_commands_must_be_nonempty_argv_arrays(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        '[policy]\nvalidation_commands = ["pytest -q"]\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="argv"):
        load_config(tmp_path)


def test_unattended_config_requires_a_finite_budget(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        "[budgets]\nunattended = true\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="model-call|provider-cost"):
        load_config(tmp_path)


def test_load_config_parses_openai_compatible_provider_metadata(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        """
[llm]
provider = "openai-compatible"
base_url = "https://api.example.test/v1"
model = "coding-model"
credential = "openai"
timeout_seconds = 45.0
""",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.llm is not None
    assert config.llm.provider == "openai-compatible"
    assert config.llm.base_url == "https://api.example.test/v1"
    assert config.llm.model == "coding-model"
    assert config.llm.credential == "openai"
    assert config.llm.timeout_seconds == 45.0


def test_llm_provider_url_cannot_contain_credentials(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        '[llm]\nbase_url = "https://user:secret@example.test/v1"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="base_url"):
        load_config(tmp_path)


def test_validate_config_rejects_nonexistent_repository() -> None:
    config = HarnessConfig.model_construct(repository_root=Path("/does/not/exist"))

    with pytest.raises(ValueError, match="repository"):
        validate_config(config)
