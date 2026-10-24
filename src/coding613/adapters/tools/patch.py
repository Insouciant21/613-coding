"""Strict, preflight-only unified diff parsing for repository mutations."""

from __future__ import annotations

import re
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


class PatchCommitError(RuntimeError):
    """A patch failed after zero or more changes were committed."""

    def __init__(self, message: str, changed_files: tuple[str, ...]) -> None:
        super().__init__(message)
        self.changed_files = changed_files


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


@dataclass(frozen=True, slots=True)
class PatchResult:
    added: int
    updated: int
    deleted: int
    changed_files: tuple[str, ...]


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
    if patch.startswith("*** Begin Patch"):
        patch = _normalize_codex_patch(patch, reader)
    elif patch.startswith("diff --git "):
        patch = _normalize_git_metadata_wrapper(patch)
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
    file_patches = _validate_patch_lines(patch)

    try:
        # Parse files independently: repeated /dev/null sources otherwise confuse
        # unidiff when a marker-based patch creates several files at once.
        files = [item for file_patch in file_patches for item in PatchSet(file_patch)]
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


def _normalize_codex_patch(patch: str, reader: Callable[[str], str]) -> str:
    """Translate Codex's marker-based patch format into a strict unified diff."""

    lines = patch.splitlines()
    if not lines or lines[0].strip() != "*** Begin Patch":
        raise InvalidPatchError("malformed Codex patch header")
    end = len(lines) - 1
    while end >= 0 and not lines[end].strip():
        end -= 1
    if end <= 0 or lines[end].strip() != "*** End Patch":
        raise InvalidPatchError("malformed Codex patch footer")

    output: list[str] = []
    index = 1
    while index < end:
        marker = lines[index]
        if not marker.strip():
            index += 1
            continue
        if marker.startswith("*** Update File: "):
            path = _normalize_path(marker.removeprefix("*** Update File: ").strip())
            index += 1
            block, index = _codex_block(lines, index, end)
            output.append(_normalize_codex_update(path, block, reader))
            continue
        if marker.startswith("*** Add File: "):
            path = _normalize_path(marker.removeprefix("*** Add File: ").strip())
            index += 1
            block, index = _codex_block(lines, index, end, allow_implicit=True)
            output.append(_normalize_codex_add(path, block))
            continue
        if marker.startswith("*** Delete File: "):
            path = _normalize_path(marker.removeprefix("*** Delete File: ").strip())
            index += 1
            block, index = _codex_block(lines, index, end)
            if block:
                raise InvalidPatchError("Codex delete patch must not contain hunks")
            source = reader(path)
            source_lines = source.splitlines(keepends=True)
            output.extend(
                [f"--- a/{path}\n", "+++ /dev/null\n", f"@@ -1,{len(source_lines)} +0,0 @@\n"]
            )
            output.extend(f"-{line}" if line.endswith("\n") else f"-{line}\n" for line in source_lines)
            continue
        raise InvalidPatchError("unsupported Codex patch operation")
    if not output:
        raise InvalidPatchError("Codex patch contains no file changes")
    return "".join(output)


def _normalize_git_metadata_wrapper(patch: str) -> str:
    """Remove harmless Git wrapper metadata before strict unified-diff parsing.

    Models commonly emit ``git diff`` output.  Only the outer ``diff --git`` and
    ``index`` lines are ignored; all file headers, hunks, and other metadata still
    pass through the existing path and safety validation.
    """

    lines = patch.splitlines(keepends=True)
    if not lines or not lines[0].startswith("diff --git "):
        raise InvalidPatchError("malformed Git patch header")
    return "".join(
        line for line in lines if not line.startswith(("diff --git ", "index "))
    )


def _codex_block(
    lines: list[str], index: int, end: int, *, allow_implicit: bool = False
) -> tuple[list[list[str]], int]:
    hunks: list[list[str]] = []
    current: list[str] | None = None
    while index < end and not lines[index].startswith("*** "):
        line = lines[index]
        if line.startswith("@@"):
            if current is not None:
                hunks.append(current)
            current = []
        elif line.startswith((" ", "+", "-", "\\ No newline")):
            if current is None:
                if not allow_implicit:
                    raise InvalidPatchError("Codex hunk is missing an @@ header")
                current = []
            if not line.startswith("\\ No newline"):
                current.append(line)
        else:
            raise InvalidPatchError("unsupported Codex hunk line")
        index += 1
    if current is not None:
        hunks.append(current)
    return hunks, index


def _normalize_codex_update(
    path: str, hunks: list[list[str]], reader: Callable[[str], str]
) -> str:
    if not hunks:
        raise InvalidPatchError(f"Codex update contains no hunks: {path}")
    original = reader(path)
    current_lines = original.splitlines(keepends=True)
    for hunk in hunks:
        old = [_codex_line(value) for value in hunk if value.startswith((" ", "-"))]
        new = [_codex_line(value) for value in hunk if value.startswith((" ", "+"))]
        if old:
            start = _find_lines(current_lines, old)
            if start is None:
                expected = old[0].rstrip("\n") if old else ""
                raise PatchConflictError(
                    f"hunk context does not match: {path}; expected {expected!r}"
                )
        else:
            if new and _find_lines(current_lines, new) is not None:
                raise PatchConflictError(f"addition already exists: {path}")
            start = len(current_lines)
        current_lines = current_lines[:start] + new + current_lines[start + len(old) :]

    original_lines = original.splitlines(keepends=True)
    source_start = 1 if original_lines else 0
    target_start = 1 if current_lines else 0
    output = [
        f"--- a/{path}\n",
        f"+++ b/{path}\n",
        f"@@ -{source_start},{len(original_lines)} +{target_start},{len(current_lines)} @@\n",
    ]
    output.extend(f"-{line}" if line.endswith("\n") else f"-{line}\n" for line in original_lines)
    output.extend(f"+{line}" if line.endswith("\n") else f"+{line}\n" for line in current_lines)
    return "".join(output)


