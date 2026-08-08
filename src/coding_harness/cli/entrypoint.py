"""Installed console entrypoint."""

from __future__ import annotations

from .main import app


def main() -> None:
    app()
