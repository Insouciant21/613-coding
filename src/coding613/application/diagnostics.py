"""Deterministic, injectable local diagnostics for TUI and CLI adapters."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID

from coding613.domain.conversation import DiagnosticCheck, DiagnosticReport
from coding613.domain.redaction import redact_text

DiagnosticCheckFactory = Callable[[UUID], DiagnosticCheck]


class DiagnosticService:
    def __init__(self, checks: Sequence[DiagnosticCheckFactory]) -> None:
        self._checks = tuple(checks)

    def run(self, project_id: UUID) -> DiagnosticReport:
        results: list[DiagnosticCheck] = []
        for index, check in enumerate(self._checks):
            try:
                result = DiagnosticCheck.model_validate(check(project_id))
                results.append(
                    result.model_copy(update={"detail": redact_text(result.detail)})
                )
            except Exception:  # noqa: BLE001 - diagnostics must isolate one failed check
                results.append(
                    DiagnosticCheck(
                        name=f"check_{index + 1}",
                        status="fail",
                        detail="diagnostic check failed",
                    )
                )
        return DiagnosticReport(project_id=project_id, checks=tuple(results))


def local_diagnostic_checks(
    repository_root: Path,
    state_root: Path,
    *,
    provider_configured: bool,
) -> tuple[DiagnosticCheckFactory, ...]:
    """Build safe checks without reading credentials or executing repository code."""

    def repository(project_id: UUID) -> DiagnosticCheck:
        del project_id
        readable = repository_root.is_dir() and os.access(repository_root, os.R_OK)
        return DiagnosticCheck(
            name="repository",
            status="pass" if readable else "fail",
            detail="repository is readable" if readable else "repository is not readable",
        )

    def state(project_id: UUID) -> DiagnosticCheck:
        del project_id
        writable = state_root.is_dir() and os.access(state_root, os.W_OK)
        return DiagnosticCheck(
            name="state",
            status="pass" if writable else "fail",
            detail="state directory is writable" if writable else "state directory is not writable",
        )

    def provider(project_id: UUID) -> DiagnosticCheck:
        del project_id
        return DiagnosticCheck(
            name="provider",
            status="pass" if provider_configured else "warn",
            detail=(
                "provider metadata is configured"
                if provider_configured
                else "no provider metadata configured"
            ),
        )

    def docker(project_id: UUID) -> DiagnosticCheck:
        del project_id
        available = shutil.which("docker") is not None
        return DiagnosticCheck(
            name="docker",
            status="pass" if available else "warn",
            detail="Docker Engine command is available" if available else "Docker Engine is optional and unavailable",
        )

    return (repository, state, provider, docker)
