from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _fake_bin(tmp_path: Path, *, fail_pyinstaller: bool = False) -> tuple[Path, Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    (bindir / "uv").write_text(
        """#!/bin/sh
set -eu
printf 'uv %s\\n' "$*" >> "$CALL_LOG"
if [ "$1" = build ]; then
  out="$3"
  mkdir -p "$out"
  : > "$out/613_coding-0.1.0-py3-none-any.whl"
  : > "$out/613_coding-0.1.0.tar.gz"
fi
if [ "$1" = run ] && [ "$2" = pyinstaller ]; then
  shift 2
  exec pyinstaller "$@"
fi
""",
        encoding="utf-8",
    )
    (bindir / "pyinstaller").write_text(
        f"""#!/bin/sh
set -eu
previous=
printf 'pyinstaller %s\\n' "$*" >> "$CALL_LOG"
{'exit 9' if fail_pyinstaller else 'for arg in "$@"; do [ "$previous" = distpath ] && dist="$arg"; previous=""; [ "$arg" = --distpath ] && previous=distpath; done; mkdir -p "$dist"; printf "#!/bin/sh\\nprintf \\\"613-coding help\\n\\\"\\n" > "$dist/613-coding-linux-x86_64"; chmod +x "$dist/613-coding-linux-x86_64"'}
""",
        encoding="utf-8",
    )
    (bindir / "sha256sum").write_text(
        """#!/bin/sh
set -eu
printf 'sha256sum %s\\n' "$*" >> "$CALL_LOG"
if [ "$1" = -c ]; then exit 0; fi
for value in "$@"; do printf 'fake  %s\\n' "$(basename "$value")"; done
""",
        encoding="utf-8",
    )
    for path in bindir.iterdir():
        path.chmod(0o755)
    return bindir, log


def test_build_artifacts_passes_explicit_output_and_tool_arguments(tmp_path: Path) -> None:
    bindir, log = _fake_bin(tmp_path)
    output = tmp_path / "artifacts"
    env = os.environ | {"PATH": f"{bindir}:{os.environ['PATH']}", "CALL_LOG": str(log)}

    result = subprocess.run(
        ["bash", str(ROOT / "scripts/build_artifacts.sh"), str(output)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert (output / "613-coding-linux-x86_64").exists()
    assert (output / "613_coding-0.1.0-py3-none-any.whl").exists()
    assert (output / "613_coding-0.1.0.tar.gz").exists()
    assert (output / "SHA256SUMS").exists()
    calls = log.read_text(encoding="utf-8")
    assert "uv build --out-dir" in calls
    assert "pyinstaller" in calls
    assert "sha256sum" in calls


def test_build_artifacts_propagates_pyinstaller_failure(tmp_path: Path) -> None:
    bindir, log = _fake_bin(tmp_path, fail_pyinstaller=True)
    env = os.environ | {"PATH": f"{bindir}:{os.environ['PATH']}", "CALL_LOG": str(log)}

    result = subprocess.run(
        ["bash", str(ROOT / "scripts/build_artifacts.sh"), str(tmp_path / "artifacts")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 9


def test_smoke_artifacts_propagates_checksum_failure(tmp_path: Path) -> None:
    bindir, log = _fake_bin(tmp_path)
    (bindir / "sha256sum").write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    (bindir / "sha256sum").chmod(0o755)
    output = tmp_path / "artifacts"
    output.mkdir()
    for name in (
        "613-coding-linux-x86_64",
        "613_coding-0.1.0-py3-none-any.whl",
        "613_coding-0.1.0.tar.gz",
    ):
        (output / name).touch()
    (output / "613-coding-linux-x86_64").chmod(0o755)
    (output / "SHA256SUMS").write_text("fake\n", encoding="utf-8")
    env = os.environ | {"PATH": f"{bindir}:{os.environ['PATH']}", "CALL_LOG": str(log)}

    result = subprocess.run(
        ["bash", str(ROOT / "scripts/smoke_artifacts.sh"), str(output)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 7
