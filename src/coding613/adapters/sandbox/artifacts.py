"""Deterministic, redacted export of workspace changes."""

from __future__ import annotations

import difflib
import fnmatch
from collections.abc import Mapping, Sequence
from typing import Any

from coding613.domain.redaction import redact_text
from coding613.domain.sandbox import WorkArtifact

from .workspace import (
    FileSnapshot,
    Workspace,
    WorkspaceBaseline,
    WorkspaceIntegrityError,
    WorkspaceManager,
    WriteSetViolation,
    normalize_write_set,
    snapshot_tree,
)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes):
        return redact_text(value.decode("utf-8", errors="replace"))
    if isinstance(value, Mapping):
        return {redact_text(str(key)): _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_redact(item) for item in value)
    return value


def _is_text(content: bytes) -> bool:
    return b"\x00" not in content and _decode(content) is not None


def _decode(content: bytes) -> str | None:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _changed(before: FileSnapshot | None, after: FileSnapshot | None) -> bool:
    return before != after


def _patch_for(path: str, before: FileSnapshot | None, after: FileSnapshot | None) -> str:
    header = f"diff --git a/{path} b/{path}\n"
    if before is None and after is not None:
        mode_lines = f"new file mode {after.mode:o}\n"
    elif after is None and before is not None:
        mode_lines = f"deleted file mode {before.mode:o}\n"
    elif before is not None and after is not None and before.mode != after.mode:
        mode_lines = f"old mode {before.mode:o}\nnew mode {after.mode:o}\n"
    else:
        mode_lines = ""
    if before is not None and after is not None and before.kind == after.kind == "file":
        old_text = _decode(before.content)
        new_text = _decode(after.content)
        if old_text is not None and new_text is not None:
            old_lines = old_text.splitlines(keepends=True)
            new_lines = new_text.splitlines(keepends=True)
            body = "".join(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                    n=3,
                )
            )
            return header + mode_lines + body
    if before is None and after is not None and after.kind == "file" and _is_text(after.content):
        text = _decode(after.content) or ""
        body = "".join(
            difflib.unified_diff([], text.splitlines(keepends=True), fromfile="/dev/null", tofile=f"b/{path}", n=3)
        )
        return header + mode_lines + body
    if after is None and before is not None and before.kind == "file" and _is_text(before.content):
        text = _decode(before.content) or ""
        body = "".join(
            difflib.unified_diff(text.splitlines(keepends=True), [], fromfile=f"a/{path}", tofile="/dev/null", n=3)
        )
        return header + mode_lines + body
    old_path = f"a/{path}" if before is not None else "/dev/null"
    new_path = f"b/{path}" if after is not None else "/dev/null"
    return header + mode_lines + f"Binary files {old_path} and {new_path} differ\n"


class ArtifactExporter:
    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        declared_write_set: Sequence[str] | None = None,
        verification_evidence: Sequence[dict[str, Any]] = (),
        assumptions: Sequence[str] = (),
        follow_up_requests: Sequence[str] = (),
    ) -> None:
        self._workspace_manager = workspace_manager
        self._declared_write_set = normalize_write_set(declared_write_set) if declared_write_set is not None else None
        self._verification_evidence = tuple(verification_evidence)
        self._assumptions = tuple(assumptions)
        self._follow_up_requests = tuple(follow_up_requests)

    def collect(
        self,
        workspace: Workspace,
        baseline: WorkspaceBaseline | None = None,
    ) -> WorkArtifact:
        self._workspace_manager.validate(workspace)
        current = snapshot_tree(workspace.path)
        if baseline is not None and baseline is not workspace.baseline:
            raise WorkspaceIntegrityError("baseline was not created by manager")
        original = workspace.baseline
        paths = sorted(set(original.files) | set(current))
        changed = tuple(path for path in paths if _changed(original.files.get(path), current.get(path)))
        write_set = self._declared_write_set
        if write_set is None:
            write_set = workspace.declared_write_set
        violations = tuple(path for path in changed if not self._allowed(path, write_set))
        if violations:
            raise WriteSetViolation("changed files outside declared write set: " + ", ".join(violations))
        patch = "".join(_patch_for(path, original.files.get(path), current.get(path)) for path in changed)
        binary = tuple(path for path in changed if not self._is_patch_text(original.files.get(path), current.get(path)))
        summary = f"changed files: {', '.join(changed) if changed else 'none'}"
        if binary:
            summary += "; binary files: " + ", ".join(binary)
        return WorkArtifact(
            patch=redact_text(patch),
            changed_files=tuple(redact_text(path) for path in changed),
            summary=redact_text(summary),
            verification_evidence=tuple(_redact(item) for item in self._verification_evidence),
            assumptions=tuple(redact_text(item) for item in self._assumptions),
            follow_up_requests=tuple(redact_text(item) for item in self._follow_up_requests),
        )

    @staticmethod
    @staticmethod
    def _allowed(path: str, write_set: Sequence[str]) -> bool:
        return any(fnmatch.fnmatchcase(path, pattern) or path == pattern or path.startswith(pattern.rstrip("/") + "/") for pattern in write_set)

    @staticmethod
    def _is_patch_text(before: FileSnapshot | None, after: FileSnapshot | None) -> bool:
        snapshots = [item for item in (before, after) if item is not None]
        return all(item.kind == "file" and _is_text(item.content) for item in snapshots)
