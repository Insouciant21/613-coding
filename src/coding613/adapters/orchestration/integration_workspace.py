"""Controlled integration workspace metadata."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from coding613.adapters.sandbox.workspace import normalize_write_set


class IntegrationWorkspace:
    def __init__(self, path: Path, declared_write_set: Iterable[str] = ()) -> None:
        self.path = path.expanduser().resolve(strict=True)
        if not self.path.is_dir() or not (self.path / ".git").exists():
            raise ValueError("integration workspace must be a Git working tree")
        self.declared_write_set = normalize_write_set(declared_write_set)
