from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from coding613.adapters.tools.filesystem import (
    FilesystemTools,
    FileTooLargeError,
    InvalidUtf8Error,
    PathOutsideRepositoryError,
)
from coding613.adapters.tools.git import GitTools


def test_filesystem_lists_searches_reads_and_edits_deterministically(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("needle on b\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("needle on a\n", encoding="utf-8")
    tools = FilesystemTools(tmp_path)
    assert tools.list_files() == ["a.txt", "b.txt"]
    assert [(match.path, match.line_number) for match in tools.search_files("needle")] == [
        ("a.txt", 1),
        ("b.txt", 1),
    ]
    assert tools.read_file("a.txt") == "needle on a\n"
    tools.edit_file("new/file.txt", "created\n")
    assert (tmp_path / "new/file.txt").read_text(encoding="utf-8") == "created\n"
    tools.delete_file("new/file.txt")
    assert not (tmp_path / "new/file.txt").exists()


@pytest.mark.parametrize(
    "directory",
    [
        ".613-coding",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "node_modules",
    ],
)
def test_filesystem_omits_generated_directory_trees(
    tmp_path: Path, directory: str
) -> None:
    generated = tmp_path / directory
    generated.mkdir()
    (generated / "large-generated-file.txt").write_text("generated\n", encoding="utf-8")
    (tmp_path / "source.txt").write_text("source\n", encoding="utf-8")

    assert FilesystemTools(tmp_path).list_files() == ["source.txt"]


@pytest.mark.parametrize("path", ["../outside.txt", "/tmp/outside.txt"])
def test_filesystem_rejects_path_escape(tmp_path: Path, path: str) -> None:
    with pytest.raises(PathOutsideRepositoryError):
        FilesystemTools(tmp_path).read_file(path)
    with pytest.raises(PathOutsideRepositoryError):
        FilesystemTools(tmp_path).delete_file(path)


def test_filesystem_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    os.symlink(outside, tmp_path / "link.txt")
    with pytest.raises(PathOutsideRepositoryError):
        FilesystemTools(tmp_path).read_file("link.txt")


@pytest.mark.parametrize("target_location", ["inside", "outside"])
def test_filesystem_deletes_symlink_without_deleting_target(
    tmp_path: Path, target_location: str
) -> None:
    target_root = tmp_path if target_location == "inside" else tmp_path.parent
    target = target_root / f"{target_location}-delete-target.txt"
    target.write_text("keep\n", encoding="utf-8")
    link = tmp_path / f"{target_location}-delete-link.txt"
    os.symlink(target, link)

    FilesystemTools(tmp_path).delete_file(link.name)

    assert not link.exists()
    assert not link.is_symlink()
    assert target.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.parametrize("target_location", ["inside", "outside"])
def test_filesystem_rejects_symlink_in_delete_parent_path(
    tmp_path: Path, target_location: str
) -> None:
    target_root = tmp_path if target_location == "inside" else tmp_path.parent
    target_directory = target_root / f"{target_location}-delete-directory"
    target_directory.mkdir(exist_ok=True)
    target = target_directory / "id_rsa"
    target.write_text("keep\n", encoding="utf-8")
    os.symlink(target_directory, tmp_path / "alias")

    with pytest.raises(PathOutsideRepositoryError):
        FilesystemTools(tmp_path).delete_file("alias/id_rsa")

    assert target.read_text(encoding="utf-8") == "keep\n"


def test_delete_file_is_anchored_when_parent_path_is_swapped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    safe = tmp_path / "safe"
    safe.mkdir()
    (safe / "victim.txt").write_text("inside\n", encoding="utf-8")
    outside = tmp_path.parent / f"outside-{tmp_path.name}"
    outside.mkdir()
    outside_victim = outside / "victim.txt"
    outside_victim.write_text("outside\n", encoding="utf-8")
    parked = tmp_path / "parked"
    real_unlink = os.unlink
    raced = False

    def swap_then_unlink(path: str, *, dir_fd: int | None = None) -> None:
        nonlocal raced
        if not raced:
            raced = True
            safe.rename(parked)
            os.symlink(outside, safe)
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", swap_then_unlink)
    FilesystemTools(tmp_path).delete_file("safe/victim.txt")

    assert not (parked / "victim.txt").exists()
    assert outside_victim.read_text(encoding="utf-8") == "outside\n"


def test_filesystem_enforces_size_and_utf8_limits(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("12345", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"\xff")
    tools = FilesystemTools(tmp_path, max_file_bytes=4)
    with pytest.raises(FileTooLargeError):
        tools.read_file("large.txt")
    with pytest.raises(InvalidUtf8Error):
        tools.read_file("binary.dat")


def test_git_diff_returns_worktree_patch(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)
    tracked.write_text("after\n", encoding="utf-8")
    patch = GitTools(tmp_path).diff()
    assert "-before" in patch
    assert "+after" in patch
