"""Offline wrong-patch, feedback, repair, memory, and guardrail demo."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from coding_harness.adapters.embeddings.mock import DeterministicEmbedding
from coding_harness.adapters.llm.mock import ScriptedLLM
from coding_harness.adapters.storage.lancedb_index import LanceMemoryIndex, VectorEntry
from coding_harness.adapters.storage.memory import MemoryRepository
from coding_harness.adapters.storage.sqlite import SqliteEventStore
from coding_harness.adapters.tools.filesystem import FilesystemTools
from coding_harness.application.approvals import ApprovalService
from coding_harness.application.budgets import BudgetLimits
from coding_harness.application.context import ContextAssembler
from coding_harness.application.feedback import FeedbackClassifier
from coding_harness.application.loop import AgentLoop, LoopDependencies
from coding_harness.application.policy import PolicyEngine, RepositoryPolicyConfig
from coding_harness.application.tool_registry import ToolRegistry
from coding_harness.application.validation import ValidationKind, ValidationResult
from coding_harness.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding_harness.domain.models import (
    MemoryEntry,
    MemoryType,
    PermissionMode,
    Project,
    Run,
    RunSummary,
)
from coding_harness.domain.models_base import DomainModel
from coding_harness.ports.llm import LLMResponse, ToolDefinition
from coding_harness.ports.policy import PolicyEffect
from coding_harness.ports.tools import ToolContext, ToolResult


class CoreFeedbackDemoResult(DomainModel):
    summary: RunSummary
    feedback_observed: bool
    guardrail_blocked: bool
    memory_retrieved: bool
    changed_file_text: str


class _EditExecutor:
    def __init__(self, filesystem: FilesystemTools) -> None:
        self._filesystem = filesystem
        self.changed_files: list[str] = []

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        path = str(call.arguments["path"])
        self._filesystem.edit_file(path, str(call.arguments["content"]))
        if path not in self.changed_files:
            self.changed_files.append(path)
        return ToolResult(
            call=call,
            success=True,
            changed_files=tuple(self.changed_files),
        )


class _Validator:
    def __init__(self, target: Path) -> None:
        self._target = target

    def validate(self) -> ValidationResult:
        passed = "return 2" in self._target.read_text(encoding="utf-8")
        return ValidationResult(
            command=("demo-test",),
            kind=ValidationKind.TEST,
            exit_code=0 if passed else 1,
            stdout="1 passed" if passed else "1 failed: expected 2",
            duration_seconds=0.01,
        )


def _edit(content: str) -> LLMResponse:
    return LLMResponse(
        actions=(
            ActionEnvelope(
                action=ToolCall(
                    name="edit_file",
                    arguments={"path": "answer.py", "content": content},
                )
            ),
        )
    )


def run_core_feedback_demo(workspace: Path) -> CoreFeedbackDemoResult:
    workspace = workspace.resolve(strict=True)
    target = workspace / "answer.py"
    target.write_text("def answer():\n    return 0\n", encoding="utf-8")

    database_path = workspace / "demo-state.sqlite"
    store = SqliteEventStore(database_path)
    project = Project(canonical_root=workspace)
    store.create_project(project)
    run = Run(project_id=project.id, task="make answer return 2")
    store.create_run(run)

    memory_repository = MemoryRepository(database_path)
    memory = MemoryEntry(
        project_id=project.id,
        memory_type=MemoryType.PROJECT_CONVENTION,
        text="The answer function must return 2.",
        permission_tags=frozenset({"public"}),
    )
    memory_repository.put(memory)
    embedding = DeterministicEmbedding(dimension=6)
    memory_index = LanceMemoryIndex(workspace / "demo-vectors", dimension=6)
    memory_index.upsert(
        (
            VectorEntry(
                memory_id=memory.id,
                project_id=project.id,
                memory_type=memory.memory_type,
                permission_tags=memory.permission_tags,
                vector=tuple(embedding.embed((memory.text,))[0]),
            ),
        )
    )
    context = ContextAssembler(
        memory_repository,
        memory_index,
        embedding,
        allowed_permission_tags=frozenset({"public"}),
    )

    provider = ScriptedLLM(
        (
            _edit("def answer():\n    return 1\n"),
            _edit("def answer():\n    return 2\n"),
            LLMResponse(actions=(ActionEnvelope(action=FinishAction(summary="fixed")),)),
        )
    )
    filesystem = FilesystemTools(workspace)
    executor = _EditExecutor(filesystem)
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="edit_file",
            description="Edit a repository file",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        ),
        executor,
    )
    policy = PolicyEngine()
    policy_config = RepositoryPolicyConfig(repository_root=workspace)
    guardrail = policy.evaluate(
        ToolCall(name="edit_file", arguments={"path": "../escape", "content": "x"}),
        policy_config,
        PermissionMode.AUTONOMOUS,
    )
    dependencies = LoopDependencies(
        context_builder=context,
        provider=provider,
        tools=registry,
        policy=policy,
        policy_config=policy_config,
        permission_mode=PermissionMode.BALANCED,
        approvals=ApprovalService(run_id=run.id),
        events=store,
        iterations=store,
        validator=_Validator(target),
        classifier=FeedbackClassifier(),
        budget_limits=BudgetLimits(total_model_calls=5),
        revision=lambda: _revision(target),
        changed_files=lambda: tuple(executor.changed_files),
        clock=lambda: datetime.now(UTC),
    )
    summary = AgentLoop().run(run.id, run.task, dependencies)
    return CoreFeedbackDemoResult(
        summary=summary,
        feedback_observed=(
            len(provider.contexts) > 1
            and "feedback.test_failure" in provider.contexts[1].model_dump_json()
        ),
        guardrail_blocked=guardrail.effect is PolicyEffect.DENY,
        memory_retrieved=bool(provider.contexts[0].metadata.get("memory_ids")),
        changed_file_text=target.read_text(encoding="utf-8"),
    )


def _revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
