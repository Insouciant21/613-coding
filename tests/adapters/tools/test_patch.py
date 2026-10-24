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

CODEX_UPDATE = """*** Begin Patch
*** Update File: src/value.py
@@
-VALUE = 1
+VALUE = 2
*** End Patch
"""

CODEX_ADD = """*** Begin Patch
*** Add File: new.txt
+created
+second line
*** End Patch
"""

CODEX_DELETE = """*** Begin Patch
*** Delete File: old.txt
*** End Patch
"""

CODEX_MULTI_UPDATE = """*** Begin Patch
*** Update File: src/value.py
@@
-VALUE = 1
+VALUE = 2
+inserted
@@
-NEXT = 1
+NEXT = 2
*** End Patch
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


def test_prepare_patch_accepts_codex_update_format() -> None:
    plan = prepare_patch(CODEX_UPDATE, lambda path: "VALUE = 1\n")

    assert plan.changes[0].path == "src/value.py"
    assert plan.changes[0].after == "VALUE = 2\n"


def test_prepare_patch_applies_codex_update_after_context_offset() -> None:
    source = "header 1\nheader 2\nVALUE = 1\n"
    plan = prepare_patch(CODEX_UPDATE, lambda path: source)

    assert plan.changes[0].after == "header 1\nheader 2\nVALUE = 2\n"


def test_prepare_patch_recovers_a_stale_standard_hunk_offset_by_unique_context() -> None:
    patch = """--- a/src/value.py
+++ b/src/value.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""

    plan = prepare_patch(patch, lambda path: "header\nVALUE = 1\n")

    assert plan.changes[0].after == "header\nVALUE = 2\n"


def test_prepare_patch_accepts_codex_add_without_hunk_header() -> None:
    plan = prepare_patch(CODEX_ADD, lambda path: (_ for _ in ()).throw(FileNotFoundError(path)))

    assert plan.changes[0] == PreparedChange(
        path="new.txt",
        operation=PatchOperation.ADD,
        before=None,
        after="created\nsecond line\n",
    )


def test_prepare_patch_accepts_codex_delete_without_hunk_header() -> None:
    plan = prepare_patch(CODEX_DELETE, lambda path: "removed\n")

    assert plan.changes[0] == PreparedChange(
        path="old.txt",
        operation=PatchOperation.DELETE,
        before="removed\n",
        after=None,
    )


def test_prepare_patch_applies_multiple_codex_hunks_against_original_source() -> None:
    source = "VALUE = 1\nNEXT = 1\n"
    plan = prepare_patch(CODEX_MULTI_UPDATE, lambda path: source)

    assert plan.changes[0].after == "VALUE = 2\ninserted\nNEXT = 2\n"


def test_prepare_patch_rejects_repeated_codex_addition() -> None:
    patch = """*** Begin Patch
*** Update File: src/value.py
@@
+VALUE = 1
*** End Patch
"""

    with pytest.raises(PatchConflictError, match="addition already exists"):
        prepare_patch(patch, lambda path: "VALUE = 1\n")


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
    with pytest.raises(PatchConflictError, match="expected 'VALUE = 1"):
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


