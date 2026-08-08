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


def test_dockerfile_copies_sources_before_project_sync() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.index("COPY src ./src") < dockerfile.index("uv sync --frozen")


def test_ci_defines_unit_and_container_jobs() -> None:
    gitlab = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    github = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "unit-test:" in gitlab
    assert "docker-build:" in gitlab
    assert "docker build" in gitlab
    assert "unit-test:" in github
    assert "docker build" in github


def test_render_manifest_exposes_health_check() -> None:
    manifest = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "runtime: docker" in manifest
    assert "healthCheckPath: /healthz" in manifest
