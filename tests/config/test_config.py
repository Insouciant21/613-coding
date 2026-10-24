from __future__ import annotations

from pathlib import Path

import pytest

from coding613.config import (
    HarnessConfig,
    UserConfig,
    load_config,
    load_user_config,
    save_user_config,
    validate_config,
)
from coding613.domain.models import PermissionMode


def test_load_config_parses_toml_and_canonicalizes_repository_root(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        """
[policy]
mode = "strict"
validation_commands = [["pytest", "-q"], ["ruff", "check", "."]]
allow_network = true
""",
        encoding="utf-8",
    )

    config = load_config(tmp_path / ".")

    assert config.repository_root == tmp_path.resolve()
    assert config.permission_mode is PermissionMode.STRICT
    assert config.validation_commands == (("pytest", "-q"), ("ruff", "check", "."))
    assert config.allow_network is True


def test_default_mode_is_safe_for_interactive_runs(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.permission_mode is PermissionMode.BALANCED
    user = load_user_config(tmp_path / "user.toml")
    assert user.budgets.unattended is False
    assert user.budgets.total_model_calls is None
    assert user.providers == {}


def test_load_config_accepts_bypass_mode(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        '[policy]\nmode = "bypass"\n', encoding="utf-8"
    )

    assert load_config(tmp_path).permission_mode is PermissionMode.BYPASS


def test_default_provider_context_window_is_256k_and_reasoning_is_provider_defined(
    tmp_path: Path,
) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        'active_provider = "reasoning"\n[providers.reasoning]\n'
        'model = "gpt-5.6"\nreasoning_effort = "xhigh"\n',
        encoding="utf-8",
    )

    config = load_user_config(path)

    provider = config.providers["reasoning"]
    assert provider.context_window_chars == 256_000
    assert provider.reasoning_effort == "xhigh"


def test_context_window_size_is_configurable(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        "active_provider = \"local\"\n[providers.local]\n"
        "context_window_chars = 1234\n",
        encoding="utf-8",
    )

    config = load_user_config(path)

    assert config.providers["local"].context_window_chars == 1234


def test_context_window_size_must_be_positive(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        "active_provider = \"local\"\n[providers.local]\n"
        "context_window_chars = 0\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="greater than 0|positive"):
        load_user_config(path)


def test_default_llm_output_budget_leaves_room_for_reasoning_and_tool_calls(
    tmp_path: Path,
) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        'active_provider = "reasoning"\n[providers.reasoning]\n'
        'api = "responses"\nmodel = "reasoning-model"\n',
        encoding="utf-8",
    )

    config = load_user_config(path)

    assert config.providers["reasoning"].max_output_tokens == 128_000
    assert config.providers["reasoning"].reasoning_effort == "low"


