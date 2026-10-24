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
    assert call["system"] == [{"type": "text", "text": "system instructions",
                               "cache_control": {"type": "ephemeral"}}]
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


def test_anthropic_counts_all_input_tokens_including_cache() -> None:
    provider = AnthropicLLM(None, "claude-sonnet", FakeClient())
    result = provider.complete(ModelContext(run_id=uuid4(), task="inspect"), ())
    usage = result.provider_metadata["usage"]
    assert usage["prompt_tokens"] == 32
    assert usage["prompt_cache_hit_tokens"] == 10
    assert usage["prompt_cache_miss_tokens"] == 22
    assert usage["cache_creation_input_tokens"] == 2
    assert usage["total_tokens"] == 40


def test_anthropic_thinking_respects_per_turn_output_limit() -> None:
    client = FakeClient()
    provider = AnthropicLLM(None, "claude-sonnet", client,
                            max_output_tokens=128000, reasoning_effort="high")
    provider.complete(ModelContext(run_id=uuid4(), task="inspect",
                                   metadata={"max_output_tokens": 2048}), ())
    request = client.messages.calls[0]
    assert request["max_tokens"] == 2048
    assert request["thinking"] == {"type": "enabled", "budget_tokens": 1024}


def test_anthropic_caches_stable_system_without_hoisting_repair_tail() -> None:
    from coding613.ports.llm import ModelMessage

    client = FakeClient()
    provider = AnthropicLLM(None, "claude-sonnet", client)
    provider.complete(ModelContext(run_id=uuid4(), task="inspect", messages=(
        ModelMessage(role="system", content="stable instructions"),
        ModelMessage(role="user", content="inspect"),
        ModelMessage(role="system", content="Read the conflicted file now"),
    )), ())
    request = client.messages.calls[0]
    assert request["system"] == [{"type": "text", "text": "stable instructions",
                                  "cache_control": {"type": "ephemeral"}}]
    assert "Read the conflicted file now" in str(request["messages"][-1])


def test_anthropic_history_cache_breakpoint_excludes_changing_ledger() -> None:
    from coding613.ports.llm import ModelMessage

    client = FakeClient()
    provider = AnthropicLLM(None, "claude-sonnet", client)
    for count in (1, 2):
        provider.complete(ModelContext(run_id=uuid4(), task="inspect", messages=(
            ModelMessage(role="system", content="stable instructions"),
            ModelMessage(role="user", content="inspect"),
            ModelMessage(role="user", content="Event tool.completed: stable source"),
            ModelMessage(role="user", content=f"Run ledger (state): {count}"),
        )), ())
    first, second = client.messages.calls
    assert first["messages"][:2] == second["messages"][:2]
    assert first["messages"][1]["content"] == [{
        "type": "text", "text": "Event tool.completed: stable source",
        "cache_control": {"type": "ephemeral"},
    }]
    assert first["messages"][2]["content"] == "Run ledger (state): 1"
