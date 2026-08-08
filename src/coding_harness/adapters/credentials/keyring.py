"""OS keyring credential adapter with an explicit environment fallback."""

from __future__ import annotations

import os
from typing import Any, cast

import keyring

from coding_harness.application.credentials import (
    CredentialError,
    CredentialStatus,
    SecretReference,
)


class KeyringCredentialStore:
    def __init__(
        self,
        *,
        service_name: str = "coding-harness",
        keyring_backend: Any = keyring,
        allow_env_fallback: bool = False,
    ) -> None:
        self._service_name = service_name
        self._keyring = keyring_backend
        self._allow_env_fallback = allow_env_fallback

    @staticmethod
    def _env_name(provider: str) -> str:
        normalized = "".join(character if character.isalnum() else "_" for character in provider)
        return f"CODING_HARNESS_{normalized.upper()}_API_KEY"

    def _keyring_value(self, provider: str) -> str | None:
        return cast(str | None, self._keyring.get_password(self._service_name, provider))

    def set(self, provider: str, value: str) -> None:
        self._keyring.set_password(self._service_name, provider, value)

    def update(self, provider: str, value: str) -> None:
        self.set(provider, value)

    def read_secret(self, provider: str) -> str:
        """Read secret material for an ephemeral provider client only."""

        value = self._keyring_value(provider)
        if value:
            return value
        if self._allow_env_fallback:
            value = os.environ.get(self._env_name(provider))
            if value:
                return value
        raise CredentialError(f"no credential configured for provider {provider}")

    def clear(self, provider: str) -> None:
        try:
            self._keyring.delete_password(self._service_name, provider)
        except Exception as delete_error:
            # Backends differ on whether deleting a missing entry is an error.
            try:
                still_present = self._keyring_value(provider) is not None
            except Exception as read_error:
                raise CredentialError("could not clear provider credential") from read_error
            if still_present:
                raise CredentialError("could not clear provider credential") from delete_error

    def status(self, provider: str) -> CredentialStatus:
        if self._keyring_value(provider) is not None:
            return CredentialStatus(provider=provider, configured=True, source="keyring")
        if self._allow_env_fallback and os.environ.get(self._env_name(provider)):
            return CredentialStatus(provider=provider, configured=True, source="env")
        return CredentialStatus(provider=provider, configured=False, source="none")

    def resolve(self, provider: str) -> SecretReference:
        status = self.status(provider)
        if not status.configured or status.source == "none":
            raise CredentialError(f"no credential configured for provider {provider}")
        return SecretReference(provider=provider, source=status.source)
