import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_container_smoke_verifies_health_and_user_then_cleans_up(tmp_path: Path) -> None:
    calls = tmp_path / "docker-calls"
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$DOCKER_CALLS"
case "$1" in
  run) printf '%s\\n' fake-container ;;
  inspect)
    case "$3" in
      *Config.User*) printf '%s\\n' coding ;;
      *) printf '%s\\n' healthy ;;
    esac
    ;;
esac
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ | {
        "DOCKER_CALLS": str(calls),
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
    }

    completed = subprocess.run(
        ["/bin/sh", str(ROOT / "scripts/smoke_container.sh"), "613-coding:test"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "container smoke passed" in completed.stdout
    docker_calls = calls.read_text(encoding="utf-8")
    assert "run -d --name" in docker_calls
    assert "613-coding:test" in docker_calls
    assert "inspect --format" in docker_calls
    assert "rm -f" in docker_calls
