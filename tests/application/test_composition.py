from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from coding613.adapters.llm.mock import ScriptedLLM
from coding613.application.composition import build_services
from coding613.application.run_service import RunRequest
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.conversation import RunOptions
from coding613.domain.models import PermissionMode, RunState, StopReason
from coding613.ports.llm import LLMResponse


class _ProbeProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, context: object, tools: object) -> object:
        del context, tools
        self.calls += 1
        raise RuntimeError("probe provider failure")


class _SecretStore:
    def __init__(self, value: str) -> None:
        self.value = value
        self.providers: list[str] = []

    def read_secret(self, provider: str) -> str:
        self.providers.append(provider)
        return self.value


class _SdkCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="", tool_calls=[]),
                )
            ]
        )


class _SdkResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="output_text", text="ok")],
                )
            ],
            output_text="ok",
        )


class _SdkClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_SdkCompletions())
        self.responses = _SdkResponses()

    def close(self) -> None:
        return None


class _AnthropicMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="anthropic")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


class _AnthropicClient:
    def __init__(self) -> None:
        self.messages = _AnthropicMessages()

    def close(self) -> None:
        return None


def test_local_composition_persists_runs_and_can_cancel_without_provider(tmp_path: Path) -> None:
    services = build_services(tmp_path)
    run = services.run_service.create_run(RunRequest(task="inspect repository"))

    assert run.project_id is not None
    cancelled = services.run_service.cancel(run.id)

    assert cancelled.status is RunState.CANCELLED
    assert cancelled.stop_reason is StopReason.CANCELLED
    assert services.list_events(run.id)


def test_local_composition_uses_configured_mode_for_unspecified_run_mode(
    tmp_path: Path,
) -> None:
    (tmp_path / "harness.toml").write_text(
        """
[policy]
mode = "autonomous"
""",
        encoding="utf-8",
    )

    services = build_services(tmp_path)
    run = services.run_service.create_run(RunRequest(task="act autonomously"))

    assert run.permission_mode is PermissionMode.AUTONOMOUS


def test_local_composition_explicit_mode_overrides_configured_mode(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        """
[policy]
mode = "autonomous"
""",
        encoding="utf-8",
    )

    services = build_services(tmp_path)
    run = services.run_service.create_run(
        RunRequest(task="require approval", permission_mode=PermissionMode.STRICT)
    )

    assert run.permission_mode is PermissionMode.STRICT


def test_local_composition_reloads_tui_configuration_for_future_runs(tmp_path: Path) -> None:
    config_path = tmp_path / "harness.toml"
    config_path.write_text(
        '[policy]\nmode = "balanced"\nvalidation_commands = [["bash", "old.sh"]]\n',
        encoding="utf-8",
    )
    services = build_services(tmp_path)
    config_path.write_text(
        '[policy]\nmode = "autonomous"\nvalidation_commands = [["bash", "new.sh"]]\n',
        encoding="utf-8",
    )

    updated = services.reload_configuration()
    run = services.run_service.create_run(RunRequest(task="use refreshed config"))
    dependencies = services.run_service._get_dependencies(run)  # type: ignore[attr-defined]
    validation = next(
        item for item in dependencies.tools.definitions() if item.name == "run_validation"
    )

    assert updated.permission_mode is PermissionMode.AUTONOMOUS
    assert services.permission_mode is PermissionMode.AUTONOMOUS
    assert run.permission_mode is PermissionMode.AUTONOMOUS
    assert '["bash", "new.sh"]' in validation.description


def test_local_composition_wires_and_reloads_llm_context_window(tmp_path: Path) -> None:
    config_path = tmp_path / "user.toml"
    config_path.write_text(
        'active_provider = "local"\n[providers.local]\n'
        "context_window_chars = 24000\n",
        encoding="utf-8",
    )
    services = build_services(tmp_path, user_config_path=config_path)
    run = services.run_service.create_run(RunRequest(task="inspect context"))
    dependencies = services.run_service._get_dependencies(run)  # type: ignore[attr-defined]

    base_context = dependencies.context_builder._base  # type: ignore[attr-defined]
    assert base_context.max_context_chars == 24_000

    config_path.write_text(
        'active_provider = "local"\n[providers.local]\n'
        "context_window_chars = 12000\n",
        encoding="utf-8",
    )
    services.reload_configuration()

    assert base_context.max_context_chars == 12_000


