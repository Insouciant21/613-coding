from __future__ import annotations

from dataclasses import dataclass

from typer.testing import CliRunner

from coding_harness.application.credentials import CredentialStatus
from coding_harness.cli.credentials import app


@dataclass
class FakeCredentials:
    value: str | None = None

    def set(self, provider: str, hidden_input: str) -> None:
        self.value = hidden_input

    def update(self, provider: str, hidden_input: str) -> None:
        self.value = hidden_input

    def clear(self, provider: str) -> None:
        self.value = None

    def status(self, provider: str) -> CredentialStatus:
        return CredentialStatus(provider=provider, configured=self.value is not None, source="keyring" if self.value else "none")


def test_set_reads_hidden_input_and_never_prints_secret(monkeypatch) -> None:
    fake = FakeCredentials()
    monkeypatch.setattr("coding_harness.cli.credentials.get_credential_service", lambda: fake)
    result = CliRunner().invoke(app, ["set", "openai"], input="sk-cli-secret\nsk-cli-secret\n")

    assert result.exit_code == 0
    assert fake.value == "sk-cli-secret"
    assert "sk-cli-secret" not in result.stdout


def test_status_is_redacted_and_clear_removes_provider(monkeypatch) -> None:
    fake = FakeCredentials(value="sk-cli-secret")
    monkeypatch.setattr("coding_harness.cli.credentials.get_credential_service", lambda: fake)

    status = CliRunner().invoke(app, ["status", "openai"])
    cleared = CliRunner().invoke(app, ["clear", "openai"])

    assert status.exit_code == 0
    assert "configured" in status.stdout
    assert "sk-cli-secret" not in status.stdout
    assert cleared.exit_code == 0
    assert fake.value is None
