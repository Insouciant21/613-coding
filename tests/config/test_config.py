from __future__ import annotations

from pathlib import Path

import pytest

from coding_harness.config import HarnessConfig, load_config, validate_config
from coding_harness.domain.models import PermissionMode


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


def test_validate_config_rejects_nonexistent_repository() -> None:
    config = HarnessConfig.model_construct(repository_root=Path("/does/not/exist"))

    with pytest.raises(ValueError, match="repository"):
        validate_config(config)
