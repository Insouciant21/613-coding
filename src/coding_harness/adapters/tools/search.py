"""Deterministic bounded text search."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SearchMatch:
    path: str
    line_number: int
    line: str


def search_repository(
    root: Path,
    query: str,
    relative_paths: Iterable[str],
    max_file_bytes: int,
) -> list[SearchMatch]:
    if not query:
        raise ValueError("search query must not be empty")
    matches: list[SearchMatch] = []
    for relative_path in sorted(relative_paths):
        path = root / relative_path
        data = path.read_bytes()
        if len(data) > max_file_bytes:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                matches.append(SearchMatch(relative_path, line_number, line))
    return matches
