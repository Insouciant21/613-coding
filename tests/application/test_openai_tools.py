from __future__ import annotations

import pytest

from coding613.adapters.llm.openai_tools import build_responses_tools
from coding613.config import LLMConfig


def test_responses_tool_catalog_builds_web_search_and_code_interpreter() -> None:
    config = LLMConfig(
        api="responses",
        responses_tools=("web_search", "code_interpreter"),
    )

    definitions = build_responses_tools(config)

    assert [item.name for item in definitions] == ["web_search", "code_interpreter"]
    assert definitions[0].provider_payload == {
        "type": "web_search",
        "search_context_size": "medium",
    }
    assert definitions[1].provider_payload == {
        "type": "code_interpreter",
        "container": {"type": "auto"},
    }


def test_responses_tool_catalog_requires_file_search_vector_store() -> None:
    with pytest.raises(ValueError, match="vector_store_ids"):
        build_responses_tools(
            LLMConfig(api="responses", responses_tools=("file_search",))
        )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("shell", {"type": "shell", "environment": {"type": "local"}}),
        ("local_shell", {"type": "local_shell"}),
        ("apply_patch", {"type": "apply_patch"}),
    ],
)
def test_responses_tool_catalog_builds_client_side_openai_tools(
    name: str, expected: dict[str, object]
) -> None:
    definitions = build_responses_tools(LLMConfig(api="responses", responses_tools=(name,)))

    assert definitions[0].provider_payload == expected


def test_responses_tool_catalog_rejects_invalid_allowed_callers() -> None:
    with pytest.raises(ValueError, match="allowed_callers"):
        build_responses_tools(
            LLMConfig(
                api="responses",
                responses_tools=("shell",),
                responses_tool_options={"shell": {"allowed_callers": [{"bad": True}]}},
            )
        )


@pytest.mark.parametrize(
    "name",
    [
        "tool_search",
        "computer",
        "computer_use_preview",
        "custom",
        "namespace",
        "programmatic_tool_calling",
    ],
)
def test_responses_tool_catalog_rejects_removed_tools(name: str) -> None:
    with pytest.raises(ValueError, match="unsupported Responses tool"):
        build_responses_tools(LLMConfig(api="responses", responses_tools=(name,)))
