import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_package_declares_console_entrypoint_and_runtime_metadata() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "coding-harness"
    assert data["project"]["scripts"]["coding-harness"] == "coding_harness.cli.entrypoint:main"


def test_dockerfile_is_pinned_non_root_and_does_not_mount_socket() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12" in dockerfile
    assert "USER coding" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "docker.sock" not in dockerfile


def test_docker_context_excludes_secrets_and_local_state() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for entry in (".env", ".git", ".venv", "*.sqlite", ".claude"):
        assert entry in ignored


def test_entrypoint_exposes_web_command() -> None:
    script = (ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    assert "uvicorn" in script
    assert "0.0.0.0" in script
