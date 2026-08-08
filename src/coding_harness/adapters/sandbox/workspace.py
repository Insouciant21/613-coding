"""Temporary, repository-shaped workspaces for sandbox workers."""

from __future__ import annotations

import shutil
import stat
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


class WorkspaceError(RuntimeError):
    """Base error raised while preparing or inspecting a workspace."""


class WorkspacePathError(WorkspaceError, ValueError):
    """A source or workspace path would escape its canonical root."""


class WriteSetViolation(WorkspaceError):
    """A changed path was not included in the worker's declared write set."""


class WorkspaceIntegrityError(WorkspacePathError):
    """A workspace or baseline was not issued by its manager."""


@dataclass(frozen=True)
class FileSnapshot:
    kind: str
    content: bytes
    mode: int


@dataclass(frozen=True)
class WorkspaceBaseline:
    files: Mapping[str, FileSnapshot]

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))


@dataclass(frozen=True)
class Workspace:
    path: Path
    source_repo: Path
    run_id: str
    worker_id: str
    declared_write_set: tuple[str, ...]
    baseline: WorkspaceBaseline

    @property
    def root(self) -> Path:
        return self.path

    @property
    def workspace_path(self) -> Path:
        return self.path


def _canonical(path: Path, *, strict: bool = True) -> Path:
    try:
        return path.expanduser().resolve(strict=strict)
    except FileNotFoundError as exc:
        raise WorkspacePathError(f"path does not exist: {path}") from exc


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise WorkspacePathError(f"path escapes workspace: {path}") from exc


def _validate_symlinks(root: Path) -> None:
    root = _canonical(root)
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        target = path.resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise WorkspacePathError(f"symlink escapes root: {_relative(root, path)}") from exc


def snapshot_tree(root: Path) -> dict[str, FileSnapshot]:
    """Return a stable snapshot of all working-tree files, including ignored files."""

    root = _canonical(root)
    _validate_symlinks(root)
    snapshots: dict[str, FileSnapshot] = {}
    for path in sorted(root.rglob("*")):
        if path == root / ".git" or root / ".git" in path.parents:
            continue
        if path.is_dir() and not path.is_symlink():
            continue
        relative = _relative(root, path)
        if path.is_symlink():
            snapshots[relative] = FileSnapshot("symlink", path.readlink().as_posix().encode(), 0o120000)
        elif path.is_file():
            mode = 0o100000 | stat.S_IMODE(path.stat().st_mode)
            snapshots[relative] = FileSnapshot("file", path.read_bytes(), mode)
        else:
            raise WorkspacePathError(f"unsupported workspace entry: {relative}")
    return snapshots


def normalize_write_set(values: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() in {"", "."}:
            raise WorkspacePathError(f"write-set path must be repository-relative: {value}")
        normalized.append(path.as_posix())
    return tuple(sorted(set(normalized)))


class WorkspaceManager:
    def __init__(
        self,
        temporary_root: Path | None = None,
        declared_write_set: Iterable[str] = (),
    ) -> None:
        self._root = _canonical(temporary_root, strict=False) if temporary_root else None
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
        self._declared_write_set = normalize_write_set(declared_write_set)
        self._owned: dict[int, tuple[Workspace, Path]] = {}
        self._cleaned: list[Workspace] = []

    def create(
        self,
        source_repo: Path,
        run_id: str,
        worker_id: str,
        declared_write_set: Iterable[str] | None = None,
    ) -> Workspace:
        source = _canonical(Path(source_repo))
        if not source.is_dir() or not (source / ".git").exists():
            raise WorkspaceError("source_repo must be a Git working tree")
        _validate_symlinks(source)
        write_set = self._declared_write_set if declared_write_set is None else normalize_write_set(declared_write_set)
        temporary_path = Path(tempfile.mkdtemp(prefix="613-sandbox-", dir=self._root))
        try:
            destination = temporary_path / "repo"
            shutil.copytree(source, destination, symlinks=True)
            destination = _canonical(destination)
            baseline = WorkspaceBaseline(snapshot_tree(destination))
            workspace = Workspace(destination, source, str(run_id), str(worker_id), write_set, baseline)
            self._owned[id(workspace)] = (workspace, _canonical(temporary_path))
            return workspace
        except Exception:
            shutil.rmtree(temporary_path, ignore_errors=True)
            raise

    def cleanup(self, workspace: Workspace) -> None:
        if any(item is workspace for item in self._cleaned):
            return
        record = self._owned.get(id(workspace))
        if record is None or record[0] is not workspace:
            raise WorkspacePathError("workspace was not created by manager")
        path, temporary_path = workspace.path, record[1]
        if self._root is not None:
            try:
                path.relative_to(self._root)
            except ValueError as exc:
                raise WorkspacePathError("workspace is outside manager temporary root") from exc
        if temporary_path == self._root or temporary_path == Path(temporary_path.anchor):
            raise WorkspacePathError("refusing to remove workspace root")
        if temporary_path.exists():
            shutil.rmtree(temporary_path)
        del self._owned[id(workspace)]
        self._cleaned.append(workspace)

    def validate(self, workspace: Workspace) -> None:
        """Validate that a workspace is the exact object issued by this manager."""

        record = self._owned.get(id(workspace))
        if record is None or record[0] is not workspace:
            raise WorkspaceIntegrityError("workspace was not created by manager")
