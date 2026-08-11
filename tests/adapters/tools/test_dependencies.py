from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from coding613.adapters.tools.dependencies import DependencyInstaller


def test_npm_install_uses_argv_workspace_and_ignore_scripts(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], Path, float]] = []

    def runner(
        argv: tuple[str, ...], cwd: Path, timeout: float
    ) -> CompletedProcess[str]:
        calls.append((argv, cwd, timeout))
        return CompletedProcess(argv, 0, "installed", "")

    result = DependencyInstaller(tmp_path, runner=runner).install(
        manager="npm",
        packages=("three", "@types/three"),
        workspace="@613-cube-solver/web",
        dev=True,
    )

    assert result.success is True
    assert calls == [
        (
            (
                "npm",
                "install",
                "--ignore-scripts",
                "--save-dev",
                "--workspace",
                "@613-cube-solver/web",
                "three",
                "@types/three",
            ),
            tmp_path,
            300.0,
        )
    ]
    assert result.output == "installed"


def test_dependency_installer_rejects_shell_metacharacters(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="package"):
        DependencyInstaller(tmp_path).install(manager="npm", packages=("three;rm",))
