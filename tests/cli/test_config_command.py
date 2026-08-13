from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from coding613.cli.config import app


def test_config_check_warns_when_bypass_is_persisted(
    tmp_path: Path, monkeypatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "harness.toml").write_text(
        '[policy]\nmode = "bypass"\n', encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    result = CliRunner().invoke(app, ["--repo", str(repository)])

    assert result.exit_code == 0
    assert "mode=bypass" in result.output
    assert "DANGEROUS: BYPASS" in result.output
