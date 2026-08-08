from __future__ import annotations

from pathlib import Path

import httpx

from coding_harness.adapters.llm.mock import ScriptedLLM
from coding_harness.application.composition import build_services
from coding_harness.application.run_service import RunRequest
from coding_harness.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding_harness.domain.models import RunState, StopReason
from coding_harness.ports.llm import LLMResponse


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


def test_local_composition_persists_runs_and_can_cancel_without_provider(tmp_path: Path) -> None:
    services = build_services(tmp_path)
    run = services.run_service.create_run(RunRequest(task="inspect repository"))

    assert run.project_id is not None
    cancelled = services.run_service.cancel(run.id)

    assert cancelled.status is RunState.CANCELLED
    assert cancelled.stop_reason is StopReason.CANCELLED
    assert services.list_events(run.id)


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
    captured: dict[str, str] = {}

    def client_factory(headers: dict[str, str], timeout: float) -> httpx.Client:
        del timeout
        captured.update(headers)
        return httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": "", "tool_calls": []}}]},
                )
            ),
            headers=headers,
        )

    services = build_services(
        tmp_path,
        credential_store=secrets,  # type: ignore[arg-type]
        client_factory=client_factory,
    )
    run = services.run_service.create_run(RunRequest(task="use configured provider"))
    summary = services.run_service.resume(run.id)

    assert secrets.providers == ["openai"]
    assert captured["Authorization"] == "Bearer sk-composition-secret"
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