def test_local_composition_applies_invocation_budget_overrides(tmp_path: Path) -> None:
    user_path = tmp_path / "user.toml"
    user_path.write_text(
        "[budgets]\ntotal_model_calls = 20\n", encoding="utf-8"
    )
    services = build_services(tmp_path, user_config_path=user_path)
    run = services.run_service.create_run(
        RunRequest(
            task="bounded run",
            options=RunOptions(
                budget_overrides={
                    "per_agent_turns": 2,
                    "total_model_calls": 3,
                    "wall_time_seconds": 4.0,
                }
            ),
        )
    )

    dependencies = services.run_service._get_dependencies(run)  # type: ignore[attr-defined]

    assert dependencies.budget_limits.per_agent_turns == 2
    assert dependencies.budget_limits.total_model_calls == 3
    assert dependencies.budget_limits.wall_time_seconds == 4.0


def test_local_composition_reads_new_run_after_service_restart(tmp_path: Path) -> None:
    services = build_services(tmp_path)
    run = services.run_service.create_run(RunRequest(task="inspect after restart"))

    restarted = build_services(tmp_path)
    summary = restarted.run_service.get_summary(run.id)

    assert summary.run_id == run.id
    assert summary.status is RunState.RUNNING
    assert summary.stop_reason is None
    assert summary.changed_files == ()
    assert summary.validation_evidence == ()
    assert summary.approvals == ()
    assert summary.unresolved_risks == ()
    assert summary.completion_blockers == ()
    assert summary.resource_usage.agent_turns == 0
    assert summary.resource_usage.model_calls == 0
    assert summary.resource_usage.wall_time_seconds == 0
    assert summary.resource_usage.provider_cost == 0


def test_local_composition_reports_provider_boundary_on_resume(tmp_path: Path) -> None:
    services = build_services(tmp_path)
    run = services.run_service.create_run(RunRequest(task="make a change"))

    summary = services.run_service.resume(run.id)

    assert summary.status is RunState.FAILED
    assert summary.stop_reason is StopReason.PROVIDER_ERROR


def test_local_composition_accepts_an_injected_provider(tmp_path: Path) -> None:
    provider = _ProbeProvider()
    services = build_services(tmp_path, provider=provider)  # type: ignore[arg-type]
    run = services.run_service.create_run(RunRequest(task="call the provider"))

    summary = services.run_service.resume(run.id)

    assert provider.calls == 1
    assert summary.status is RunState.FAILED
    assert summary.stop_reason is StopReason.PROVIDER_ERROR


def test_local_composition_builds_configured_provider_without_persisting_key(
    tmp_path: Path,
) -> None:
    user_path = tmp_path / "user.toml"
    (tmp_path / "harness.toml").write_text(
        """
""",
        encoding="utf-8",
    )
    user_path.write_text(
        """
active_provider = "openai"

[providers.openai]
provider = "openai-compatible"
base_url = "https://api.example.test/v1"
model = "coding-model"
credential = "openai"

[budgets]
total_model_calls = 1
""",
        encoding="utf-8",
    )
    secrets = _SecretStore("sk-composition-secret")
    captured: list[tuple[str, str, float]] = []

    def client_factory(api_key: str, base_url: str, timeout: float) -> _SdkClient:
        captured.append((api_key, base_url, timeout))
        return _SdkClient()

    services = build_services(
        tmp_path,
        credential_store=secrets,  # type: ignore[arg-type]
        client_factory=client_factory,
        user_config_path=user_path,
    )
    run = services.run_service.create_run(RunRequest(task="use configured provider"))
    summary = services.run_service.resume(run.id)

    assert secrets.providers == ["openai"]
    assert captured == [("sk-composition-secret", "https://api.example.test/v1", 60.0)]
    assert summary.status is RunState.FAILED
    events = services.list_events(run.id)
    assert all("sk-composition-secret" not in event.model_dump_json() for event in events)


