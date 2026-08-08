"""Controlled application of worker artifacts to the integration workspace."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from coding_harness.adapters.orchestration.integration_workspace import IntegrationWorkspace
from coding_harness.domain.models import Feedback, FeedbackKind
from coding_harness.domain.models_base import DomainModel
from coding_harness.domain.sandbox import WorkArtifact


class IntegrationResult(DomainModel):
    applied: bool = False
    conflict: bool = False
    replay_required: bool = False
    changed_files: tuple[str, ...] = ()
    feedback: tuple[Feedback, ...] = ()


class ArtifactIntegrator:
    def __init__(self) -> None:
        self._replay_attempted: set[int] = set()

    def apply(self, artifact: WorkArtifact, workspace: IntegrationWorkspace) -> IntegrationResult:
        path_error = self._validate_paths(artifact, workspace)
        if path_error is not None:
            return path_error
        check = self._git_apply(artifact.patch, workspace.path, check=True)
        if check.returncode != 0:
            return self._conflict(artifact)
        applied = self._git_apply(artifact.patch, workspace.path, check=False)
        if applied.returncode != 0:
            return self._conflict(artifact)
        return IntegrationResult(applied=True, changed_files=artifact.changed_files)

    def replay_conflict(self, artifact: WorkArtifact, workspace: IntegrationWorkspace) -> IntegrationResult:
        key = id(artifact)
        if key in self._replay_attempted:
            return self._conflict(artifact, replay_required=False)
        self._replay_attempted.add(key)
        return self._conflict(artifact, replay_required=False)

    def validate(self, workspace: IntegrationWorkspace) -> tuple[Feedback, ...]:
        del workspace
        return ()

    def _validate_paths(self, artifact: WorkArtifact, workspace: IntegrationWorkspace) -> IntegrationResult | None:
        allowed = workspace.declared_write_set
        patch_paths = self._patch_paths(artifact.patch)
        if set(patch_paths) != set(artifact.changed_files):
            return self._policy_feedback("patch metadata mismatch")
        for changed in (*artifact.changed_files, *patch_paths):
            path = Path(changed)
            if path.is_absolute() or ".." in path.parts:
                return self._policy_feedback(changed)
            if not any(
                fnmatch.fnmatchcase(changed, pattern)
                or changed == pattern
                or changed.startswith(pattern.rstrip("/") + "/")
                for pattern in allowed
            ):
                return self._policy_feedback(changed)
        return None

    @staticmethod
    def _patch_paths(patch: str) -> tuple[str, ...]:
        paths: list[str] = []
        for line in patch.splitlines():
            if not line.startswith("diff --git a/"):
                continue
            value = line[len("diff --git a/") :]
            if " b/" not in value:
                return ()
            left, right = value.split(" b/", 1)
            if left != right:
                return ()
            paths.append(left)
        return tuple(sorted(set(paths)))

    @staticmethod
    def _git_apply(patch: str, cwd: Path, *, check: bool) -> subprocess.CompletedProcess[bytes]:
        command = ["git", "apply", "--whitespace=nowarn"]
        if check:
            command.append("--check")
        command.append("-")
        return subprocess.run(command, cwd=cwd, input=patch.encode(), capture_output=True, check=False)

    @staticmethod
    def _policy_feedback(path: str) -> IntegrationResult:
        return IntegrationResult(
            feedback=(
                Feedback(
                    kind=FeedbackKind.POLICY_BLOCKED,
                    message=f"artifact path outside integration write set: {path}",
                    retryable=False,
                ),
            )
        )

    def _conflict(self, artifact: WorkArtifact, *, replay_required: bool | None = None) -> IntegrationResult:
        if replay_required is None:
            replay_required = id(artifact) not in self._replay_attempted
        return IntegrationResult(
            conflict=True,
            replay_required=replay_required,
            changed_files=artifact.changed_files,
            feedback=(
                Feedback(
                    kind=FeedbackKind.MERGE_CONFLICT,
                    message="worker artifact does not apply cleanly",
                    retryable=replay_required,
                ),
            ),
        )
