from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from coding613.adapters.tools.filesystem import (
    FilesystemTools,
    PathOutsideRepositoryError,
)
from coding613.adapters.tools.patch import (
    InvalidPatchError,
    PatchCommitError,
    PatchConflictError,
    PatchLimitError,
    PatchOperation,
    PreparedChange,
    UnsafePatchPathError,
    prepare_patch,
)

UPDATE = """--- a/src/value.py
+++ b/src/value.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""

ADD = """--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+created
"""

DELETE = """--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-removed
"""


def test_prepare_patch_updates_matching_text() -> None:
    plan = prepare_patch(UPDATE, lambda path: "VALUE = 1\n")
    assert plan.changes == (
        PreparedChange(
            path="src/value.py",
            operation=PatchOperation.UPDATE,
            before="VALUE = 1\n",
            after="VALUE = 2\n",
        ),
    )


def test_prepare_patch_supports_add_and_delete() -> None:
    values = {"old.txt": "removed\n"}
    def read(path: str) -> str:
        if path not in values:
            raise FileNotFoundError(path)
        return values[path]

    added = prepare_patch(ADD, read)
    deleted = prepare_patch(DELETE, read)
    assert added.changes[0] == PreparedChange(
        path="new.txt",
        operation=PatchOperation.ADD,
        before=None,
        after="created\n",
    )
    assert deleted.changes[0] == PreparedChange(
        path="old.txt",
        operation=PatchOperation.DELETE,
        before="removed\n",
        after=None,
    )


def test_prepared_values_are_immutable() -> None:
    plan = prepare_patch(UPDATE, lambda path: "VALUE = 1\n")
    with pytest.raises(FrozenInstanceError):
        plan.changes[0].path = "other.py"  # type: ignore[misc]


@pytest.mark.parametrize(
    "patch",
    [
        UPDATE.replace("src/value.py", "/etc/passwd"),
        UPDATE.replace("src/value.py", "../outside"),
        UPDATE.replace("src/value.py", ".git/config"),
        UPDATE.replace("src/value.py", ".613-coding/state.sqlite"),
        UPDATE.replace("src/value.py", "src/./value.py"),
        UPDATE.replace("src/value.py", "src//value.py"),
        UPDATE.replace("src/value.py", "src/value.py\0"),
    ],
)
def test_prepare_patch_rejects_unsafe_paths(patch: str) -> None:
    with pytest.raises(UnsafePatchPathError):
        prepare_patch(patch, lambda path: "VALUE = 1\n")


def test_prepare_patch_rejects_source_target_mismatch() -> None:
    patch = UPDATE.replace("+++ b/src/value.py", "+++ b/src/other.py")
    with pytest.raises(InvalidPatchError):
        prepare_patch(patch, lambda path: "VALUE = 1\n")


def test_prepare_patch_validates_all_headers_before_calling_reader() -> None:
    mismatch = UPDATE.replace("src/value.py", "src/other.py").replace(
        "+++ b/src/other.py", "+++ b/src/mismatch.py"
    )
    calls: list[str] = []

    def read(path: str) -> str:
        calls.append(path)
        return "VALUE = 1\n"

    with pytest.raises(InvalidPatchError):
        prepare_patch(UPDATE + mismatch, read)

    assert calls == []


def test_prepare_patch_rejects_duplicate_targets() -> None:
    with pytest.raises(InvalidPatchError):
        prepare_patch(UPDATE + UPDATE, lambda path: "VALUE = 1\n")


@pytest.mark.parametrize(
    "patch",
    [
        "GIT binary patch\nliteral 3\nabc\n",
        "diff --git a/a b/a\nold mode 100644\nnew mode 100755\n",
        "--- a/value.py\n+++ b/value.py\n@@ malformed\n-value\n+new\n",
    ],
)
def test_prepare_patch_rejects_unsupported_or_malformed_patch(patch: str) -> None:
    with pytest.raises(InvalidPatchError):
        prepare_patch(patch, lambda path: "value\n")


def test_prepare_patch_rejects_hunk_conflict() -> None:
    with pytest.raises(PatchConflictError):
        prepare_patch(UPDATE, lambda path: "VALUE = 9\n")


def test_prepare_patch_requires_empty_source_for_add() -> None:
    with pytest.raises(PatchConflictError):
        prepare_patch(ADD, lambda path: "already exists\n")


def test_prepare_patch_requires_complete_source_for_delete() -> None:
    with pytest.raises(PatchConflictError):
        prepare_patch(DELETE, lambda path: "removed\nextra\n")


def test_prepare_patch_counts_utf8_bytes_and_aggregate_size() -> None:
    with pytest.raises(PatchLimitError):
        prepare_patch(UPDATE, lambda path: "VALUE = 1\n", max_patch_bytes=10)
    unicode_patch = UPDATE.replace("VALUE = 2", "VALUE = é")
    with pytest.raises(PatchLimitError):
        prepare_patch(
            unicode_patch,
            lambda path: "VALUE = 1\n",
            max_patch_bytes=len(unicode_patch),
        )


def test_prepare_patch_rejects_surrogate_encoding() -> None:
    with pytest.raises(PatchLimitError):
        prepare_patch(chr(0xDFFF), lambda path: "")


def test_prepare_patch_wraps_invalid_utf8_from_reader() -> None:
    with pytest.raises(PatchLimitError):
        prepare_patch(UPDATE, lambda path: chr(0xDFFF))


def test_prepare_patch_wraps_invalid_utf8_for_existing_add_target() -> None:
    with pytest.raises(PatchLimitError):
        prepare_patch(ADD, lambda path: chr(0xDFFF))


def test_apply_patch_adds_updates_and_deletes_in_order(tmp_path: Path) -> None:
    (tmp_path / "update.txt").write_text("before\n", encoding="utf-8")
    (tmp_path / "delete.txt").write_text("remove\n", encoding="utf-8")
    patch = """--- /dev/null
