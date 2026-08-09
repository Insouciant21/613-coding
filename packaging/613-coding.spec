# -*- mode: python ; coding: utf-8 -*-
"""Deterministic PyInstaller collection for the Linux TUI executable."""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

spec_location = str(globals().get("__file__", os.getcwd()))
project_root = Path(
    os.environ.get("CODING613_ROOT", os.path.abspath(os.path.join(os.path.dirname(spec_location), "..")))
)
src_root = project_root / "src"
required_data = (
    src_root / "coding613" / "adapters" / "storage" / "schema.sql",
    src_root / "coding613" / "tui" / "styles.tcss",
)
missing = [str(path) for path in required_data if not path.is_file()]
if missing:
    raise FileNotFoundError(f"required PyInstaller data file(s) missing: {', '.join(missing)}")

datas: list[tuple[str, str]] = [
    (str(required_data[0]), "coding613/adapters/storage"),
    (str(required_data[1]), "coding613/tui"),
]
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = []
for package in ("coding613", "textual", "lancedb", "pyarrow", "keyring.backends"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)

a = Analysis(
    [str(project_root / "packaging" / "launcher.py")],
    pathex=[str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="613-coding-linux-x86_64",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