def test_local_composition_selects_configured_responses_api(
    tmp_path: Path,
) -> None:
    user_path = tmp_path / "user.toml"
    (tmp_path / "harness.toml").write_text(
        """
""",
        encoding="utf-8",
    )
    user_path.write_text(
        """
active_provider = "openai"

[providers.openai]
api = "responses"
provider = "openai-compatible"
base_url = "https://api.example.test/v1"
model = "coding-model"
credential = "openai"

[budgets]
total_model_calls = 1
""",
        encoding="utf-8",
    )
    secrets = _SecretStore("sk-responses-secret")
    clients: list[_SdkClient] = []

    def client_factory(api_key: str, base_url: str, timeout: float) -> _SdkClient:
        del api_key, base_url, timeout
        client = _SdkClient()
        clients.append(client)
        return client

    services = build_services(
        tmp_path,
        credential_store=secrets,  # type: ignore[arg-type]
        client_factory=client_factory,
        user_config_path=user_path,
    )
    run = services.run_service.create_run(RunRequest(task="use Responses"))

    services.run_service.resume(run.id)

    assert len(clients) == 1
    assert len(clients[0].responses.calls) == 1
    assert clients[0].chat.completions.calls == []


def test_local_composition_reloads_selected_provider_model_profile(tmp_path: Path) -> None:
    user_path = tmp_path / "user.toml"
    user_path.write_text(
        'active_provider = "coding"\n[providers.coding]\n'
        'provider = "openai-compatible"\napi = "responses"\n'
        'base_url = "https://api.example.test/v1"\nmodel = "legacy"\n'
        'credential = "coding"\nactive_model = "fast"\n'
        '[providers.coding.models.fast]\nmodel = "fast-model"\nreasoning_effort = "low"\n'
        '[providers.coding.models.deep]\nmodel = "deep-model"\nreasoning_effort = "high"\n'
        'max_output_tokens = 12000\n',
        encoding="utf-8",
    )
    secrets = _SecretStore("sk-secret")
    clients: list[_SdkClient] = []

    def client_factory(api_key: str, base_url: str, timeout: float) -> _SdkClient:
        del api_key, base_url, timeout
        client = _SdkClient()
        clients.append(client)
        return client

    services = build_services(
        tmp_path,
        credential_store=secrets,  # type: ignore[arg-type]
        client_factory=client_factory,
        user_config_path=user_path,
    )
    assert services.llm_metadata is not None
    assert services.llm_metadata.model == "fast-model"
    services.switch_model("coding", "deep")
    assert services.llm_metadata is not None
    assert services.llm_metadata.model == "deep-model"
    assert services.llm_metadata.reasoning_effort == "high"
    run = services.run_service.create_run(RunRequest(task="selected model"))
    dependencies = services.run_service._get_dependencies(run)  # type: ignore[attr-defined]
    assert dependencies.max_output_tokens == 12000


def test_local_composition_selects_anthropic_sdk_adapter(tmp_path: Path) -> None:
    user_path = tmp_path / "user.toml"
    user_path.write_text(
        'active_provider = "claude"\n[providers.claude]\n'
        'provider = "anthropic"\napi = "anthropic"\n'
        'base_url = "https://api.anthropic.com"\nmodel = "claude-sonnet"\n'
        'credential = "claude"\n[budgets]\ntotal_model_calls = 1\n',
        encoding="utf-8",
    )
    secrets = _SecretStore("sk-anthropic-secret")
    clients: list[_AnthropicClient] = []

    def client_factory(api_key: str, base_url: str | None, timeout: float) -> _AnthropicClient:
        assert api_key == "sk-anthropic-secret"
        assert base_url == "https://api.anthropic.com"
        assert timeout == 60.0
        client = _AnthropicClient()
        clients.append(client)
        return client

    services = build_services(
        tmp_path,
        credential_store=secrets,  # type: ignore[arg-type]
        anthropic_client_factory=client_factory,
        user_config_path=user_path,
    )
    run = services.run_service.create_run(RunRequest(task="use Anthropic"))

    services.run_service.resume(run.id)

    assert len(clients) == 1
    assert clients[0].messages.calls[0]["model"] == "claude-sonnet"


