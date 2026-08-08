from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_readme_and_deployment_cover_acquisition_security_and_limits() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    deployment = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")
    text = f"{readme}\n{deployment}"
    for required in ("uv sync", "uv build", "Docker", "keyring", ".env", "public", "SQLite", "LanceDB", "GitLab CI", "limitations"):
        assert required.lower() in text.lower()
    assert "unverified" in deployment.lower()


def test_docs_do_not_claim_a_deployed_url_without_evidence() -> None:
    deployment = (ROOT / "docs/deployment.md").read_text(encoding="utf-8").lower()
    assert "deployed url: not verified" in deployment


def test_reflection_is_explicitly_student_authored_boundary() -> None:
    reflection = (ROOT / "REFLECTION.md").read_text(encoding="utf-8")
    assert "student-authored" in reflection.lower()
    assert "ai" in reflection.lower()