+++ b/new/nested.txt
@@ -0,0 +1 @@
+created
--- a/update.txt
+++ b/update.txt
@@ -1 +1 @@
-before
+after
--- a/delete.txt
+++ /dev/null
@@ -1 +0,0 @@
-remove
"""

    result = FilesystemTools(tmp_path).apply_patch(patch)

    assert (tmp_path / "new/nested.txt").read_text(encoding="utf-8") == "created\n"
    assert (tmp_path / "update.txt").read_text(encoding="utf-8") == "after\n"
    assert not (tmp_path / "delete.txt").exists()
    assert result.added == 1
    assert result.updated == 1
    assert result.deleted == 1
    assert result.changed_files == ("delete.txt", "new/nested.txt", "update.txt")


def test_apply_patch_preflights_every_file_before_mutation(tmp_path: Path) -> None:
    (tmp_path / "first.txt").write_text("one\n", encoding="utf-8")
    (tmp_path / "second.txt").write_text("unexpected\n", encoding="utf-8")
    patch = """--- a/first.txt
+++ b/first.txt
@@ -1 +1 @@
-one
+changed
--- a/second.txt
+++ b/second.txt
@@ -1 +1 @@
-two
+changed
"""

    with pytest.raises(PatchConflictError):
        FilesystemTools(tmp_path).apply_patch(patch)

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == "one\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "unexpected\n"


def test_apply_patch_rejects_symlink_parent_without_touching_outside(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"patch-outside-{tmp_path.name}"
    outside.mkdir()
    outside_target = outside / "target.txt"
    outside_target.write_text("outside\n", encoding="utf-8")
    os.symlink(outside, tmp_path / "alias")
    patch = """--- /dev/null
+++ b/alias/new.txt
@@ -0,0 +1 @@
+created
"""

    with pytest.raises(PathOutsideRepositoryError):
        FilesystemTools(tmp_path).apply_patch(patch)

    assert outside_target.read_text(encoding="utf-8") == "outside\n"
    assert not (outside / "new.txt").exists()


def test_apply_patch_reports_only_committed_files_and_cleans_temps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "a.txt").write_text("old-a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("old-b\n", encoding="utf-8")
    patch = """--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-old-a
+new-a
--- a/b.txt
+++ b/b.txt
@@ -1 +1 @@
-old-b
+new-b
"""
    real_replace = os.replace
    calls = 0

    def fail_second_replace(
        source: str,
        target: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        real_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "replace", fail_second_replace)

    with pytest.raises(PatchCommitError) as raised:
        FilesystemTools(tmp_path).apply_patch(patch)

    assert raised.value.changed_files == ("a.txt",)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new-a\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "old-b\n"
    assert not [path for path in tmp_path.iterdir() if path.name.startswith(".")]


def test_apply_patch_reports_replace_committed_before_parent_close_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "value.txt"
    target.write_text("old\n", encoding="utf-8")
    patch = """--- a/value.txt
+++ b/value.txt
@@ -1 +1 @@
-old
+new
"""
    real_replace = os.replace
    real_close = os.close
    replaced = False

    def mark_replace(*args: object, **kwargs: object) -> None:
        nonlocal replaced
        real_replace(*args, **kwargs)  # type: ignore[arg-type]
        replaced = True

    def fail_close_after_replace(descriptor: int) -> None:
        nonlocal replaced
        real_close(descriptor)
        if replaced:
            replaced = False
            raise OSError("close failed")

    monkeypatch.setattr(os, "replace", mark_replace)
    monkeypatch.setattr(os, "close", fail_close_after_replace)

    with pytest.raises(PatchCommitError) as raised:
        FilesystemTools(tmp_path).apply_patch(patch)

    assert raised.value.changed_files == ("value.txt",)
    assert target.read_text(encoding="utf-8") == "new\n"


def test_apply_patch_reports_delete_committed_before_parent_close_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "gone.txt"
    target.write_text("remove\n", encoding="utf-8")
    patch = """--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-remove
"""
    real_unlink = os.unlink
    real_close = os.close
    unlinked = False

    def mark_unlink(path: str, *, dir_fd: int | None = None) -> None:
        nonlocal unlinked
        real_unlink(path, dir_fd=dir_fd)
        unlinked = True

    def fail_close_after_unlink(descriptor: int) -> None:
        nonlocal unlinked
        real_close(descriptor)
        if unlinked:
            unlinked = False
            raise OSError("close failed")

    monkeypatch.setattr(os, "unlink", mark_unlink)
    monkeypatch.setattr(os, "close", fail_close_after_unlink)

    with pytest.raises(PatchCommitError) as raised:
        FilesystemTools(tmp_path).apply_patch(patch)

    assert raised.value.changed_files == ("gone.txt",)
    assert not target.exists()
