from __future__ import annotations

import subprocess
from pathlib import Path

from coding_harness.adapters.orchestration.integration_workspace import IntegrationWorkspace
from coding_harness.application.artifact_integrator import ArtifactIntegrator
from coding_harness.domain.models import FeedbackKind
from coding_harness.domain.sandbox import WorkArtifact


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "main.py").write_text("print('before')\n")
    subprocess.run(["git", "-C", str(repo), "add", "main.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    return repo


def _patch(old: str = "before", new: str = "after") -> str:
    return (
        "diff --git a/main.py b/main.py\n"
        "--- a/main.py\n"
        "+++ b/main.py\n"
        "@@ -1 +1 @@\n"
        f"-print('{old}')\n+print('{new}')\n"
    )


def test_integrator_applies_clean_patch_without_overwrite(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workspace = IntegrationWorkspace(repo, declared_write_set=("main.py",))

    result = ArtifactIntegrator().apply(
        WorkArtifact(patch=_patch(), changed_files=("main.py",)), workspace
    )

    assert result.applied is True
    assert result.conflict is False
    assert (repo / "main.py").read_text() == "print('after')\n"


def test_integrator_rejects_artifact_path_outside_allowlist(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workspace = IntegrationWorkspace(repo, declared_write_set=("main.py",))

    result = ArtifactIntegrator().apply(
        WorkArtifact(patch=_patch(), changed_files=("secret.txt",)), workspace
    )

    assert result.applied is False
    assert result.feedback[0].kind is FeedbackKind.POLICY_BLOCKED


def test_integrator_rejects_patch_paths_that_disagree_with_artifact_metadata(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workspace = IntegrationWorkspace(repo, declared_write_set=("main.py",))
    artifact = WorkArtifact(
        patch=_patch().replace("a/main.py b/main.py", "a/secret.py b/secret.py"),
        changed_files=("main.py",),
    )

    result = ArtifactIntegrator().apply(artifact, workspace)

    assert result.applied is False
    assert result.feedback[0].kind is FeedbackKind.POLICY_BLOCKED
    assert (repo / "main.py").read_text() == "print('before')\n"


def test_integrator_classifies_conflict_and_limits_replay_to_one_attempt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workspace = IntegrationWorkspace(repo, declared_write_set=("main.py",))
    (repo / "main.py").write_text("print('local')\n")
    artifact = WorkArtifact(patch=_patch(), changed_files=("main.py",))
    integrator = ArtifactIntegrator()

    first = integrator.apply(artifact, workspace)
    replay = integrator.replay_conflict(artifact, workspace)

    assert first.conflict is True
    assert first.replay_required is True
    assert replay.conflict is True
    assert replay.replay_required is False
    assert (repo / "main.py").read_text() == "print('local')\n"


def test_integrator_validation_handoff_is_deterministic(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    workspace = IntegrationWorkspace(repo, declared_write_set=("main.py",))

    assert ArtifactIntegrator().validate(workspace) == ()
