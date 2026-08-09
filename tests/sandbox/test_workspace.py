from __future__ import annotations

import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from coding613.adapters.sandbox.workspace import (
    Workspace,
    WorkspaceBaseline,
    WorkspaceManager,
    WorkspacePathError,
    WriteSetViolation,
    normalize_write_set,
)


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "tracked.txt").write_text("tracked\n")
    (repo / "ignored.txt").write_text("ignored\n")
    (repo / "untracked.txt").write_text("untracked\n")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    return repo


def test_create_copies_git_ignored_and_untracked_files_with_canonical_paths(tmp_path: Path) -> None:
    source = _git_repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces")

    workspace = manager.create(source, "run/1", "worker/1")

    assert workspace.path.is_absolute()
    assert workspace.path == workspace.path.resolve()
    assert (workspace.path / ".git").exists()
    assert (workspace.path / "ignored.txt").read_text() == "ignored\n"
    assert (workspace.path / "untracked.txt").read_text() == "untracked\n"
    temporary_path = workspace.path.parent
    manager.cleanup(workspace)
    manager.cleanup(workspace)
    assert not workspace.path.exists()
    assert not temporary_path.exists()


def test_create_rejects_source_symlink_escape_and_cleans_partial_workspace(tmp_path: Path) -> None:
    source = _git_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (source / "escape.txt").symlink_to(outside)
    manager = WorkspaceManager(tmp_path / "workspaces")

    with pytest.raises(WorkspacePathError, match="symlink"):
        manager.create(source, "run", "worker")

    workspace_dir = tmp_path / "workspaces"
    assert not any(workspace_dir.iterdir()) if workspace_dir.exists() else True


def test_normalize_write_set_preserves_dotfile_names() -> None:
    assert normalize_write_set(("./.hidden", ".env")) == (".env", ".hidden")


def test_declared_write_set_is_enforced_during_artifact_collection(tmp_path: Path) -> None:
    source = _git_repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces", declared_write_set=("tracked.txt",))
    workspace = manager.create(source, "run", "worker")
    (workspace.path / "tracked.txt").write_text("changed\n")
    (workspace.path / "untracked.txt").write_text("changed untracked\n")

    from coding613.adapters.sandbox.artifacts import ArtifactExporter

    with pytest.raises(WriteSetViolation, match="untracked.txt"):
        ArtifactExporter(manager).collect(workspace, workspace.baseline)
    manager.cleanup(workspace)


def test_empty_declared_write_set_rejects_all_changes(tmp_path: Path) -> None:
    source = _git_repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces")
    workspace = manager.create(source, "run", "worker")
    (workspace.path / "new.txt").write_text("changed\n")

    from coding613.adapters.sandbox.artifacts import ArtifactExporter

    try:
        with pytest.raises(WriteSetViolation, match="new.txt"):
            ArtifactExporter(manager).collect(workspace, workspace.baseline)
    finally:
        manager.cleanup(workspace)


def test_cleanup_refuses_workspace_not_created_by_manager(tmp_path: Path) -> None:
    foreign_path = tmp_path / "foreign"
    foreign_path.mkdir()
    (foreign_path / "keep.txt").write_text("keep")
    manager = WorkspaceManager()
    foreign = Workspace(
        path=foreign_path,
        source_repo=tmp_path,
        run_id="run",
        worker_id="worker",
        declared_write_set=(),
        baseline=WorkspaceBaseline({}),
    )

    with pytest.raises(WorkspacePathError, match="created by manager"):
        manager.cleanup(foreign)
    assert (foreign_path / "keep.txt").exists()


def test_cleanup_refuses_forged_workspace_with_owned_path(tmp_path: Path) -> None:
    source = _git_repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces")
    workspace = manager.create(source, "run", "worker")
    forged = Workspace(
        path=workspace.path,
        source_repo=workspace.source_repo,
        run_id=workspace.run_id,
        worker_id=workspace.worker_id,
        declared_write_set=workspace.declared_write_set,
        baseline=workspace.baseline,
    )

    with pytest.raises(WorkspacePathError, match="created by manager"):
        manager.cleanup(forged)
    assert workspace.path.exists()
    manager.cleanup(workspace)


def test_workspace_and_baseline_are_immutable(tmp_path: Path) -> None:
    source = _git_repo(tmp_path)
    manager = WorkspaceManager(tmp_path / "workspaces", declared_write_set=("tracked.txt",))
    workspace = manager.create(source, "run", "worker")

    with pytest.raises(FrozenInstanceError):
        workspace.declared_write_set = ("**",)
    with pytest.raises(TypeError):
        workspace.baseline.files["tracked.txt"] = workspace.baseline.files["tracked.txt"]

    manager.cleanup(workspace)
