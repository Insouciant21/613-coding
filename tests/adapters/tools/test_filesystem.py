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
