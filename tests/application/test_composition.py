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
    def create(self, **kwargs: object) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="", tool_calls=[]),
                )
            ]
        )


class _SdkClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_SdkCompletions())

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
    (tmp_path / "harness.toml").write_text(
        """
[llm]
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
    )
    run = services.run_service.create_run(RunRequest(task="use configured provider"))
    summary = services.run_service.resume(run.id)

    assert secrets.providers == ["openai"]
    assert captured == [("sk-composition-secret", "https://api.example.test/v1", 60.0)]
    assert summary.status is RunState.FAILED
    events = services.list_events(run.id)
    assert all("sk-composition-secret" not in event.model_dump_json() for event in events)


def test_local_composition_runs_repository_tool_and_declared_validation(
    tmp_path: Path,
) -> None:
    (tmp_path / "answer.txt").write_text("answer\n", encoding="utf-8")
    (tmp_path / "harness.toml").write_text(
        """
[validation]
commands = [["python", "-c", "print('ok')"]]

[budgets]
total_model_calls = 2
""",
        encoding="utf-8",
    )
    provider = ScriptedLLM(
        (
            LLMResponse(
                actions=(
                    ActionEnvelope(
                        action=ToolCall(name="read_file", arguments={"path": "answer.txt"})
                    ),
                )
            ),
            LLMResponse(actions=(ActionEnvelope(action=FinishAction(summary="inspected")),)),
        )
    )
    services = build_services(tmp_path, provider=provider)
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
    (tmp_path / "harness.toml").write_text(
        """
[validation]
commands = [["python", "-c", "print('ok')"]]

[budgets]
total_model_calls = 2
""",
        encoding="utf-8",
    )
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
    services = build_services(tmp_path, provider=provider)
    run = services.run_service.create_run(RunRequest(task="patch answer"))

    summary = services.run_service.resume(run.id)

    assert summary.status is RunState.COMPLETED
    assert summary.changed_files == ("answer.txt",)
    assert target.read_text(encoding="utf-8") == "after\n"
