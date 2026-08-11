from __future__ import annotations

from pathlib import Path

import pytest

from coding613.application.configuration import ConfigurationService
from coding613.config import load_config
from coding613.domain.models import PermissionMode


def test_configuration_service_updates_validated_scalar_and_preserves_other_toml(
    tmp_path: Path,
) -> None:
    original = """# keep this operator note
[policy]
mode = "balanced"
validation_commands = [["bash", "scripts", "verify.sh"]]
"""
    path = tmp_path / "harness.toml"
    path.write_text(original, encoding="utf-8")
    service = ConfigurationService(tmp_path)

    updated = service.set_value("policy.mode", "autonomous")

    assert updated.permission_mode is PermissionMode.AUTONOMOUS
    assert load_config(tmp_path).validation_commands == (("bash", "scripts", "verify.sh"),)
    persisted = path.read_text(encoding="utf-8")
    assert "# keep this operator note" in persisted
    assert 'mode = "autonomous"' in persisted


def test_configuration_service_updates_mode_and_parses_booleans(tmp_path: Path) -> None:
    service = ConfigurationService(tmp_path)

    updated = service.set_value("mode", "autonomous")
    service.set_value("policy.allow_network", "true")

    assert updated.permission_mode is PermissionMode.AUTONOMOUS
    assert load_config(tmp_path).allow_network is True


def test_configuration_service_rejects_invalid_value_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "harness.toml"
    path.write_text('[policy]\nmode = "balanced"\n', encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    service = ConfigurationService(tmp_path)

    with pytest.raises(ValueError, match="permission|invalid"):
        service.set_value("policy.mode", "extreme")

    assert path.read_text(encoding="utf-8") == before


def test_configuration_service_summary_shows_safe_metadata(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        '[policy]\nmode = "strict"\n',
        encoding="utf-8",
    )
    summary = ConfigurationService(tmp_path).summary()

    assert "mode=strict" in summary
    assert "scope=project-policy-only" in summary


def test_configuration_service_rejects_user_scoped_sections(tmp_path: Path) -> None:
    service = ConfigurationService(tmp_path)

    with pytest.raises(ValueError, match="unsupported configuration key"):
        service.set_value("llm.model", "coding-model")


def test_configuration_service_rejects_user_sections_in_project_file(tmp_path: Path) -> None:
    path = tmp_path / "harness.toml"
    path.write_text("[budgets]\ntotal_model_calls = 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="user config"):
        load_config(tmp_path)
