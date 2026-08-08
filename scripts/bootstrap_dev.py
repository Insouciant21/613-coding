#!/usr/bin/env python3
"""Check whether the provisioned development toolchain is available."""

from __future__ import annotations

import importlib.util
import shutil
import sys


REQUIRED_IMPORTS = ("pydantic", "pytest")
REQUIRED_COMMANDS = ("uv", "ruff", "mypy")


def main() -> int:
    missing_imports = [name for name in REQUIRED_IMPORTS if importlib.util.find_spec(name) is None]
    missing_commands = [name for name in REQUIRED_COMMANDS if shutil.which(name) is None]
    if missing_imports or missing_commands:
        print("DEPENDENCY_PROVISIONING_BLOCKED")
        print("Missing imports: " + (", ".join(missing_imports) or "none"))
        print("Missing commands: " + (", ".join(missing_commands) or "none"))
        print("Remediation: uv sync --all-extras --frozen")
        print("Air-gapped remediation: provide a populated uv cache or wheelhouse, then run")
        print("  uv sync --all-extras --frozen --offline")
        return 1
    print("DEPENDENCIES_PROVISIONED")
    print("Canonical checks: uv run pytest, uv run ruff check ., uv run mypy src")
    return 0


if __name__ == "__main__":
    sys.exit(main())
