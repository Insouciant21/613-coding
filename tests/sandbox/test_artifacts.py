from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from coding_harness.adapters.sandbox.artifacts import ArtifactExporter
from coding_harness.adapters.sandbox.workspace import WorkspaceManager


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


def test_collect_returns_deterministic_text_diff_and_changed_files(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces", declared_write_set=("main.py", "new.txt"))
    workspace = manager.create(source, "run", "worker")
    (workspace.path / "main.py").write_text("print('after')\n")
    (workspace.path / "new.txt").write_text("new\n")
    exporter = ArtifactExporter()

    first = exporter.collect(workspace, workspace.baseline)
    second = exporter.collect(workspace, workspace.baseline)

    assert first == second
    assert first.changed_files == ("main.py", "new.txt")
    assert "--- a/main.py" in first.patch
    assert "+++ b/main.py" in first.patch
    assert "new file mode" in first.patch
    manager.cleanup(workspace)


def test_collect_honors_explicit_empty_baseline(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces", declared_write_set=("main.py",))
    workspace = manager.create(source, "run", "worker")

    artifact = ArtifactExporter().collect(workspace, {})

    assert artifact.changed_files == ("main.py",)
    assert "new file mode" in artifact.patch
    manager.cleanup(workspace)


def test_collect_exports_mode_only_changes(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces", declared_write_set=("main.py",))
    workspace = manager.create(source, "run", "worker")
    (workspace.path / "main.py").chmod(0o755)

    artifact = ArtifactExporter().collect(workspace, workspace.baseline)

    assert artifact.changed_files == ("main.py",)
    assert "old mode 100644" in artifact.patch
    assert "new mode 100755" in artifact.patch
    manager.cleanup(workspace)


def test_collect_summarizes_binary_changes_without_exporting_bytes(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces", declared_write_set=("blob.bin",))
    workspace = manager.create(source, "run", "worker")
    (workspace.path / "blob.bin").write_bytes(b"\x00\xff\x00")

    artifact = ArtifactExporter().collect(workspace, workspace.baseline)

    assert artifact.changed_files == ("blob.bin",)
    assert "blob.bin" in artifact.summary
    assert "Binary" in artifact.patch
    assert "\x00" not in artifact.patch
    manager.cleanup(workspace)


def test_collect_redacts_secrets_from_patch_and_metadata(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces", declared_write_set=("secret.txt",))
    workspace = manager.create(source, "run", "worker")
    (workspace.path / "secret.txt").write_text("api_key=sk-123456789ABC\n")

    artifact = ArtifactExporter(
        verification_evidence=({"log": "Bearer abc.def.ghi"},),
        assumptions=("password=topsecret",),
    ).collect(workspace, workspace.baseline)

    rendered = artifact.model_dump_json()
    assert "sk-123456789ABC" not in rendered
    assert "Bearer abc.def.ghi" not in rendered
    assert "topsecret" not in rendered
    assert "[REDACTED]" in rendered
    manager.cleanup(workspace)


def test_collect_rejects_new_symlink_escaping_workspace(tmp_path: Path) -> None:
    source = _repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces", declared_write_set=("escape",))
    workspace = manager.create(source, "run", "worker")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (workspace.path / "escape").symlink_to(outside)

    try:
        with pytest.raises(ValueError, match="symlink"):
            ArtifactExporter().collect(workspace, workspace.baseline)
    finally:
        manager.cleanup(workspace)
    assert not workspace.path.exists()