def test_apply_patch_pins_repository_root_descriptor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "a.txt").write_text("old-a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("old-b\n", encoding="utf-8")
    replacement = tmp_path.parent / "replacement-root"
    replacement.mkdir()
    (replacement / "b.txt").write_text("outside\n", encoding="utf-8")
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
    real_write = FilesystemTools._write_patch_text
    calls = 0

    def swap_root(self: FilesystemTools, path: Path, content: str, on_commit: object, **kwargs: object) -> None:
        nonlocal calls
        real_write(self, path, content, on_commit, **kwargs)  # type: ignore[arg-type]
        calls += 1
        if calls == 1:
            parked = tmp_path.parent / "parked-original"
            tmp_path.rename(parked)
            replacement.rename(tmp_path)

    monkeypatch.setattr(FilesystemTools, "_write_patch_text", swap_root)
    result = FilesystemTools(tmp_path).apply_patch(patch)

    assert result.changed_files == ("a.txt", "b.txt")
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "outside\n"
    assert (tmp_path.parent / "parked-original" / "b.txt").read_text(encoding="utf-8") == "new-b\n"


def test_apply_patch_accepts_standard_git_metadata_wrapper(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")

    patch = """diff --git a/a.txt b/a.txt
index 3e75765..9daeafb 100644
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-old
+new
"""

    result = FilesystemTools(tmp_path).apply_patch(patch)

    assert result.changed_files == ("a.txt",)
    assert target.read_text(encoding="utf-8") == "new\n"


def test_apply_patch_reports_filesystem_errors_after_partial_commit(
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
    real_write = FilesystemTools._write_patch_text
    calls = 0

    def fail_second(self: FilesystemTools, path: Path, content: str, on_commit: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PathOutsideRepositoryError("simulated late path failure")
        real_write(self, path, content, on_commit, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(FilesystemTools, "_write_patch_text", fail_second)
    with pytest.raises(PatchCommitError) as raised:
        FilesystemTools(tmp_path).apply_patch(patch)

    assert raised.value.changed_files == ("a.txt",)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new-a\n"


def test_prepare_patch_rejects_trailing_non_diff_content() -> None:
    patch = """--- a/value.txt
+++ b/value.txt
@@ -1 +1 @@
-old
+new
trailing-junk
"""

    with pytest.raises(InvalidPatchError):
        prepare_patch(patch, lambda path: "old\n")


def test_prepare_patch_rejects_target_hunk_length_mismatch() -> None:
    patch = """--- a/value.txt
+++ b/value.txt
@@ -1 +1 +2 @@
-old
+new
"""

    with pytest.raises(InvalidPatchError):
        prepare_patch(patch, lambda path: "old\n")


def test_apply_patch_reports_root_close_failure_after_commit(
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
    root_fds: list[int] = []
    real_open_root = FilesystemTools._open_root_descriptor
    real_close = os.close

    def capture_root(self: FilesystemTools) -> int:
        descriptor = real_open_root(self)
        root_fds.append(descriptor)
        return descriptor

    def fail_root_close(descriptor: int) -> None:
        real_close(descriptor)
        if root_fds and descriptor == root_fds[0]:
            raise OSError("root close failed")

    monkeypatch.setattr(FilesystemTools, "_open_root_descriptor", capture_root)
    monkeypatch.setattr(os, "close", fail_root_close)

    with pytest.raises(PatchCommitError) as raised:
        FilesystemTools(tmp_path).apply_patch(patch)

    assert raised.value.changed_files == ("value.txt",)
    assert target.read_text(encoding="utf-8") == "new\n"


@pytest.mark.parametrize("patch", [
    "*** Begin Patch\n*** Add File: first.txt\n+first\n*** Add File: second.txt\n+second\n*** End Patch\n",
    (
        "--- /dev/null\n+++ b/first.txt\n@@ -0,0 +1 @@\n+first\n"
        "--- /dev/null\n+++ b/second.txt\n@@ -0,0 +1 @@\n+second\n"
    ),
])
def test_patch_can_create_two_files_in_one_action(tmp_path: Path, patch: str) -> None:
    result = FilesystemTools(tmp_path).apply_patch(patch)
    assert result.added == 2
    assert (tmp_path / "first.txt").read_text() == "first\n"
    assert (tmp_path / "second.txt").read_text() == "second\n"


def test_prepare_patch_accepts_deletion_of_dash_prefixed_lines() -> None:
    # A hunk line for deleted content "-- sql comment" is itself prefixed
    # "--- " in the patch; it must not be mistaken for a new file header.
    source = "keep\n-- sql comment\nremoved\nkeep2\n"
    patch = (
        "--- a/notes.sql\n"
        "+++ b/notes.sql\n"
        "@@ -1,4 +1,2 @@\n"
        " keep\n"
        "--- sql comment\n"
        "-removed\n"
        " keep2\n"
    )

    plan = prepare_patch(patch, lambda path: source)

    assert plan.changes == (
        PreparedChange(
            path="notes.sql",
            operation=PatchOperation.UPDATE,
            before=source,
            after="keep\nkeep2\n",
        ),
    )


def test_prepare_patch_rejects_header_without_target_line() -> None:
    patch = "--- a/notes.sql\n+++ b/notes.sql\n@@ -1 +1 @@\n-old\n+new\n--- a/other.sql\n"

    with pytest.raises(InvalidPatchError, match="unified file header is incomplete"):
        prepare_patch(patch, lambda path: "old\n")
