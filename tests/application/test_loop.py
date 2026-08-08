from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from coding_harness.application.approvals import ApprovalDecision, ApprovalService
from coding_harness.application.budgets import BudgetLimits
from coding_harness.application.feedback import FeedbackClassifier
from coding_harness.application.loop import AgentLoop, LoopDependencies
from coding_harness.application.policy import PolicyEngine, RepositoryPolicyConfig
from coding_harness.application.run_service import RunRequest, RunService
from coding_harness.application.tool_registry import ToolRegistry
from coding_harness.application.validation import ValidationKind, ValidationResult
from coding_harness.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding_harness.domain.events import Event
from coding_harness.domain.models import (
    IterationRecord,
    PermissionMode,
    Run,
    RunState,
    StopReason,
)
from coding_harness.ports.llm import LLMResponse, ModelContext, ToolDefinition
from coding_harness.ports.tools import ToolContext, ToolResult


class Provider:
    def __init__(self, responses: Sequence[Any]) -> None:
        self.responses = deque(responses)
        self.contexts: list[ModelContext] = []

    def complete(self, context: ModelContext, tools: Sequence[ToolDefinition]) -> Any:
        self.contexts.append(context)
        return self.responses.popleft()


class ContextBuilder:
    def build(self, run_id: UUID, task: str, events: Sequence[Event]) -> ModelContext:
        return ModelContext(
            run_id=run_id,
            task=task,
            metadata={"event_types": [event.event_type for event in events]},
        )


class EventRecords:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.iterations: list[IterationRecord] = []

    def append(self, event: Event) -> None:
        self.events.append(event)

    def list_for_run(self, run_id: UUID) -> list[Event]:
        return [event for event in self.events if event.run_id == run_id]

    def save_iteration(self, iteration: IterationRecord) -> None:
        self.iterations.append(iteration)


class RunRecords(EventRecords):
    def __init__(self) -> None:
        super().__init__()
        self.runs: dict[UUID, Run] = {}

    def create_run(self, run: Run) -> None:
        self.runs[run.id] = run

    def get_run(self, run_id: UUID) -> Run | None:
        return self.runs.get(run_id)

    def update_run(self, run: Run) -> None:
        self.runs[run.id] = run


class Executor:
    def __init__(self, changed_files: list[str]) -> None:
        self.changed_files = changed_files
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        self.calls.append(call)
        path = str(call.arguments.get("path", ""))
        if path and path not in self.changed_files:
            self.changed_files.append(path)
        return ToolResult(call=call, success=True, changed_files=tuple(self.changed_files))


class Validator:
    def __init__(self, results: Sequence[ValidationResult]) -> None:
        self.results = deque(results)

    def validate(self) -> ValidationResult:
        return self.results.popleft()


def validation(exit_code: int, output: str = "") -> ValidationResult:
    return ValidationResult(
        command=("pytest",),
        kind=ValidationKind.TEST,
        exit_code=exit_code,
        stdout=output,
        duration_seconds=0.1,
    )


def response(action: ToolCall | FinishAction) -> LLMResponse:
    return LLMResponse(actions=(ActionEnvelope(action=action),))


def dependencies(
    tmp_path: Path,
    provider: Provider,
    validator: Validator,
    *,
    mode: PermissionMode = PermissionMode.BALANCED,
    budget: BudgetLimits | None = None,
    changed_files: list[str] | None = None,
) -> tuple[LoopDependencies, EventRecords, Executor, ApprovalService]:
    records = EventRecords()
    files = changed_files if changed_files is not None else []
    executor = Executor(files)
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="edit_file",
            description="Edit file",
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
    approvals = ApprovalService(run_id=uuid4())
    deps = LoopDependencies(
        context_builder=ContextBuilder(),
        provider=provider,
        tools=registry,
        policy=PolicyEngine(),
        policy_config=RepositoryPolicyConfig(repository_root=tmp_path),
        permission_mode=mode,
        approvals=approvals,
        events=records,
        iterations=records,
        validator=validator,
        classifier=FeedbackClassifier(),
        budget_limits=budget or BudgetLimits(total_model_calls=10),
        revision=lambda: "|".join(files) or "clean",
        changed_files=lambda: tuple(files),
        clock=lambda: datetime.now(UTC),
    )
    return deps, records, executor, approvals


