from __future__ import annotations

from uuid import uuid4

import pytest

from coding613.domain.conversation import PromptRequest, RunOptions


def test_prompt_request_rejects_conflicting_session_selection() -> None:
    with pytest.raises(ValueError, match="continue_latest"):
        PromptRequest(
            project_id=uuid4(),
            text="inspect",
            session_id=uuid4(),
            continue_latest=True,
        )


def test_run_options_reject_overlapping_tool_filters() -> None:
    with pytest.raises(ValueError, match="both allowed and disallowed"):
        RunOptions(
            allowed_tools=frozenset({"read_file"}),
            disallowed_tools=frozenset({"read_file"}),
        )


def test_run_options_reject_empty_prompt_overrides() -> None:
    with pytest.raises(ValueError):
        RunOptions(system_prompt="")
    with pytest.raises(ValueError):
        RunOptions(append_system_prompt="")
