from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from coding613.adapters.llm.anthropic import AnthropicLLM
from coding613.domain.actions import ActionEnvelope, ToolCall
from coding613.ports.llm import ModelContext, ToolDefinition


class FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="inspect "),
                SimpleNamespace(type="tool_use", id="call-1", name="list_files", input={}),
            ],
            usage=SimpleNamespace(
                input_tokens=20,
                output_tokens=8,
                cache_read_input_tokens=10,
                cache_creation_input_tokens=2,
            ),
        )


class FakeClient:
    def __init__(self) -> None:
        self.messages = FakeMessages()

    def close(self) -> None:
        return None


def test_anthropic_messages_adapter_maps_tools_reasoning_and_usage() -> None:
    client = FakeClient()
    provider = AnthropicLLM(
        "https://api.anthropic.com",
        "claude-sonnet",
        client,
        max_output_tokens=4096,
        reasoning_effort="high",
    )

    response = provider.complete(
        ModelContext(
            run_id=uuid4(),
            task="inspect",
            metadata={"system_prompt": "system instructions"},
        ),
        (ToolDefinition(name="list_files", description="List files", input_schema={"type": "object"}),),
    )

    call = client.messages.calls[0]
    assert call["model"] == "claude-sonnet"
    assert call["system"] == "system instructions"
    assert call["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert call["tools"] == [
        {"name": "list_files", "description": "List files", "input_schema": {"type": "object"}}
    ]
    assert response.content == "inspect "
    assert response.actions == (
        ActionEnvelope(action=ToolCall(name="list_files", arguments={})),
    )
    assert response.provider_metadata["usage"]["prompt_cache_hit_tokens"] == 10


def test_anthropic_adapter_accepts_provider_specific_reasoning_effort() -> None:
    client = FakeClient()
    provider = AnthropicLLM(
        "https://api.anthropic.com",
        "claude-sonnet",
        client,
        max_output_tokens=4096,
        reasoning_effort="xhigh",
    )

    provider.complete(ModelContext(run_id=uuid4(), task="inspect"), ())

    assert client.messages.calls[0]["thinking"] == {
        "type": "enabled",
        "budget_tokens": 2048,
    }
