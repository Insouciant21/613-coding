from __future__ import annotations

import sys
from pathlib import Path

from coding613.adapters.tools.validation import ValidatorRunner
from coding613.application.validation import ValidationKind, ValidationLimits


def test_validator_runner_captures_exit_and_caps_output(tmp_path: Path) -> None:
    runner = ValidatorRunner()
    validation = runner.run(
        (
            sys.executable,
            "-c",
            "import sys; print('x' * 100); print('y' * 100, file=sys.stderr); sys.exit(3)",
        ),
        tmp_path,
        ValidationLimits(timeout_seconds=2, max_output_bytes=16),
        ValidationKind.TEST,
    )
    assert validation.exit_code == 3
    assert len(validation.stdout.encode()) + len(validation.stderr.encode()) <= 16
    assert validation.output_truncated


def test_validator_runner_times_out(tmp_path: Path) -> None:
    validation = ValidatorRunner().run(
        (sys.executable, "-c", "import time; time.sleep(2)"),
        tmp_path,
        ValidationLimits(timeout_seconds=0.05, max_output_bytes=64),
        ValidationKind.TEST,
    )
    assert validation.timed_out
    assert validation.exit_code is None
