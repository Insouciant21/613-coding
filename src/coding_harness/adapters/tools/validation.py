"""Bounded argv-only subprocess execution for objective validators."""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO

from coding_harness.application.validation import (
    ValidationKind,
    ValidationLimits,
    ValidationResult,
)


class _OutputBudget:
    def __init__(self, limit: int) -> None:
        self._remaining = limit
        self._lock = threading.Lock()
        self.truncated = False

    def take(self, chunk: bytes) -> bytes:
        with self._lock:
            size = min(len(chunk), self._remaining)
            self._remaining -= size
            if size < len(chunk):
                self.truncated = True
            return chunk[:size]


class _CapturedStream:
    def __init__(self, budget: _OutputBudget) -> None:
        self._budget = budget
        self._data = bytearray()

    def read(self, stream: BinaryIO) -> None:
        while chunk := stream.read(8192):
            self._data.extend(self._budget.take(chunk))

    def text(self) -> str:
        return bytes(self._data).decode("utf-8", errors="replace")


class ValidatorRunner:
    def run(
        self,
        command: Sequence[str],
        cwd: str | Path,
        limits: ValidationLimits,
        kind: ValidationKind,
    ) -> ValidationResult:
        argv = tuple(command)
        if not argv or any(not item for item in argv):
            raise ValueError("validation command must contain nonempty argv items")
        working_directory = Path(cwd).resolve(strict=True)
        start = time.monotonic()
        try:
            process = subprocess.Popen(
                argv,
                cwd=working_directory,
                env=dict(limits.environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=os.name == "posix",
            )
        except FileNotFoundError:
            return self._launch_failure(argv, kind, start, 127, "command not found")
        except PermissionError:
            return self._launch_failure(argv, kind, start, 126, "command not executable")

        self._apply_resource_limits(process.pid, limits)

        assert process.stdout is not None
        assert process.stderr is not None
        output_budget = _OutputBudget(limits.max_output_bytes)
        stdout = _CapturedStream(output_budget)
        stderr = _CapturedStream(output_budget)
        threads = [
            threading.Thread(target=stdout.read, args=(process.stdout,), daemon=True),
            threading.Thread(target=stderr.read, args=(process.stderr,), daemon=True),
        ]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            process.wait(timeout=limits.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill(process)
            process.wait()
        finally:
            for thread in threads:
                thread.join()
        return_code = process.returncode
        exhausted = not timed_out and return_code in {-signal.SIGKILL, -signal.SIGXCPU}
        return ValidationResult(
            command=argv,
            kind=kind,
            exit_code=None if timed_out else return_code,
            stdout=stdout.text(),
            stderr=stderr.text(),
            duration_seconds=time.monotonic() - start,
            timed_out=timed_out,
            resource_exhausted=exhausted,
            output_truncated=output_budget.truncated,
        )

    @staticmethod
    def _launch_failure(
        argv: tuple[str, ...],
        kind: ValidationKind,
        start: float,
        exit_code: int,
        message: str,
    ) -> ValidationResult:
        return ValidationResult(
            command=argv,
            kind=kind,
            exit_code=exit_code,
            stderr=message,
            duration_seconds=time.monotonic() - start,
        )

    @staticmethod
    def _apply_resource_limits(pid: int, limits: ValidationLimits) -> None:
        if os.name != "posix" or not hasattr(resource, "prlimit"):
            return
        try:
            if limits.max_memory_bytes is not None:
                resource.prlimit(
                    pid,
                    resource.RLIMIT_AS,
                    (limits.max_memory_bytes, limits.max_memory_bytes),
                )
            if limits.max_processes is not None and hasattr(resource, "RLIMIT_NPROC"):
                resource.prlimit(
                    pid,
                    resource.RLIMIT_NPROC,
                    (limits.max_processes, limits.max_processes),
                )
        except ProcessLookupError:
            return

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            return
