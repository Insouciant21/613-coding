"""Offline wrong-patch, feedback, repair, memory, and guardrail demo."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from coding613.adapters.embeddings.mock import DeterministicEmbedding
from coding613.adapters.llm.mock import ScriptedLLM
from coding613.adapters.storage.lancedb_index import LanceMemoryIndex, VectorEntry
from coding613.adapters.storage.memory import MemoryRepository
from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.adapters.tools.filesystem import FilesystemTools
from coding613.application.approvals import ApprovalService
from coding613.application.budgets import BudgetLimits
from coding613.application.context import ContextAssembler
from coding613.application.feedback import FeedbackClassifier
from coding613.application.loop import AgentLoop, LoopDependencies
from coding613.application.policy import PolicyEngine, RepositoryPolicyConfig
from coding613.application.run_service import RunRequest, RunService
from coding613.application.tool_registry import ToolRegistry
from coding613.application.validation import ValidationKind, ValidationResult
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.models import (
    MemoryEntry,
    MemoryType,
    PermissionMode,
    Project,
    Run,
    RunSummary,
)
from coding613.domain.models_base import DomainModel
from coding613.ports.llm import LLMResponse, ToolDefinition
from coding613.ports.policy import PolicyEffect
from coding613.ports.tools import ToolContext, ToolResult


class CoreFeedbackDemoResult(DomainModel):
    summary: RunSummary
    feedback_observed: bool
    guardrail_blocked: bool
    bypass_command_allowed: bool
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


class _ValidationRequestExecutor:
    """The loop owns validation; this tool only records the explicit request."""

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        return ToolResult(call=call, success=True, output="validation requested")


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
            LLMResponse(
                actions=(
                    ActionEnvelope(
                        action=ToolCall(
                            name="run_validation", arguments={"argv": ["demo-test"]}
                        )
                    ),
                )
            ),
            _edit("def answer():\n    return 2\n"),
            LLMResponse(
                actions=(
                    ActionEnvelope(
                        action=ToolCall(
                            name="run_validation", arguments={"argv": ["demo-test"]}
                        )
                    ),
                )
            ),
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
    registry.register(
        ToolDefinition(
            name="run_validation",
            description="Run the declared validation command",
            input_schema={
                "type": "object",
                "properties": {
                    "argv": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        ),
        _ValidationRequestExecutor(),
    )
    policy = PolicyEngine()
    policy_config = RepositoryPolicyConfig(
        repository_root=workspace,
        validation_commands=(("demo-test",),),
    )
    guardrail = policy.evaluate(
        ToolCall(name="edit_file", arguments={"path": "../escape", "content": "x"}),
        policy_config,
        PermissionMode.BYPASS,
    )
    bypass_command = policy.evaluate(
        ToolCall(name="run_command", arguments={"argv": ["python", "-V"]}),
        policy_config,
        PermissionMode.BYPASS,
    )
    def dependency_factory(run: Run) -> LoopDependencies:
        return LoopDependencies(
            context_builder=context,
            provider=provider,
            tools=registry,
            policy=policy,
            policy_config=policy_config,
            permission_mode=run.permission_mode,
            approvals=ApprovalService(run_id=run.id, store=store),
            events=store,
            iterations=store,
            sessions=store,
            validator=_Validator(target),
            classifier=FeedbackClassifier(),
            budget_limits=BudgetLimits(total_model_calls=5),
            revision=lambda: _revision(target),
            changed_files=lambda: tuple(executor.changed_files),
            clock=lambda: datetime.now(UTC),
        )

    service = RunService(store, AgentLoop(), dependency_factory)
    run = service.create_run(
        RunRequest(
            task="make answer return 2",
            project_id=project.id,
            permission_mode=PermissionMode.BALANCED,
        )
    )
    summary = service.resume(run.id)
    return CoreFeedbackDemoResult(
        summary=summary,
        feedback_observed=(
            any("feedback.test_failure" in context.model_dump_json() for context in provider.contexts)
        ),
        guardrail_blocked=guardrail.effect is PolicyEffect.DENY,
        bypass_command_allowed=bypass_command.effect is PolicyEffect.ALLOW,
        memory_retrieved=bool(provider.contexts[0].metadata.get("memory_ids")),
        changed_file_text=target.read_text(encoding="utf-8"),
    )


def _revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
