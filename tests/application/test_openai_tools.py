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
