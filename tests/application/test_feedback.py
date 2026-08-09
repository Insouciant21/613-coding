from __future__ import annotations

from uuid import uuid4

import pytest

from coding613.application.feedback import FeedbackClassifier
from coding613.application.validation import (
    ValidationKind,
    ValidationResult,
    ValidationTracker,
)
from coding613.domain.actions import ToolCall
from coding613.domain.models import FeedbackKind


def result(
    kind: ValidationKind,
    exit_code: int | None,
    output: str = "",
    *,
    timed_out: bool = False,
    resource_exhausted: bool = False,
) -> ValidationResult:
    return ValidationResult(
        command=(kind.value,),
        kind=kind,
        exit_code=exit_code,
        stdout=output,
        duration_seconds=0.1,
        timed_out=timed_out,
        resource_exhausted=resource_exhausted,
    )


@pytest.mark.parametrize(
    ("validation", "expected"),
    [
        (result(ValidationKind.TEST, 0), FeedbackKind.PASS),
        (result(ValidationKind.TEST, 1, "1 failed"), FeedbackKind.TEST_FAILURE),
        (result(ValidationKind.LINT, 1, "E501"), FeedbackKind.LINT_FAILURE),
        (result(ValidationKind.TYPE, 1, "error: incompatible"), FeedbackKind.TYPE_FAILURE),
        (
            result(ValidationKind.TEST, 127, "command not found"),
            FeedbackKind.ENVIRONMENT_FAILURE,
        ),
        (result(ValidationKind.TEST, None, timed_out=True), FeedbackKind.TIMEOUT),
        (
            result(ValidationKind.TEST, None, resource_exhausted=True),
            FeedbackKind.RESOURCE_EXHAUSTED,
        ),
    ],
)
def test_feedback_classifies_objective_results(
    validation: ValidationResult, expected: FeedbackKind
) -> None:
    feedback = FeedbackClassifier().classify(
        validation,
        ToolCall(name="run_command", arguments={"argv": list(validation.command)}),
        ("a.py",),
    )
    assert feedback.kind is expected


def test_feedback_detects_invalid_action_and_no_progress() -> None:
    classifier = FeedbackClassifier()
    assert classifier.classify(None, None, ()).kind is FeedbackKind.INVALID_ACTION
    feedback = classifier.classify(
        result(ValidationKind.TEST, 0),
        ToolCall(name="edit_file", arguments={"path": "a.py", "content": "same"}),
        (),
    )
    assert feedback.kind is FeedbackKind.NO_PROGRESS


def test_feedback_treats_delete_without_changed_file_as_no_progress() -> None:
    feedback = FeedbackClassifier().classify(
        result(ValidationKind.TEST, 0),
        ToolCall(name="delete_file", arguments={"path": "missing.py"}),
        (),
    )

    assert feedback.kind is FeedbackKind.NO_PROGRESS


def test_repeated_failure_becomes_no_progress() -> None:
    classifier = FeedbackClassifier(repeated_failure_limit=3)
    failure = result(ValidationKind.TEST, 1, "same failure")
    call = ToolCall(name="run_command", arguments={"argv": ["pytest"]})
    assert classifier.classify(failure, call, ("a.py",)).kind is FeedbackKind.TEST_FAILURE
    assert classifier.classify(failure, call, ("a.py",)).kind is FeedbackKind.TEST_FAILURE
    no_progress = classifier.classify(failure, call, ("a.py",))
    assert no_progress.kind is FeedbackKind.NO_PROGRESS
    assert not no_progress.retryable


def test_repeated_failure_allows_progressive_file_changes() -> None:
    classifier = FeedbackClassifier(repeated_failure_limit=3)
    failure = result(ValidationKind.TEST, 1, "same failure")
    call = ToolCall(name="edit_file", arguments={"path": "next.py", "content": "x"})

    assert classifier.classify(failure, call, ("a.py",)).kind is FeedbackKind.TEST_FAILURE
    assert classifier.classify(failure, call, ("a.py", "b.py")).kind is FeedbackKind.TEST_FAILURE
    assert (
        classifier.classify(failure, call, ("a.py", "b.py", "c.py")).kind
        is FeedbackKind.TEST_FAILURE
    )

    assert (
        classifier.classify(failure, call, ("a.py", "b.py", "c.py")).kind
        is FeedbackKind.TEST_FAILURE
    )
    assert (
        classifier.classify(failure, call, ("a.py", "b.py", "c.py")).kind
        is FeedbackKind.NO_PROGRESS
    )


def test_feedback_classifier_restores_repeated_failure_state() -> None:
    failure = result(ValidationKind.TEST, 1, "same failure")
    call = ToolCall(name="run_command", arguments={"argv": ["pytest"]})
    first = FeedbackClassifier(repeated_failure_limit=3)
    assert first.classify(failure, call, ("a.py",)).kind is FeedbackKind.TEST_FAILURE
    assert first.classify(failure, call, ("a.py",)).kind is FeedbackKind.TEST_FAILURE

    reconstructed = FeedbackClassifier()
    reconstructed.restore(first.snapshot())

    assert (
        reconstructed.classify(failure, call, ("a.py",)).kind
        is FeedbackKind.NO_PROGRESS
    )


def test_validation_tracker_requires_fresh_pass() -> None:
    tracker = ValidationTracker()
    revision = uuid4().hex
    tracker.record(result(ValidationKind.TEST, 0), revision)
    assert tracker.is_fresh_and_passing(revision)
    assert not tracker.is_fresh_and_passing(uuid4().hex)
    tracker.record(result(ValidationKind.TEST, 1, "failed"), revision)
    assert not tracker.is_fresh_and_passing(revision)
