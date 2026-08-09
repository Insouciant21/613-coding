"""Application boundary for provider credentials.

Secret material is accepted only by ``set``/``update`` and is never included
in returned models or their representations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


class CredentialError(RuntimeError):
    """Raised when a provider credential is unavailable or invalid."""


@dataclass(frozen=True, slots=True)
class SecretReference:
    provider: str
    source: Literal["keyring", "env"]
    configured: bool = True

    def __repr__(self) -> str:
        return (
            f"SecretReference(provider={self.provider!r}, source={self.source!r}, "
            f"configured={self.configured!r})"
        )


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    provider: str
    configured: bool
    source: Literal["keyring", "env", "none"]


class CredentialStore(Protocol):
    def set(self, provider: str, value: str) -> None: ...
    def update(self, provider: str, value: str) -> None: ...
    def clear(self, provider: str) -> None: ...
    def status(self, provider: str) -> CredentialStatus: ...
    def resolve(self, provider: str) -> SecretReference: ...


class CredentialService:
    def __init__(self, store: CredentialStore) -> None:
        self._store = store

    @staticmethod
    def _validate(provider: str, hidden_input: str) -> None:
        if not provider or not provider.strip():
            raise CredentialError("provider must not be empty")
        if not hidden_input:
            raise CredentialError("credential input must not be empty")

    def set(self, provider: str, hidden_input: str) -> None:
        self._validate(provider, hidden_input)
        self._store.set(provider.strip(), hidden_input)

    def update(self, provider: str, hidden_input: str) -> None:
        self._validate(provider, hidden_input)
        self._store.update(provider.strip(), hidden_input)

    def clear(self, provider: str) -> None:
        if not provider or not provider.strip():
            raise CredentialError("provider must not be empty")
        self._store.clear(provider.strip())

    def status(self, provider: str) -> CredentialStatus:
        if not provider or not provider.strip():
            raise CredentialError("provider must not be empty")
        return self._store.status(provider.strip())

    def resolve(self, provider: str) -> SecretReference:
        if not provider or not provider.strip():
            raise CredentialError("provider must not be empty")
        return self._store.resolve(provider.strip())
