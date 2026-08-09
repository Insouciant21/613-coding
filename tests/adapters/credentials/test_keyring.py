from __future__ import annotations

import pytest

from coding613.adapters.credentials.keyring import KeyringCredentialStore
from coding613.application.credentials import CredentialError, CredentialService


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def service(fake: FakeKeyring, **kwargs: object) -> CredentialService:
    return CredentialService(KeyringCredentialStore(keyring_backend=fake, **kwargs))


def test_set_uses_hidden_keyring_input_and_status_is_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeKeyring()
    credentials = service(fake)

    credentials.set("openai", "sk-super-secret-123")

    assert fake.values["coding-harness", "openai"] == "sk-super-secret-123"
    assert credentials.status("openai").configured is True
    print(credentials.status("openai"))
    assert "sk-super-secret-123" not in repr(credentials.status("openai"))
    assert "sk-super-secret-123" not in capsys.readouterr().out


def test_update_and_clear_change_configuration_without_returning_secret() -> None:
    fake = FakeKeyring()
    credentials = service(fake)
    credentials.set("openai", "old-secret")

    credentials.update("openai", "new-secret")
    reference = credentials.resolve("openai")
    assert reference.configured is True
    assert "new-secret" not in repr(reference)

    credentials.clear("openai")
    assert credentials.status("openai").configured is False


def test_missing_key_raises_and_providers_are_isolated() -> None:
    fake = FakeKeyring()
    credentials = service(fake)
    credentials.set("openai", "openai-secret")

    with pytest.raises(CredentialError):
        credentials.resolve("anthropic")
    assert credentials.resolve("openai").provider == "openai"


def test_env_fallback_is_opt_in_and_is_not_used_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODING_HARNESS_ANTHROPIC_API_KEY", "env-secret")
    fake = FakeKeyring()
    credentials = service(fake)
    with pytest.raises(CredentialError):
        credentials.resolve("anthropic")

    fallback = service(fake, allow_env_fallback=True)
    assert fallback.resolve("anthropic").source == "env"
    assert "env-secret" not in repr(fallback.resolve("anthropic"))


class KeyringBackendError(RuntimeError):
    pass


class RaisingOnDeleteKeyring(FakeKeyring):
    """Backend that always raises on delete_password (e.g. Freedesktop Secret Service)."""

    def delete_password(self, service: str, username: str) -> None:
        raise KeyringBackendError("keyring: no item found")


class AlwaysRaisingKeyring:
    """Backend that raises on every call -- simulates delete+get double-fault."""

    def get_password(self, service: str, username: str) -> str | None:
        raise KeyringBackendError("keyring: get_password failed")

    def set_password(self, service: str, username: str, password: str) -> None:
        pass

    def delete_password(self, service: str, username: str) -> None:
        raise KeyringBackendError("keyring: delete_password failed")


def test_clear_missing_key_is_idempotent_when_backend_raises_on_delete() -> None:
    """clear() must not propagate the backend exception when the entry is absent."""
    backend = RaisingOnDeleteKeyring()
    credentials = service(backend)
    # Key was never set; delete_password raises but get_password returns None -> silent
    credentials.clear("openai")


def test_clear_double_fault_raises_credential_error() -> None:
    """When delete_password AND get_password both raise, clear() must raise CredentialError."""
    backend = AlwaysRaisingKeyring()
    credentials = CredentialService(KeyringCredentialStore(keyring_backend=backend))
    with pytest.raises(CredentialError):
        credentials.clear("openai")