def _normalize_codex_add(path: str, block: list[list[str]]) -> str:
    if len(block) != 1:
        raise InvalidPatchError(f"Codex add must contain one hunk: {path}")
    values = block[0]
    if any(not value.startswith("+") for value in values):
        raise InvalidPatchError(f"Codex add contains non-addition lines: {path}")
    output = ["--- /dev/null\n", f"+++ b/{path}\n", f"@@ -0,0 +1,{len(values)} @@\n"]
    output.extend(value + ("\n" if not value.endswith("\n") else "") for value in values)
    return "".join(output)


def _codex_line(value: str) -> str:
    return value[1:] + "\n"


def _find_lines(source: list[str], wanted: list[str]) -> int | None:
    if not wanted:
        return len(source)
    for start in range(len(source) - len(wanted) + 1):
        if all(source[start + offset].rstrip("\n") == line.rstrip("\n") for offset, line in enumerate(wanted)):
            return start
    return None


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


def _validate_patch_lines(patch: str) -> tuple[str, ...]:
    source_remaining = target_remaining = 0
    hunk_pattern = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    files: list[str] = []
    file_lines: list[str] = []
    for line in patch.splitlines(keepends=True):
        if not (source_remaining or target_remaining) and line.startswith("--- ") and file_lines:
            files.append("".join(file_lines))
            file_lines = []
        file_lines.append(line)
        if source_remaining or target_remaining:
            if line.startswith("\\ No newline at end of file"):
                continue
            if line.startswith(" "):
                source_remaining -= 1
                target_remaining -= 1
            elif line.startswith("-"):
                source_remaining -= 1
            elif line.startswith("+"):
                target_remaining -= 1
            else:
                raise InvalidPatchError("hunk line count mismatch")
            if source_remaining < 0 or target_remaining < 0:
                raise InvalidPatchError("hunk line count mismatch")
            continue
        if line.startswith(("--- ", "+++ ")):
            continue
        match = hunk_pattern.match(line)
        if match is None:
            raise InvalidPatchError("patch contains unsupported trailing content")
        source_remaining = int(match.group(2) or "1") if match.group(1) else 0
        target_remaining = int(match.group(4) or "1") if match.group(3) else 0
    if source_remaining or target_remaining:
        raise InvalidPatchError("hunk line count mismatch")

    if file_lines:
        files.append("".join(file_lines))
    return tuple(files)


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
        hunk_lines = tuple(hunk)
        expected = tuple(
            str(getattr(line, "value", ""))
            for line in hunk_lines
            if getattr(line, "line_type", "") in {" ", "-"}
        )
        if expected and not _matches_at(original, start, expected):
            candidates = [
                candidate
                for candidate in range(cursor, len(original) - len(expected) + 1)
                if _matches_at(original, candidate, expected)
            ]
            if len(candidates) == 1:
                start = candidates[0]
            elif len(candidates) > 1:
                raise PatchConflictError(f"hunk context is ambiguous: {path}")
        if start < cursor or start > len(original):
            raise PatchConflictError(f"hunk offset is out of range: {path}")
        output.extend(original[cursor:start])
        cursor = start
        consumed = 0
        produced = 0
        for line in hunk_lines:
            line_type = getattr(line, "line_type", "")
            value = str(getattr(line, "value", ""))
            if line_type in {" ", "-"}:
                if cursor >= len(original):
                    raise PatchConflictError(
                        f"hunk context does not match: {path}; expected {value.rstrip(chr(10))!r} "
                        f"at line {cursor + 1}, but the file ended"
                    )
                if original[cursor] != value:
                    raise PatchConflictError(
                        f"hunk context does not match: {path}; expected {value.rstrip(chr(10))!r} "
                        f"at line {cursor + 1}, found {original[cursor].rstrip(chr(10))!r}"
                    )
                if line_type == " ":
                    output.append(value)
                    produced += 1
                cursor += 1
                consumed += 1
            elif line_type == "+":
                output.append(value)
                produced += 1
            else:
                raise InvalidPatchError(f"unsupported hunk line: {path}")
        declared = int(getattr(hunk, "source_length", consumed))
        if declared != consumed:
            raise InvalidPatchError(f"hunk source length mismatch: {path}")
        declared_target = int(getattr(hunk, "target_length", produced))
        if declared_target != produced:
            raise InvalidPatchError(f"hunk target length mismatch: {path}")
    output.extend(original[cursor:])
    if operation is PatchOperation.DELETE and cursor != len(original):
        raise PatchConflictError(f"delete patch does not consume source: {path}")
    result = "".join(output)
    try:
        result.encode("utf-8")
    except UnicodeEncodeError as error:
        raise PatchLimitError("resulting text must be valid UTF-8") from error
    return result


def _matches_at(source: list[str], start: int, expected: tuple[str, ...]) -> bool:
    if start < 0 or start + len(expected) > len(source):
        return False
    return all(source[start + offset] == value for offset, value in enumerate(expected))