def test_failure_feedback_drives_repair_and_fresh_finish(tmp_path: Path) -> None:
    provider = Provider(
        (
            response(ToolCall(name="edit_file", arguments={"path": "a.py", "content": "bad"})),
            response(ToolCall(name="edit_file", arguments={"path": "a.py", "content": "good"})),
            response(FinishAction(summary="done")),
        )
    )
    deps, records, executor, _ = dependencies(
        tmp_path, provider, Validator((validation(1, "1 failed"), validation(0)))
    )
    summary = AgentLoop().run(uuid4(), "fix test", deps)
    assert summary.status is RunState.COMPLETED
    assert summary.stop_reason is StopReason.SUCCESS
    assert len(executor.calls) == 2
    assert "feedback.test_failure" in provider.contexts[1].metadata["event_types"]
    assert records.iterations[-1].state_after is RunState.COMPLETED


def test_invalid_response_and_premature_finish_are_repaired(tmp_path: Path) -> None:
    provider = Provider(
        (
            {"not": "a response"},
            response(FinishAction(summary="too early")),
            response(ToolCall(name="edit_file", arguments={"path": "a.py", "content": "ok"})),
            response(FinishAction(summary="done")),
        )
    )
    deps, records, _, _ = dependencies(tmp_path, provider, Validator((validation(0),)))
    summary = AgentLoop().run(uuid4(), "fix", deps)
    assert summary.status is RunState.COMPLETED
    assert [event.event_type for event in records.events].count("feedback.invalid_action") == 2


def test_strict_approval_pauses_then_resumes_exact_action(tmp_path: Path) -> None:
    provider = Provider(
        (
            response(ToolCall(name="edit_file", arguments={"path": "a.py", "content": "ok"})),
            response(FinishAction(summary="done")),
        )
    )
    loop = AgentLoop()
    run_id = uuid4()
    deps, _, executor, approvals = dependencies(
        tmp_path,
        provider,
        Validator((validation(0),)),
        mode=PermissionMode.STRICT,
    )
    paused = loop.run(run_id, "fix", deps)
    assert paused.status is RunState.WAITING_APPROVAL
    assert paused.stop_reason is StopReason.APPROVAL_REQUIRED
    approvals.resolve(paused.approvals[-1], ApprovalDecision.APPROVE)
    completed = loop.run(run_id, "fix", deps)
    assert completed.status is RunState.COMPLETED
    assert len(executor.calls) == 1


def test_policy_denial_is_feedback_and_budget_stops_loop(tmp_path: Path) -> None:
    denied = response(
        ToolCall(name="edit_file", arguments={"path": "../escape", "content": "x"})
    )
    provider = Provider((denied, denied, denied))
    deps, records, executor, _ = dependencies(
        tmp_path,
        provider,
        Validator(()),
        budget=BudgetLimits(total_model_calls=2),
    )
    summary = AgentLoop().run(uuid4(), "unsafe", deps)
    assert summary.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert not executor.calls
    assert "feedback.policy_blocked" in [event.event_type for event in records.events]


def test_provider_cost_budget_stops_before_tool_execution(tmp_path: Path) -> None:
    costly = response(
        ToolCall(name="edit_file", arguments={"path": "a.py", "content": "x"})
    ).model_copy(update={"provider_metadata": {"cost": 2.0}})
    provider = Provider((costly,))
    deps, _, executor, _ = dependencies(
        tmp_path,
        provider,
        Validator(()),
        budget=BudgetLimits(provider_cost=1.0),
    )
    summary = AgentLoop().run(uuid4(), "costly", deps)
    assert summary.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert not executor.calls