def test_validation_commands_must_be_nonempty_argv_arrays(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        '[policy]\nvalidation_commands = ["pytest -q"]\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="argv"):
        load_config(tmp_path)


def test_unattended_user_config_requires_a_finite_budget(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        "[budgets]\nunattended = true\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="model-call|provider-cost"):
        load_user_config(path)


def test_load_config_parses_openai_compatible_provider_metadata(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        """
active_provider = "coding"

[providers.coding]
provider = "openai-compatible"
api = "responses"
base_url = "https://api.example.test/v1"
model = "coding-model"
credential = "openai"
timeout_seconds = 45.0
max_output_tokens = 1234
streaming = true
""",
        encoding="utf-8",
    )

    config = load_user_config(path)

    provider = config.providers["coding"]
    assert provider.provider == "openai-compatible"
    assert provider.api == "responses"
    assert provider.base_url == "https://api.example.test/v1"
    assert provider.model == "coding-model"
    assert provider.credential == "openai"
    assert provider.timeout_seconds == 45.0
    assert provider.max_output_tokens == 1234
    assert provider.streaming is True


def test_responses_hosted_tool_options_round_trip_in_user_config(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        'active_provider = "openai"\n'
        '[providers.openai]\napi = "responses"\nresponses_tools = ["web_search"]\n'
        '[providers.openai.responses_tool_options.web_search]\n'
        'search_context_size = "high"\n',
        encoding="utf-8",
    )

    config = load_user_config(path)
    assert config.providers["openai"].responses_tools == ("web_search",)
    assert config.providers["openai"].responses_tool_options == {
        "web_search": {"search_context_size": "high"}
    }
    save_user_config(config, path)
    loaded = load_user_config(path)
    assert loaded.providers["openai"].responses_tool_options["web_search"]["search_context_size"] == "high"


def test_llm_provider_url_cannot_contain_credentials(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        'active_provider = "bad"\n[providers.bad]\n'
        'base_url = "https://user:secret@example.test/v1"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="base_url"):
        load_user_config(path)


def test_user_profiles_allow_named_openai_compatible_adapters(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        'active_provider = "deepseek"\n[providers.deepseek]\n'
        'provider = "deepseek"\nmodel = "deepseek-chat"\n',
        encoding="utf-8",
    )

    config = load_user_config(path)

    assert config.providers["deepseek"].provider == "deepseek"


def test_provider_model_catalog_round_trips_selected_reasoning_profile(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        'active_provider = "coding"\n[providers.coding]\n'
        'active_model = "fast"\nmodel = "legacy"\n'
        '[providers.coding.models.fast]\nmodel = "gpt-fast"\nreasoning_effort = "low"\n'
        '[providers.coding.models.deep]\nmodel = "gpt-deep"\nreasoning_effort = "high"\n'
        'max_output_tokens = 12000\n',
        encoding="utf-8",
    )

    config = load_user_config(path)

    provider = config.providers["coding"]
    assert provider.effective().model == "gpt-fast"
    assert provider.effective().reasoning_effort == "low"
    provider = provider.model_copy(update={"active_model": "deep"})
    assert provider.effective().model == "gpt-deep"
    assert provider.effective().max_output_tokens == 12000
    save_user_config(config.model_copy(update={"providers": {"coding": provider}}), path)
    assert load_user_config(path).providers["coding"].models["deep"].model == "gpt-deep"


def test_model_catalog_accepts_provider_specific_reasoning_levels(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        'active_provider = "coding"\n[providers.coding]\n'
        '[providers.coding.models.maximal]\nmodel = "gpt-5.6"\nreasoning_effort = "max"\n',
        encoding="utf-8",
    )

    config = load_user_config(path)

    assert config.providers["coding"].models["maximal"].reasoning_effort == "max"


def test_model_alias_must_be_safe_toml_table_name(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    path.write_text(
        'active_provider = "coding"\n[providers.coding.models."bad.alias"]\n'
        'model = "gpt"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="model aliases"):
        load_user_config(path)


def test_project_harness_rejects_user_scoped_sections(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text("[llm]\nmodel = \"wrong-scope\"\n", encoding="utf-8")

    with pytest.raises(ValueError, match="user config"):
        load_config(tmp_path)


def test_user_config_round_trips_without_api_keys(tmp_path: Path) -> None:
    path = tmp_path / "user.toml"
    config = UserConfig(
        active_provider="local",
        providers={"local": {"model": "coding", "credential": "local-key"}},
    )

    save_user_config(config, path)
    persisted = path.read_text(encoding="utf-8")
    loaded = load_user_config(path)

    assert "api_key" not in persisted
    assert loaded == config


def test_validate_config_rejects_nonexistent_repository() -> None:
    config = HarnessConfig.model_construct(repository_root=Path("/does/not/exist"))

    with pytest.raises(ValueError, match="repository"):
        validate_config(config)


def test_explicit_prompt_cache_setting_round_trips_with_model_override(tmp_path: Path) -> None:
    from coding613.config import LLMConfig, ModelConfig

    provider = LLMConfig(api="responses", prompt_cache_explicit=True, active_model="plain",
                         models={"plain": ModelConfig(model="custom", prompt_cache_explicit=False)})
    config = UserConfig(active_provider="test", providers={"test": provider})
    path = tmp_path / "config.toml"
    save_user_config(config, path)
    restored = load_user_config(path).providers["test"]
    assert restored.prompt_cache_explicit is True
    assert restored.effective().prompt_cache_explicit is False
