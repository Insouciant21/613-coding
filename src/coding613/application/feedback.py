"""Deterministic classification of objective coding feedback."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from typing import Any, ClassVar

from pydantic import Field

from coding613.domain.actions import ToolCall
from coding613.domain.models import Feedback, FeedbackKind
from coding613.domain.models_base import DomainModel

from .validation import ValidationKind, ValidationResult


class _ClassifierState(DomainModel):
    repeated_failure_limit: int = Field(ge=2)
    fingerprints: dict[str, int]


class FeedbackClassifier:
    _ENVIRONMENT_MARKERS = (
        "command not found",
        "modulenotfounderror",
        "no such file or directory",
    )
    _CHANGE_ACTIONS: ClassVar[frozenset[str]] = frozenset(
        {"apply_patch", "delete_file", "edit_file", "write_file"}
    )

    def __init__(self, repeated_failure_limit: int = 3) -> None:
        if repeated_failure_limit < 2:
            raise ValueError("repeated_failure_limit must be at least two")
        self._limit = repeated_failure_limit
        self._fingerprints: Counter[str] = Counter()

    def snapshot(self) -> dict[str, Any]:
        return _ClassifierState(
            repeated_failure_limit=self._limit,
            fingerprints=dict(self._fingerprints),
        ).model_dump(mode="json")

    def restore(self, snapshot: dict[str, Any]) -> None:
        state = _ClassifierState.model_validate(snapshot)
        if any(count < 0 for count in state.fingerprints.values()):
            raise ValueError("feedback fingerprint counts cannot be negative")
        self._limit = state.repeated_failure_limit
        self._fingerprints = Counter(state.fingerprints)

    def classify(
        self,
        result: ValidationResult | None,
        action: ToolCall | None,
        changes: Sequence[str],
    ) -> Feedback:
        if result is None or action is None:
            return Feedback(
                kind=FeedbackKind.INVALID_ACTION,
                message="action or objective validation result is missing",
            )
        fingerprint = self._fingerprint(result, changes)
        kind = self._kind(result)
        if result.passed and action.name in self._CHANGE_ACTIONS and not changes:
            kind = FeedbackKind.NO_PROGRESS
        if kind not in {FeedbackKind.PASS, FeedbackKind.NO_PROGRESS}:
            self._fingerprints[fingerprint] += 1
            if self._fingerprints[fingerprint] >= self._limit:
                kind = FeedbackKind.NO_PROGRESS
        return Feedback(
            kind=kind,
            message=self._message(kind),
            fingerprint=fingerprint,
            retryable=kind
            not in {
                FeedbackKind.NO_PROGRESS,
                FeedbackKind.PASS,
                FeedbackKind.RESOURCE_EXHAUSTED,
            },
            details={"changed_files": list(changes)},
        )

    def _kind(self, result: ValidationResult) -> FeedbackKind:
        if result.timed_out:
            return FeedbackKind.TIMEOUT
        if result.resource_exhausted:
            return FeedbackKind.RESOURCE_EXHAUSTED
        if result.passed:
            return FeedbackKind.PASS
        output = f"{result.stdout}\n{result.stderr}".lower()
        if result.exit_code in {126, 127} or any(
            marker in output for marker in self._ENVIRONMENT_MARKERS
        ):
            return FeedbackKind.ENVIRONMENT_FAILURE
        if result.kind is ValidationKind.TEST:
            return FeedbackKind.TEST_FAILURE
        if result.kind is ValidationKind.LINT:
            return FeedbackKind.LINT_FAILURE
        if result.kind is ValidationKind.TYPE:
            return FeedbackKind.TYPE_FAILURE
        return FeedbackKind.TOOL_ERROR

    @staticmethod
    def _message(kind: FeedbackKind) -> str:
        return {
            FeedbackKind.PASS: "objective validation passed",
            FeedbackKind.NO_PROGRESS: "action made no objective progress",
        }.get(kind, f"objective validation produced {kind.value}")

    @staticmethod
    def _fingerprint(result: ValidationResult, changes: Sequence[str]) -> str:
        value = {
            "changed_files": sorted(set(changes)),
            "command": result.command,
            "exit_code": result.exit_code,
            "kind": result.kind.value,
            "resource_exhausted": result.resource_exhausted,
            "stderr": result.stderr,
            "stdout": result.stdout,
            "timed_out": result.timed_out,
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