def test_local_composition_runs_repository_tool_and_declared_validation(
    tmp_path: Path,
) -> None:
    (tmp_path / "answer.txt").write_text("answer\n", encoding="utf-8")
    user_path = tmp_path / "user.toml"
    (tmp_path / "harness.toml").write_text(
        """
[validation]
commands = [["python", "-c", "print('ok')"]]
""",
        encoding="utf-8",
    )
    user_path.write_text("[budgets]\ntotal_model_calls = 3\n", encoding="utf-8")
    provider = ScriptedLLM(
        (
            LLMResponse(
                actions=(
                    ActionEnvelope(
                        action=ToolCall(name="read_file", arguments={"path": "answer.txt"})
                    ),
                )
            ),
            LLMResponse(
                actions=(
                    ActionEnvelope(
                        action=ToolCall(
                            name="run_validation",
                            arguments={"argv": ["python", "-c", "print('ok')"]},
                        )
                    ),
                )
            ),
            LLMResponse(actions=(ActionEnvelope(action=FinishAction(summary="inspected")),)),
        )
    )
    services = build_services(tmp_path, provider=provider, user_config_path=user_path)
    run = services.run_service.create_run(RunRequest(task="inspect answer"))

    summary = services.run_service.resume(run.id)

    assert summary.status is RunState.COMPLETED
    assert summary.stop_reason is StopReason.SUCCESS
    assert summary.validation_evidence


def test_local_composition_applies_run_tool_filters_before_repository_execution(
    tmp_path: Path,
) -> None:
    target = tmp_path / "answer.txt"
    target.write_text("answer\n", encoding="utf-8")
    provider = ScriptedLLM(
        (
            LLMResponse(
                actions=(
                    ActionEnvelope(
                        action=ToolCall(
                            name="read_file", arguments={"path": "answer.txt"}
                        )
                    ),
                )
            ),
        )
    )
    services = build_services(tmp_path, provider=provider)
    run = services.run_service.create_run(
        RunRequest(
            task="read answer",
            options=RunOptions(disallowed_tools=frozenset({"read_file"})),
        )
    )

    summary = services.run_service.resume(run.id)

    assert summary.status is RunState.FAILED
    assert summary.unresolved_risks == ("invocation.tool_disallowed",)
    assert target.read_text(encoding="utf-8") == "answer\n"


def test_local_composition_runs_apply_patch_and_persists_changed_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "answer.txt"
    target.write_text("before\n", encoding="utf-8")
    user_path = tmp_path / "user.toml"
    (tmp_path / "harness.toml").write_text(
        """
[validation]
commands = [["python", "-c", "print('ok')"]]
""",
        encoding="utf-8",
    )
    user_path.write_text("[budgets]\ntotal_model_calls = 2\n", encoding="utf-8")
    provider = ScriptedLLM(
        (
            LLMResponse(
                actions=(
                    ActionEnvelope(
                        action=ToolCall(
                            name="apply_patch",
                            arguments={
                                "patch": """--- a/answer.txt
+++ b/answer.txt
@@ -1 +1 @@
-before
+after
"""
                            },
                        )
                    ),
                )
            ),
            LLMResponse(actions=(ActionEnvelope(action=FinishAction(summary="patched")),)),
        )
    )
    services = build_services(tmp_path, provider=provider, user_config_path=user_path)
    run = services.run_service.create_run(RunRequest(task="patch answer"))

    summary = services.run_service.resume(run.id)

    assert summary.status is RunState.COMPLETED
    assert summary.changed_files == ("answer.txt",)
    assert target.read_text(encoding="utf-8") == "after\n"
