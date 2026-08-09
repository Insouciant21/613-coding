from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from coding613.domain.interactive import InteractiveSession
from coding613.domain.models import Run


def test_interactive_session_round_trip_preserves_timestamps() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    updated_at = created_at + timedelta(minutes=1)
    session = InteractiveSession(
        project_id=uuid4(),
        title="Repair tests",
        created_at=created_at,
        updated_at=updated_at,
    )

    restored = InteractiveSession.model_validate_json(session.model_dump_json())

    assert restored == session


def test_interactive_session_rejects_blank_or_overlong_title() -> None:
    with pytest.raises(ValidationError):
        InteractiveSession(project_id=uuid4(), title="   ")
    with pytest.raises(ValidationError):
        InteractiveSession(project_id=uuid4(), title="x" * 201)


def test_old_run_json_loads_without_session_id() -> None:
    old_json = Run(
        project_id=uuid4(),
        task="legacy task",
    ).model_dump_json(exclude={"session_id"})

    restored = Run.model_validate_json(old_json)

    assert restored.session_id is None
