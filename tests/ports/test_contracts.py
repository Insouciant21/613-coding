from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from coding_harness.domain.actions import ActionEnvelope, ToolCall
from coding_harness.domain.events import Event
from coding_harness.domain.models import PermissionMode
from coding_harness.ports.embeddings import EmbeddingProvider
from coding_harness.ports.llm import (
    LLMProvider,
    LLMResponse,
    ModelContext,
    ModelMessage,
    ToolDefinition,
)
from coding_harness.ports.policy import PolicyDecision, PolicyEffect, PolicyEvaluator
from coding_harness.ports.storage import EventStore
from coding_harness.ports.tools import ToolContext, ToolExecutor, ToolResult


class FakeLLM:
    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.calls: list[tuple[ModelContext, tuple[ToolDefinition, ...]]] = []

    def complete(
        self, context: ModelContext, tools: Sequence[ToolDefinition]
    ) -> LLMResponse:
        self.calls.append((context, tuple(tools)))
        return self.response


class FakeEmbeddings:
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(index), float(len(text))] for index, text in enumerate(texts)]


class FakeTools:
    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        return ToolResult(call=call, success=True, output=str(context.repository_root))


class InMemoryEvents:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def append(self, event: Event) -> None:
        self.events.append(event)

    def list_for_run(self, run_id: UUID) -> list[Event]:
        return [event for event in self.events if event.run_id == run_id]


class AllowPolicy:
    def evaluate(self, call: ToolCall, context: ToolContext) -> PolicyDecision:
        return PolicyDecision(effect=PolicyEffect.ALLOW, rule_id="test.allow", reason=call.name)


def test_llm_protocol_preserves_validated_context_and_tools() -> None:
    response = LLMResponse(
        actions=(ActionEnvelope(action=ToolCall(name="read_file", arguments={"path": "a.py"})),)
    )
    provider: LLMProvider = FakeLLM(response)
    context = ModelContext(
        run_id=uuid4(),
        task="inspect a.py",
        messages=(ModelMessage(role="user", content="inspect a.py"),),
    )
    definition = ToolDefinition(
        name="read_file",
        description="Read a repository file",
        input_schema={"type": "object"},
    )
    assert provider.complete(context, (definition,)) == response
    assert isinstance(provider, FakeLLM)
    assert provider.calls == [(context, (definition,))]


def test_embedding_and_tool_protocols_preserve_order_and_types(tmp_path: Path) -> None:
    embeddings: EmbeddingProvider = FakeEmbeddings()
    assert embeddings.embed(("a", "longer")) == [[0.0, 1.0], [1.0, 6.0]]

    tools: ToolExecutor = FakeTools()
    call = ToolCall(name="pwd", arguments={})
    context = ToolContext(
        run_id=uuid4(), repository_root=tmp_path, permission_mode=PermissionMode.BALANCED
    )
    result = tools.execute(call, context)
    assert result.call is call
    assert result.success


def test_event_store_preserves_append_order_per_run() -> None:
    store: EventStore = InMemoryEvents()
    first_run = uuid4()
    second_run = uuid4()
    timestamp = datetime.now(UTC)
    expected = [
        Event.new("run.started", first_run, {"n": 1}, timestamp),
        Event.new("run.updated", first_run, {"n": 2}, timestamp),
    ]
    store.append(expected[0])
    store.append(Event.new("run.started", second_run, {}, timestamp))
    store.append(expected[1])
    assert store.list_for_run(first_run) == expected


def test_policy_protocol_returns_typed_decision(tmp_path: Path) -> None:
    policy: PolicyEvaluator = AllowPolicy()
    call = ToolCall(name="read_file", arguments={"path": "a.py"})
    context = ToolContext(
        run_id=uuid4(), repository_root=tmp_path, permission_mode=PermissionMode.STRICT
    )
    decision = policy.evaluate(call, context)
    assert decision.effect is PolicyEffect.ALLOW
    assert decision.rule_id == "test.allow"
