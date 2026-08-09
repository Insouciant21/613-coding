from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_readme_and_deployment_cover_acquisition_security_and_limits() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    deployment = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")
    text = f"{readme}\n{deployment}"
    for required in (
        "uv sync",
        "uv build",
        "Docker",
        "keyring",
        ".env",
        "SQLite",
        "LanceDB",
        "GitLab CI",
        "limitations",
        "613-coding",
        "--resume",
    ):
        assert required.lower() in text.lower()
    assert "unverified" not in deployment.lower()


def test_current_guidance_has_no_removed_server_or_web_instructions() -> None:
    current = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "docs/deployment.md", "docs/development.md")
    ).lower()
    for forbidden in (
        "fastapi",
        "uvicorn",
        "webui",
        "render.yaml",
        "ssh deployment",
        "reverse proxy",
        "healthz",
        "613-coding web",
        "coding613.api",
        "coding613.web",
    ):
        assert forbidden not in current


def test_reflection_is_explicitly_student_authored_boundary() -> None:
    reflection = (ROOT / "REFLECTION.md").read_text(encoding="utf-8")
    assert "student-authored" in reflection.lower()
    assert "ai" in reflection.lower()


def test_current_docs_use_613_coding_package_names() -> None:
    current = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "docs/deployment.md", "AGENTS.md")
    )
    assert "613-coding web" not in current
    assert "coding-harness" not in current
    assert "src/coding_harness" not in current
