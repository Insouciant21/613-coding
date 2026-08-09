"""Bounded filesystem access constrained to one canonical repository root."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import ClassVar

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
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise PathOutsideRepositoryError("path must be repository-relative")
        parent = self.root
        for component in relative.parent.parts:
            candidate = parent / component
            if candidate.is_symlink():
                raise PathOutsideRepositoryError("delete parent cannot be a symlink")
            parent = candidate
        parent = parent.resolve(strict=True)
        if not parent.is_relative_to(self.root):
            raise PathOutsideRepositoryError("parent escaped repository root")
        entry = parent / relative.name
        if not entry.exists() and not entry.is_symlink():
            raise FileNotFoundError(entry)
        if entry.is_dir() and not entry.is_symlink():
            raise IsADirectoryError(entry)
        entry.unlink()

    def _resolve(self, path: str | Path) -> Path:
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise PathOutsideRepositoryError("path must be repository-relative")
        candidate = (self.root / relative).resolve(strict=False)
        if candidate == self.root or not candidate.is_relative_to(self.root):
            raise PathOutsideRepositoryError("path escaped repository root")
        return candidate
