from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from coding613.adapters.tools.patch import (
    InvalidPatchError,
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
