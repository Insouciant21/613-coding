import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_package_declares_only_613_coding_console_entrypoint() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "613-coding"
    assert data["project"]["scripts"] == {
        "613-coding": "coding613.cli.entrypoint:main",
    }


def test_only_coding613_import_package_is_available() -> None:
    assert importlib.util.find_spec("coding613") is not None
    assert importlib.util.find_spec("coding_harness") is None


def test_main_distribution_has_no_web_http_runtime_surface() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = "\n".join(data["project"]["dependencies"])
    assert "fastapi" not in dependencies.lower()
    assert "uvicorn" not in dependencies.lower()
    assert importlib.util.find_spec("coding613.api") is None
    assert importlib.util.find_spec("coding613.web") is None
    assert not (ROOT / "render.yaml").exists()
    assert not (ROOT / "docker/entrypoint.sh").exists()
    assert not (ROOT / "scripts/smoke_container.sh").exists()


def test_current_root_help_has_no_web_command() -> None:
    from typer.testing import CliRunner

    from coding613.cli.main import app

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert " web" not in result.stdout
