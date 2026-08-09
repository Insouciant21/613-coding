"""Bounded filesystem access constrained to one canonical repository root."""

from __future__ import annotations

import os
import secrets
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from .patch import (
    PatchCommitError,
    PatchOperation,
    PatchResult,
    prepare_patch,
)
from .search import SearchMatch, search_repository


class FilesystemToolError(RuntimeError):
    pass


class PathOutsideRepositoryError(FilesystemToolError):
    pass


class FileTooLargeError(FilesystemToolError):
    pass


class InvalidUtf8Error(FilesystemToolError):
    pass


class FilesystemTools:
    _PROTECTED_MUTATION_ROOTS: ClassVar[frozenset[str]] = frozenset(
        {".613-coding", ".git"}
    )
    _IGNORED_DIRECTORIES: ClassVar[frozenset[str]] = frozenset(
        {
            ".613-coding",
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "dist",
            "node_modules",
        }
    )

    def __init__(self, root: str | Path, max_file_bytes: int = 1_000_000) -> None:
        canonical_root = Path(root).resolve(strict=True)
        if not canonical_root.is_dir():
            raise NotADirectoryError(canonical_root)
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        self.root = canonical_root
        self.max_file_bytes = max_file_bytes

    def list_files(self) -> list[str]:
        files: list[str] = []
        for current_root, directories, filenames in os.walk(self.root, followlinks=False):
            directories[:] = sorted(
                directory
                for directory in directories
                if directory not in self._IGNORED_DIRECTORIES
                and not (Path(current_root) / directory).is_symlink()
            )
            for filename in sorted(filenames):
                path = Path(current_root) / filename
                if path.is_symlink():
                    continue
                files.append(path.relative_to(self.root).as_posix())
        return sorted(files)

    def search_files(self, query: str) -> list[SearchMatch]:
        return search_repository(self.root, query, self.list_files(), self.max_file_bytes)

    def read_file(self, path: str | Path) -> str:
        resolved = self._resolve(path)
        data = resolved.read_bytes()
        if len(data) > self.max_file_bytes:
            raise FileTooLargeError(f"file exceeds {self.max_file_bytes} bytes")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise InvalidUtf8Error("file is not valid UTF-8") from error

    def edit_file(self, path: str | Path, content: str) -> None:
        data = content.encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise FileTooLargeError(f"content exceeds {self.max_file_bytes} bytes")
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if not resolved.parent.resolve(strict=True).is_relative_to(self.root):
            raise PathOutsideRepositoryError("parent escaped repository root")
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{resolved.name}.", dir=resolved.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(data)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, resolved)
        finally:
            temporary_path.unlink(missing_ok=True)

    def delete_file(self, path: str | Path) -> None:
        self._delete_file(Path(path), lambda: None)

    def _delete_file(
        self,
        relative: Path,
        on_commit: Callable[[], None],
        *,
        root_fd: int | None = None,
    ) -> None:
        parent_fd, name = self._parent_descriptor(relative, root_fd=root_fd)
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                raise IsADirectoryError(self.root / relative)
            os.unlink(name, dir_fd=parent_fd)
            on_commit()
        finally:
            os.close(parent_fd)

    def apply_patch(self, patch: str) -> PatchResult:
        root_fd = self._open_root_descriptor()
        changed_files: list[str] = []
        try:
            prepared = prepare_patch(
                patch,
                lambda path: self._read_patch_source(path, root_fd=root_fd),
                max_patch_bytes=self.max_file_bytes,
            )
        except Exception:
            os.close(root_fd)
            raise
        try:
            for change in prepared.changes:
                record_commit = lambda path=change.path: changed_files.append(path)
                if change.operation is PatchOperation.DELETE:
                    self._delete_file(Path(change.path), record_commit, root_fd=root_fd)
                else:
                    if change.after is None:
                        raise RuntimeError("prepared write change has no content")
                    self._write_patch_text(
                        Path(change.path),
                        change.after,
                        record_commit,
                        root_fd=root_fd,
                    )
        except Exception as error:
            committed = tuple(sorted(changed_files))
            raise PatchCommitError(str(error), committed) from error
        finally:
            os.close(root_fd)

        return PatchResult(
            added=sum(
                change.operation is PatchOperation.ADD for change in prepared.changes
            ),
            updated=sum(
                change.operation is PatchOperation.UPDATE for change in prepared.changes
            ),
            deleted=sum(
                change.operation is PatchOperation.DELETE for change in prepared.changes
            ),
            changed_files=tuple(sorted(changed_files)),
        )

    def _read_patch_source(self, path: str, *, root_fd: int | None = None) -> str:
        parent_fd, name = self._parent_descriptor(Path(path), root_fd=root_fd)
        descriptor: int | None = None
        try:
            flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(name, flags, dir_fd=parent_fd)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise PathOutsideRepositoryError("patch source must be a regular file")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(65_536, self.max_file_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > self.max_file_bytes:
                    raise FileTooLargeError(
                        f"file exceeds {self.max_file_bytes} bytes"
                    )
            try:
                return b"".join(chunks).decode("utf-8")
            except UnicodeDecodeError as error:
                raise InvalidUtf8Error("file is not valid UTF-8") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_fd)

    def _write_patch_text(
        self,
        path: Path,
        content: str,
        on_commit: Callable[[], None],
        *,
        root_fd: int | None = None,
    ) -> None:
        data = content.encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise FileTooLargeError(f"content exceeds {self.max_file_bytes} bytes")
        parent_fd, name = self._parent_descriptor(path, create=True, root_fd=root_fd)
        temporary_name = f".{name}.613-tmp-{secrets.token_hex(8)}"
        descriptor: int | None = None
        staged = False
        try:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
            )
            descriptor = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=parent_fd,
            )
            staged = True
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                if written < 1:
                    raise OSError("could not write patch staging file")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(
                temporary_name,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            staged = False
            on_commit()
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if staged:
                try:
                    os.unlink(temporary_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
            os.close(parent_fd)

    def _open_root_descriptor(self) -> int:
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        return os.open(self.root, directory_flags)

    def _parent_descriptor(
        self,
        path: Path,
        *,
        create: bool = False,
        root_fd: int | None = None,
    ) -> tuple[int, str]:
        if "\x00" in str(path) or path.is_absolute() or ".." in path.parts or not path.parts:
            raise PathOutsideRepositoryError("path must be repository-relative")
        if path.parts[0] in self._PROTECTED_MUTATION_ROOTS:
            raise PathOutsideRepositoryError("mutation path is protected")

        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        current_fd = os.dup(root_fd) if root_fd is not None else os.open(self.root, directory_flags)
        try:
            for component in path.parent.parts:
                try:
                    metadata = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(component, dir_fd=current_fd)
                    metadata = os.stat(
                        component, dir_fd=current_fd, follow_symlinks=False
                    )
                if stat.S_ISLNK(metadata.st_mode):
                    raise PathOutsideRepositoryError("delete parent cannot be a symlink")
                if not stat.S_ISDIR(metadata.st_mode):
                    raise NotADirectoryError(component)
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd, path.name
        except BaseException:
            os.close(current_fd)
            raise

    def _resolve(self, path: str | Path) -> Path:
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise PathOutsideRepositoryError("path must be repository-relative")
        candidate = (self.root / relative).resolve(strict=False)
        if candidate == self.root or not candidate.is_relative_to(self.root):
            raise PathOutsideRepositoryError("path escaped repository root")
        return candidate
