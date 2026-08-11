from __future__ import annotations

from pathlib import Path

import pytest

from coding613.application.credentials import CredentialStatus
from coding613.application.user_configuration import UserConfigurationService
from coding613.config import LLMConfig, ModelConfig, load_user_config


class FakeCredentials:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, provider: str, value: str) -> None:
        self.values[provider] = value

    def update(self, provider: str, value: str) -> None:
        self.set(provider, value)

    def clear(self, provider: str) -> None:
        self.values.pop(provider, None)

    def status(self, provider: str) -> CredentialStatus:
        configured = provider in self.values
        return CredentialStatus(
            provider=provider,
            configured=configured,
            source="keyring" if configured else "none",
        )

    def read_secret(self, provider: str) -> str:
        return self.values[provider]


def test_provider_profiles_are_user_scoped_and_switchable(tmp_path: Path) -> None:
    credentials = FakeCredentials()
    service = UserConfigurationService(tmp_path / "config.toml", credential_store=credentials)  # type: ignore[arg-type]

    service.upsert_provider(
        "openai",
        LLMConfig(model="gpt-4o", credential="openai-key"),
        make_active=True,
    )
    service.upsert_provider(
        "deepseek",
        LLMConfig(
            base_url="https://api.deepseek.example/v1",
            model="deepseek-chat",
            credential="deepseek-key",
            api="responses",
        ),
    )
    service.set_api_key("deepseek", "sk-deepseek-secret")
    service.select_provider("deepseek")

    profiles = service.profiles()
    assert [profile.name for profile in profiles] == ["deepseek", "openai"]
    assert service.active() is not None
    assert service.active().name == "deepseek"  # type: ignore[union-attr]
    assert credentials.values == {"deepseek-key": "sk-deepseek-secret"}
    persisted = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "sk-deepseek-secret" not in persisted
    assert "deepseek-chat" in persisted


def test_user_budget_updates_are_validated_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    service = UserConfigurationService(path, credential_store=FakeCredentials())  # type: ignore[arg-type]

    service.set_budget_value("total_model_calls", "12")
    assert load_user_config(path).budgets.total_model_calls == 12

    before = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="greater than zero"):
        service.set_budget_value("total_model_calls", "0")
    assert path.read_text(encoding="utf-8") == before

    unattended_path = tmp_path / "unattended.toml"
    unattended = UserConfigurationService(
        unattended_path, credential_store=FakeCredentials()
    )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="model-call|provider-cost"):
        unattended.set_budget_value("unattended", "true")


def test_provider_models_can_be_added_listed_and_switched(tmp_path: Path) -> None:
    service = UserConfigurationService(tmp_path / "config.toml", credential_store=FakeCredentials())  # type: ignore[arg-type]
    service.upsert_provider("coding", LLMConfig(model="legacy"), make_active=True)
    service.upsert_model(
        "coding",
        "fast",
        ModelConfig(model="coding-fast", reasoning_effort="low"),
    )
    service.upsert_model(
        "coding",
        "deep",
        ModelConfig(model="coding-deep", reasoning_effort="high", max_output_tokens=12000),
        make_active=True,
    )

    models = service.models("coding")
    assert [item.alias for item in models] == ["deep", "fast"]
    assert next(item for item in models if item.active).alias == "deep"
    assert service.active() is not None
    assert service.active().selected.model == "coding-deep"  # type: ignore[union-attr]

    service.select_model("coding", "fast")
    assert service.active().selected.model == "coding-fast"  # type: ignore[union-attr]
    service.set_model_reasoning("coding", "fast", "high")
    assert next(item for item in service.models("coding") if item.alias == "fast").config.reasoning_effort == "high"
    service.remove_model("coding", "fast")
    assert [item.alias for item in service.models("coding")] == ["deep"]


def test_provider_metadata_update_preserves_existing_model_catalogue(tmp_path: Path) -> None:
    service = UserConfigurationService(tmp_path / "config.toml", credential_store=FakeCredentials())  # type: ignore[arg-type]
    service.upsert_provider("coding", LLMConfig(model="legacy"), make_active=True)
    service.upsert_model("coding", "fast", ModelConfig(model="coding-fast"), make_active=True)
    service.upsert_provider(
        "coding",
        LLMConfig(model="new-default", base_url="https://api.example.test/v1"),
    )

    assert [item.alias for item in service.models("coding")] == ["fast"]
    assert service.active().selected.model == "coding-fast"  # type: ignore[union-attr]
