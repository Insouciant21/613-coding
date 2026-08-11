from __future__ import annotations

from dataclasses import dataclass

from typer.testing import CliRunner

from coding613.application.credentials import CredentialStatus
from coding613.application.user_configuration import ProviderProfile
from coding613.cli.providers import app
from coding613.config import LLMConfig, ModelConfig, UserConfig


@dataclass
class FakeProviderService:
    profiles_value: tuple[ProviderProfile, ...] = ()
    selected: str | None = None
    added: tuple[str, LLMConfig] | None = None
    model_added: tuple[str, str, ModelConfig] | None = None
    reasoning_set: tuple[str, str, str] | None = None

    def profiles(self) -> tuple[ProviderProfile, ...]:
        return self.profiles_value

    def select_provider(self, name: str) -> UserConfig:
        self.selected = name
        return UserConfig(active_provider=name, providers={name: LLMConfig()})

    def upsert_provider(self, name: str, provider: LLMConfig, **_: object) -> UserConfig:
        self.added = (name, provider)
        return UserConfig(active_provider=name, providers={name: provider})

    def upsert_model(
        self, provider: str, alias: str, model: ModelConfig, **_: object
    ) -> UserConfig:
        self.model_added = (provider, alias, model)
        return UserConfig()

    def set_model_reasoning(self, provider: str, alias: str, effort: str) -> UserConfig:
        self.reasoning_set = (provider, alias, effort)
        return UserConfig()


def _profile(name: str, *, active: bool = False) -> ProviderProfile:
    return ProviderProfile(
        name=name,
        config=LLMConfig(model="coding-model", credential=f"{name}-key"),
        active=active,
        credential=CredentialStatus(provider=f"{name}-key", configured=True, source="keyring"),
    )


def test_provider_list_is_metadata_only(monkeypatch) -> None:
    service = FakeProviderService(profiles_value=(_profile("ai2", active=True),))
    monkeypatch.setattr("coding613.cli.providers.get_user_configuration_service", lambda: service)

    result = CliRunner().invoke(app, ["list"])

    assert result.exit_code == 0
    assert "ai2" in result.stdout
    assert "coding-model" in result.stdout
    assert "api_key" not in result.stdout


def test_provider_use_selects_profile(monkeypatch) -> None:
    service = FakeProviderService(profiles_value=(_profile("ai2"),))
    monkeypatch.setattr("coding613.cli.providers.get_user_configuration_service", lambda: service)

    result = CliRunner().invoke(app, ["use", "ai2"])

    assert result.exit_code == 0
    assert service.selected == "ai2"


def test_provider_add_persists_non_secret_options(monkeypatch) -> None:
    service = FakeProviderService()
    monkeypatch.setattr("coding613.cli.providers.get_user_configuration_service", lambda: service)

    result = CliRunner().invoke(
        app,
        [
            "add",
            "deepseek",
            "--base-url",
            "https://api.example.test/v1",
            "--model",
            "deepseek-chat",
            "--api",
            "responses",
            "--active",
        ],
    )

    assert result.exit_code == 0
    assert service.added is not None
    assert service.added[0] == "deepseek"
    assert service.added[1].api == "responses"


def test_provider_model_add_accepts_reasoning_profile(monkeypatch) -> None:
    service = FakeProviderService()
    monkeypatch.setattr("coding613.cli.providers.get_user_configuration_service", lambda: service)

    result = CliRunner().invoke(
        app,
        [
            "models",
            "add",
            "ai2",
            "deep",
            "--model",
            "gpt-deep",
            "--reasoning-effort",
            "high",
            "--active",
        ],
    )

    assert result.exit_code == 0
    assert service.model_added is not None
    assert service.model_added[0:2] == ("ai2", "deep")
    assert service.model_added[2].reasoning_effort == "high"


def test_provider_model_reasoning_can_be_switched(monkeypatch) -> None:
    service = FakeProviderService()
    monkeypatch.setattr("coding613.cli.providers.get_user_configuration_service", lambda: service)

    result = CliRunner().invoke(app, ["models", "reasoning", "ai2", "deep", "high"])

    assert result.exit_code == 0
    assert service.reasoning_set == ("ai2", "deep", "high")


def test_provider_model_reasoning_accepts_provider_specific_level(monkeypatch) -> None:
    service = FakeProviderService()
    monkeypatch.setattr("coding613.cli.providers.get_user_configuration_service", lambda: service)

    result = CliRunner().invoke(app, ["models", "reasoning", "ai2", "deep", "xhigh"])

    assert result.exit_code == 0
    assert service.reasoning_set == ("ai2", "deep", "xhigh")
