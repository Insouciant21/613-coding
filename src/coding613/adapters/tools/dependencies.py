"""Policy-bounded npm dependency installation for repository workers."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess

_PACKAGE_PATTERN = re.compile(
    r"^(?:@?[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]*(?:@[A-Za-z0-9._~^*<>=-]+)?$"
)
_WORKSPACE_PATTERN = re.compile(r"^[A-Za-z0-9@/_.-]+$")


@dataclass(frozen=True, slots=True)
class DependencyInstallResult:
    success: bool
    output: str = ""
    error: str | None = None
    changed_files: tuple[str, ...] = ()


Runner = Callable[[tuple[str, ...], Path, float], CompletedProcess[str]]


class DependencyInstaller:
    """Install explicitly named npm packages without shell interpolation."""

    def __init__(
        self,
        root: str | Path,
        *,
        runner: Runner | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._root = Path(root).resolve(strict=True)
        if not self._root.is_dir():
            raise NotADirectoryError(self._root)
        if timeout_seconds <= 0:
            raise ValueError("dependency install timeout must be positive")
        self._runner = runner or self._run
        self._timeout_seconds = timeout_seconds

    def install(
        self,
        *,
        manager: str,
        packages: Sequence[str],
        workspace: str | None = None,
        dev: bool = False,
    ) -> DependencyInstallResult:
        if manager != "npm":
            raise ValueError("only npm dependency installation is supported")
        names = tuple(packages)
        if not names or len(names) > 32:
            raise ValueError("dependency package list must contain 1 to 32 packages")
        if any(not _PACKAGE_PATTERN.fullmatch(name) for name in names):
            raise ValueError("package names contain unsupported characters")
        if workspace is not None and not _WORKSPACE_PATTERN.fullmatch(workspace):
            raise ValueError("workspace name contains unsupported characters")

        argv = ["npm", "install", "--ignore-scripts"]
        if dev:
            argv.append("--save-dev")
        if workspace is not None:
            argv.extend(("--workspace", workspace))
        argv.extend(names)
        command = tuple(argv)
        try:
            completed = self._runner(command, self._root, self._timeout_seconds)
        except subprocess.TimeoutExpired:
            return DependencyInstallResult(
                success=False, error="TimeoutExpired", output=""
            )
        except OSError as error:
            return DependencyInstallResult(success=False, error=type(error).__name__)
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        changed = (
            "package.json",
            "package-lock.json",
        ) if completed.returncode == 0 else ()
        return DependencyInstallResult(
            success=completed.returncode == 0,
            output=output,
            error=None if completed.returncode == 0 else f"exit_{completed.returncode}",
            changed_files=changed,
        )

    @staticmethod
    def _run(command: tuple[str, ...], cwd: Path, timeout: float) -> CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            env={"PATH": os.environ.get("PATH", ""), "CI": "1"},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
