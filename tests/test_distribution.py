import importlib.util
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_package_declares_only_613_coding_console_entrypoint() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "613-coding"
    assert data["project"]["scripts"] == {
        "613-coding": "coding613.cli.entrypoint:main",
    }


def test_package_declares_click_runtime_dependency_for_entrypoint() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = {dependency.split("[", 1)[0].split(">", 1)[0].split("=", 1)[0] for dependency in data["project"]["dependencies"]}
    assert "click" in dependencies


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


def test_dockerfile_is_builder_only_and_exports_three_artifacts() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith(
        "FROM python:3.12.8-slim-bookworm@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0 AS builder"
    )
    assert "FROM scratch AS artifacts" in dockerfile
    assert "COPY --from=builder /out/ /" in dockerfile
    assert "ENTRYPOINT" not in dockerfile
    assert "CMD" not in dockerfile
    assert "EXPOSE" not in dockerfile
    assert "HEALTHCHECK" not in dockerfile
    for artifact in ("613-coding-linux-x86_64", "613_coding-", "SHA256SUMS"):
        assert artifact in dockerfile or artifact in (ROOT / "scripts/build_artifacts.sh").read_text(encoding="utf-8")


def test_docker_builder_installs_pyinstaller_system_tools() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "apt-get install" in dockerfile
    assert "binutils" in dockerfile


def test_ci_uses_artifact_builder_and_has_no_removed_container_smoke() -> None:
    github = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    gitlab = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    for workflow in (github, gitlab):
        assert "smoke_container.sh" not in workflow
        assert "--target artifacts" in workflow
        assert "smoke_artifacts.sh" in workflow
        assert "SHA256SUMS" in workflow or "dist/" in workflow
    assert "actions/upload-artifact" in github
    assert "setup-uv@v6" in github
    assert 'tags: ["v*"]' in github
    assert "contents: write" in github
    assert "action-gh-release" in github
    for artifact in (
        "613-coding-linux-x86_64",
        "613_coding-*.whl",
        "613_coding-*.tar.gz",
        "SHA256SUMS",
    ):
        assert artifact in github
    assert "artifact-smoke" in gitlab
    assert "needs:" in gitlab
    docker_job, smoke_job = gitlab.split("artifact-smoke:", 1)
    docker_job = docker_job.rsplit("docker-build:", 1)[1]
    assert "before_script: []" in docker_job
    assert "smoke_artifacts.sh" not in docker_job
    assert "smoke_artifacts.sh" in smoke_job


def test_artifact_builder_uses_pinned_pyinstaller() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = "\n".join(data["dependency-groups"]["dev"])
    assert re.search(r"pyinstaller>=6\.16,<7", dev)
