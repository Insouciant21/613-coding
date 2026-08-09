"""Strict, preflight-only unified diff parsing for repository mutations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, cast

from unidiff import PatchSet  # type: ignore[import-untyped]


class PatchError(ValueError):
    """Base class for stable patch validation errors."""


class InvalidPatchError(PatchError):
    """The patch is not a supported unified diff."""


class PatchConflictError(PatchError):
    """The patch does not match the current repository content."""


class UnsafePatchPathError(PatchError):
    """A patch target is outside the repository mutation boundary."""


class PatchLimitError(PatchError):
    """The patch or resulting change exceeds the configured size limit."""


class PatchOperation(StrEnum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class PreparedChange:
    path: str
    operation: PatchOperation
    before: str | None
    after: str | None


@dataclass(frozen=True, slots=True)
class PreparedPatch:
    changes: tuple[PreparedChange, ...]


_PROTECTED_ROOTS = frozenset({".git", ".613-coding"})
_UNSUPPORTED_MARKERS = (
    "GIT binary patch",
    "Binary files ",
    "old mode ",
    "new mode ",
    "new file mode ",
    "deleted file mode ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
    "diff --git ",
    "index ",
)


def prepare_patch(
    patch: str,
    reader: Callable[[str], str],
    *,
    max_patch_bytes: int = 1_000_000,
) -> PreparedPatch:
    """Parse and preflight a supported UTF-8 unified diff without mutating files."""

    if max_patch_bytes < 1:
        raise PatchLimitError("max_patch_bytes must be positive")
    try:
        patch_bytes = patch.encode("utf-8")
    except UnicodeEncodeError as error:
        raise PatchLimitError("patch must be valid UTF-8") from error
    if len(patch_bytes) > max_patch_bytes:
        raise PatchLimitError("patch exceeds configured byte limit")
    if "\x00" in patch:
        header_nul = any(
            line.startswith(("--- ", "+++ ")) and "\x00" in line
            for line in patch.splitlines()
        )
        if header_nul:
            raise UnsafePatchPathError("patch path contains NUL")
        raise InvalidPatchError("patch contains NUL")
    if any(line.startswith(_UNSUPPORTED_MARKERS) for line in patch.splitlines()):
        raise InvalidPatchError("patch contains unsupported metadata")
    if not patch.startswith("--- "):
        raise InvalidPatchError("patch must start with a unified file header")
    _preflight_header_pairs(patch)

    try:
        files = PatchSet(patch)
    except Exception as error:
        raise InvalidPatchError("malformed unified patch") from error
    if not files:
        raise InvalidPatchError("patch contains no file changes")

    changes: list[PreparedChange] = []
    targets: set[str] = set()
    aggregate_bytes = 0
    for patched_file in files:
        source = _header_path(str(patched_file.source_file))
        target = _header_path(str(patched_file.target_file))
        operation, path = _operation_path(source, target)
        if path in targets:
            raise InvalidPatchError(f"duplicate patch target: {path}")
        targets.add(path)

        before: str | None = None
        if operation is PatchOperation.ADD:
            try:
                existing = reader(path)
            except FileNotFoundError:
                before = None
            else:
                if not isinstance(existing, str):
                    raise InvalidPatchError("reader must return text")
                _utf8_size(existing, "existing add target")
                raise PatchConflictError(f"add target already exists: {path}")
        else:
            try:
                before = reader(path)
            except FileNotFoundError as error:
                raise PatchConflictError(f"missing patch source: {path}") from error
            if not isinstance(before, str):
                raise InvalidPatchError("reader must return text")
            _utf8_size(before, "patch source")
        after: str | None = _apply_hunks(patched_file, before, operation, path)
        if operation is PatchOperation.DELETE:
            after = None
        if operation is PatchOperation.ADD:
            before = None
        aggregate_bytes += len(path.encode("utf-8"))
        if before is not None:
            aggregate_bytes += _utf8_size(before, "patch source")
        if after is not None:
            aggregate_bytes += _utf8_size(after, "change text")
        if aggregate_bytes > max_patch_bytes:
            raise PatchLimitError("aggregate patch data exceeds configured byte limit")
        changes.append(PreparedChange(path, operation, before, after))
    return PreparedPatch(tuple(changes))


def _header_path(value: str) -> str:
    path = value.split("\t", 1)[0].strip()
    if not path:
        raise InvalidPatchError("empty patch path")
    return path


def _preflight_header_pairs(patch: str) -> None:
    lines = patch.splitlines()
    targets: set[str] = set()
    index = 0
    found = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("--- "):
            index += 1
            continue
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise InvalidPatchError("unified file header is incomplete")
        _, path = _operation_path(
            _header_path(line[4:]),
            _header_path(lines[index + 1][4:]),
        )
        if path in targets:
            raise InvalidPatchError(f"duplicate patch target: {path}")
        targets.add(path)
        found += 1
        index += 2
    if found == 0:
        raise InvalidPatchError("patch contains no file headers")


def _operation_path(source: str, target: str) -> tuple[PatchOperation, str]:
    source_dev_null = source == "/dev/null"
    target_dev_null = target == "/dev/null"
    if source_dev_null and target_dev_null:
        raise InvalidPatchError("both patch paths cannot be /dev/null")
    if source_dev_null:
        return PatchOperation.ADD, _normalize_path(target)
    if target_dev_null:
        return PatchOperation.DELETE, _normalize_path(source)
    source_path = _normalize_path(source)
    target_path = _normalize_path(target)
    if source_path != target_path:
        raise InvalidPatchError("source and target paths differ")
    return PatchOperation.UPDATE, target_path


def _utf8_size(value: str, label: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise PatchLimitError(f"{label} must be valid UTF-8") from error


def _normalize_path(value: str) -> str:
    if "\x00" in value or value.startswith("/"):
        raise UnsafePatchPathError("patch path must be repository-relative")
    if value.startswith(("a/", "b/")):
        value = value[2:]
    if not value or value.startswith("/") or "\\" in value:
        raise UnsafePatchPathError("patch path must be POSIX relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise UnsafePatchPathError("patch path contains an unsafe component")
    if parts[0] in _PROTECTED_ROOTS:
        raise UnsafePatchPathError("patch path is protected")
    return PurePosixPath(*parts).as_posix()


def _apply_hunks(patched_file: object, source: str | None, operation: PatchOperation, path: str) -> str:
    if source is None:
        source = ""
    original = source.splitlines(keepends=True)
    if operation is PatchOperation.ADD and original:
        raise PatchConflictError(f"add target already exists: {path}")
    cursor = 0
    output: list[str] = []
    hunks: tuple[Any, ...] = tuple(cast(Any, patched_file))
    if not hunks:
        raise InvalidPatchError(f"patch contains no hunks: {path}")
    for hunk in hunks:
        source_start = int(getattr(hunk, "source_start", 0))
        start = max(source_start - 1, 0)
        if start < cursor or start > len(original):
            raise PatchConflictError(f"hunk offset is out of range: {path}")
        output.extend(original[cursor:start])
        consumed = 0
        for line in hunk:
            line_type = getattr(line, "line_type", "")
            value = str(getattr(line, "value", ""))
            if line_type in {" ", "-"}:
                if cursor >= len(original) or original[cursor] != value:
                    raise PatchConflictError(f"hunk context does not match: {path}")
                if line_type == " ":
                    output.append(value)
                cursor += 1
                consumed += 1
            elif line_type == "+":
                output.append(value)
            else:
                raise InvalidPatchError(f"unsupported hunk line: {path}")
        declared = int(getattr(hunk, "source_length", consumed))
        if declared != consumed:
            raise InvalidPatchError(f"hunk source length mismatch: {path}")
    output.extend(original[cursor:])
    if operation is PatchOperation.DELETE and cursor != len(original):
        raise PatchConflictError(f"delete patch does not consume source: {path}")
    result = "".join(output)
    try:
        result.encode("utf-8")
    except UnicodeEncodeError as error:
        raise PatchLimitError("resulting text must be valid UTF-8") from error
    return result