def test_no_progress_and_cancel_are_terminal(tmp_path: Path) -> None:
    provider = Provider(
        (response(ToolCall(name="edit_file", arguments={"path": "", "content": "same"})),)
    )
    deps, _, _, _ = dependencies(
        tmp_path, provider, Validator((validation(0),)), changed_files=[]
    )
    loop = AgentLoop()
    no_progress = loop.run(uuid4(), "edit", deps)
    assert no_progress.stop_reason is StopReason.NO_PROGRESS

    cancelled_id = uuid4()
    loop.cancel(cancelled_id)
    cancelled = loop.run(cancelled_id, "cancelled", deps)
    assert cancelled.status is RunState.CANCELLED
    assert cancelled.stop_reason is StopReason.CANCELLED


def test_run_service_creates_approves_resumes_and_cancels(tmp_path: Path) -> None:
    records = RunRecords()
    loop = AgentLoop()
    dependency_map: dict[UUID, LoopDependencies] = {}
    factory_calls = 0

    def factory(run: Run) -> LoopDependencies:
        nonlocal factory_calls
        factory_calls += 1
        provider = Provider(
            (
                response(
                    ToolCall(
                        name="edit_file", arguments={"path": "a.py", "content": "ok"}
                    )
                ),
                response(FinishAction(summary="done")),
            )
        )
        deps, _, _, approvals = dependencies(
            tmp_path,
            provider,
            Validator((validation(0),)),
            mode=PermissionMode.STRICT,
        )
        approvals.run_id = run.id
        deps = replace(deps, events=records, iterations=records)
        dependency_map[run.id] = deps
        return deps

    service = RunService(records, loop, factory)
    run = service.create_run(RunRequest(task="fix", permission_mode=PermissionMode.STRICT))
    paused = service.resume(run.id)
    assert paused.status is RunState.WAITING_APPROVAL
    service.approve(paused.approvals[-1])
    completed = service.resume(run.id)
    assert completed.status is RunState.COMPLETED
    assert service.get_summary(run.id) == completed
    assert factory_calls == 1

    rejected_run = service.create_run(RunRequest(task="reject", permission_mode=PermissionMode.STRICT))
    rejected_pause = service.resume(rejected_run.id)
    service.reject(rejected_pause.approvals[-1])
    rejected = service.resume(rejected_run.id)
    assert rejected.status is RunState.FAILED
    assert rejected.stop_reason is StopReason.APPROVAL_REJECTED

    cancelled_run = service.create_run(RunRequest(task="cancel"))
    cancelled = service.cancel(cancelled_run.id)
    assert cancelled.status is RunState.CANCELLED


def test_expired_approval_terminates_instead_of_waiting_forever(tmp_path: Path) -> None:
    records = RunRecords()
    loop = AgentLoop()
    approval_time = datetime.now(UTC)

    def now() -> datetime:
        return approval_time

    def factory(run: Run) -> LoopDependencies:
        provider = Provider(
            (
                response(
                    ToolCall(
                        name="edit_file", arguments={"path": "a.py", "content": "ok"}
                    )
                ),
            )
        )
        deps, _, _, _ = dependencies(
            tmp_path,
            provider,
            Validator(()),
            mode=PermissionMode.STRICT,
        )
        approvals = ApprovalService(
            run_id=run.id, clock=now, ttl=timedelta(seconds=1)
        )
        return replace(
            deps,
            approvals=approvals,
            events=records,
            iterations=records,
        )

    service = RunService(records, loop, factory)
    run = service.create_run(RunRequest(task="expire", permission_mode=PermissionMode.STRICT))
    paused = service.resume(run.id)
    assert paused.status is RunState.WAITING_APPROVAL

    approval_time += timedelta(seconds=2)
    expired = service.resume(run.id)
    assert expired.status is RunState.FAILED
    assert expired.stop_reason is StopReason.TIMEOUT
    assert "approval.expired" in [event.event_type for event in records.events]
