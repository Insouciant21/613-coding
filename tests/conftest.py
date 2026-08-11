from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_user_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keep offline tests independent from a developer's real provider profiles."""

    monkeypatch.setenv("CODING613_CONFIG_FILE", str(tmp_path / "user-config.toml"))
