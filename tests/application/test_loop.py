from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.application.approvals import (
    ApprovalDecision,
    ApprovalService,
    StaleApprovalError,
)
from coding613.application.budgets import BudgetLimits
from coding613.application.feedback import FeedbackClassifier
from coding613.application.loop import AgentLoop, LoopDependencies
from coding613.application.policy import PolicyEngine, RepositoryPolicyConfig
from coding613.application.progress import CancellationToken, ProviderCancelledError
from coding613.application.run_service import RunRequest, RunService
from coding613.application.tool_registry import ToolRegistry
from coding613.application.validation import ValidationKind, ValidationResult
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.events import Event
from coding613.domain.models import (
    ApprovalRequest,
    ApprovalStatus,
    FeedbackKind,
    IterationRecord,
    LoopSession,
    PermissionMode,
    Run,
    RunState,
    RunSummary,
    StopReason,
)
from coding613.ports.llm import (
    LLMResponse,
    ModelContext,
    ModelMessage,
    ToolDefinition,
)
from coding613.ports.progress import ProgressKind, RunProgress
from coding613.ports.tools import ToolContext, ToolResult


class Provider:
    def __init__(self, responses: Sequence[Any]) -> None:
        self.responses = deque(responses)
        self.contexts: list[ModelContext] = []
        self.tool_batches: list[tuple[ToolDefinition, ...]] = []

    def complete(self, context: ModelContext, tools: Sequence[ToolDefinition]) -> Any:
        self.contexts.append(context)
        self.tool_batches.append(tuple(tools))
        return self.responses.popleft()


class RaisingProvider:
    def complete(self, context: ModelContext, tools: Sequence[ToolDefinition]) -> Any:
        raise RuntimeError("provider unavailable")


class StreamingProvider(Provider):
    def __init__(self, responses: Sequence[Any], deltas: Sequence[str]) -> None:
        super().__init__(responses)
        self.deltas = tuple(deltas)

    def complete_stream(self, context, tools, on_text_delta, cancelled):
        self.contexts.append(context)
        self.tool_batches.append(tuple(tools))
        for delta in self.deltas:
            if cancelled():
                raise ProviderCancelledError("cancelled")
            on_text_delta(delta)
        return self.responses.popleft()


class RecordingProgress:
    def __init__(self) -> None:
        self.updates: list[RunProgress] = []

    def publish(self, update: RunProgress) -> None:
        self.updates.append(update)


class ContextBuilder:
    def build(self, run_id: UUID, task: str, events: Sequence[Event]) -> ModelContext:
        return ModelContext(
            run_id=run_id,
            task=task,
            messages=(ModelMessage(role="user", content=task),),
            metadata={"event_types": [event.event_type for event in events]},
        )


class EventRecords:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.iterations: list[IterationRecord] = []
        self.sessions: dict[UUID, LoopSession] = {}
        self.approval_requests: dict[UUID, ApprovalRequest] = {}

    def append(self, event: Event) -> None:
        self.events.append(event)

    def list_for_run(self, run_id: UUID) -> list[Event]:
        return [event for event in self.events if event.run_id == run_id]

    def save_iteration(self, iteration: IterationRecord) -> None:
        self.iterations.append(iteration)

    def save_loop_session(self, session: LoopSession) -> None:
        self.sessions[session.run_id] = session

    def save_iteration_and_session(
        self,
        iteration: IterationRecord,
        session: LoopSession,
        approval_update: ApprovalRequest | None = None,
    ) -> None:
        self.iterations.append(iteration)
        self.sessions[session.run_id] = session
        if approval_update is not None:
            self.approval_requests[approval_update.id] = approval_update

    def get_loop_session(self, run_id: UUID) -> LoopSession | None:
        return self.sessions.get(run_id)

    def save_approval(self, request: ApprovalRequest) -> None:
        self.approval_requests[request.id] = request

    def get_approval(self, request_id: UUID) -> ApprovalRequest | None:
        return self.approval_requests.get(request_id)

    def list_approvals(self, run_id: UUID) -> list[ApprovalRequest]:
        return [
            request
            for request in self.approval_requests.values()
            if request.run_id == run_id
        ]

    def compare_and_set_approval(
        self,
        request_id: UUID,
        expected_status: ApprovalStatus,
        replacement: ApprovalRequest,
    ) -> bool:
        current = self.approval_requests.get(request_id)
        if current is None or current.status is not expected_status:
            return False
        self.approval_requests[request_id] = replacement
        return True


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

    def compare_and_set_run(self, expected: Run, replacement: Run) -> bool:
        if self.runs.get(expected.id) != expected:
            return False
        self.runs[expected.id] = replacement
        return True


class RacingRunRecords(RunRecords):
    def __init__(self) -> None:
        super().__init__()
        self.authoritative: Run | None = None

    def _persist_competing_terminal(self, run_id: UUID) -> None:
        if self.authoritative is not None:
            return
        current = self.runs[run_id]
        self.authoritative = current.model_copy(
            update={
                "state": RunState.COMPLETED,
                "stop_reason": StopReason.SUCCESS,
                "updated_at": current.updated_at + timedelta(seconds=1),
            }
        )
        self.runs[run_id] = self.authoritative

    def update_run(self, run: Run) -> None:
        self._persist_competing_terminal(run.id)
        super().update_run(run)

    def compare_and_set_run(self, expected: Run, replacement: Run) -> bool:
        self._persist_competing_terminal(expected.id)
        return super().compare_and_set_run(expected, replacement)


class StaleRunLoop:
    def __init__(self) -> None:
        self.run_calls = 0
        self.cancel_calls = 0

    def run(
        self,
        run_id: UUID,
        task: str,
        deps: LoopDependencies,
    ) -> RunSummary:
        self.run_calls += 1
        return RunSummary(run_id=run_id, status=RunState.WAITING_APPROVAL)

    def cancel(
        self,
        run_id: UUID,
        task: str,
        deps: LoopDependencies,
    ) -> RunSummary:
        self.cancel_calls += 1
        return RunSummary(
            run_id=run_id,
            status=RunState.CANCELLED,
            stop_reason=StopReason.CANCELLED,
        )

    def get_summary(
        self,
        run_id: UUID,
        deps: LoopDependencies,
    ) -> RunSummary:
        return RunSummary(run_id=run_id, status=RunState.WAITING_APPROVAL)


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


class ReadExecutor:
    def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        del context
        return ToolResult(call=call, success=True, output="read")


class Validator:
    def __init__(self, results: Sequence[ValidationResult]) -> None:
        self.results = deque(results)
        self.calls = 0

    def validate(self) -> ValidationResult:
        self.calls += 1
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
    approvals = ApprovalService(run_id=uuid4(), store=records)
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
        sessions=records,
        validator=validator,
        classifier=FeedbackClassifier(),
        budget_limits=budget or BudgetLimits(total_model_calls=10),
        revision=lambda: "|".join(files) or "clean",
        changed_files=lambda: tuple(files),
        clock=lambda: datetime.now(UTC),
    )
    return deps, records, executor, approvals


def test_bare_run_service_defaults_unspecified_mode_to_balanced(tmp_path: Path) -> None:
    deps, _, _, _ = dependencies(tmp_path, Provider(()), Validator(()))
    records = RunRecords()
    service = RunService(records, AgentLoop(), lambda run: deps)

    created = service.create_run(RunRequest(task="use library default"))

    assert created.permission_mode is PermissionMode.BALANCED


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


def test_loop_publishes_streamed_progress_at_owned_boundaries(tmp_path: Path) -> None:
    provider = StreamingProvider(
        (
            response(ToolCall(name="edit_file", arguments={"path": "a.py", "content": "ok"})),
            response(FinishAction(summary="done")),
        ),
        ("working",),
    )
    deps, _, _, _ = dependencies(tmp_path, provider, Validator((validation(0),)))
    progress = RecordingProgress()
    deps = replace(deps, progress=progress, cancellation=CancellationToken())

    summary = AgentLoop().run(uuid4(), "stream", deps)

    assert summary.status is RunState.COMPLETED
    kinds = [update.kind for update in progress.updates]
    assert ProgressKind.STATE in kinds
    assert ProgressKind.TEXT_DELTA in kinds
    assert ProgressKind.TOOL_STARTED in kinds
    assert ProgressKind.TOOL_FINISHED in kinds
    assert ProgressKind.VALIDATION_STARTED in kinds
    assert ProgressKind.VALIDATION_FINISHED in kinds
    tool_started = next(
        update for update in progress.updates if update.kind is ProgressKind.TOOL_STARTED
    )
    assert tool_started.payload["arguments"] == {"path": "a.py", "content": "ok"}
    tool_finished = next(
        update for update in progress.updates if update.kind is ProgressKind.TOOL_FINISHED
    )
    assert tool_finished.payload["changed_files"] == ("a.py",)
    assert [update.text for update in progress.updates if update.kind is ProgressKind.TEXT_DELTA] == [
        "working",
        "working",
    ]


def test_provider_cancellation_pauses_without_persisting_token_deltas(tmp_path: Path) -> None:
    token = CancellationToken()

    class CancellingProvider(StreamingProvider):
        def complete_stream(self, context, tools, on_text_delta, cancelled):
            on_text_delta("partial")
            token.cancel()
            raise ProviderCancelledError("cancelled")

    deps, records, _, _ = dependencies(
        tmp_path, CancellingProvider((response(FinishAction(summary="done")),), ()), Validator(())
    )
    progress = RecordingProgress()
    deps = replace(deps, progress=progress, cancellation=token)
    run_id = uuid4()

    summary = AgentLoop().run(run_id, "pause", deps)

    assert summary.status is RunState.PAUSED
    assert summary.stop_reason is None
    assert [update.text for update in progress.updates if update.kind is ProgressKind.TEXT_DELTA] == ["partial"]
    assert all("token" not in event.event_type for event in records.events)


def test_loop_exposes_finish_tool_to_provider(tmp_path: Path) -> None:
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
    deps, _, _, _ = dependencies(tmp_path, provider, Validator((validation(0),)))

    summary = AgentLoop().run(uuid4(), "finish after verification", deps)

    finish = next(tool for tool in provider.tool_batches[0] if tool.name == "finish")
    assert finish.input_schema == {
        "type": "object",
        "properties": {"summary": {"type": "string", "minLength": 1}},
        "required": ["summary"],
        "additionalProperties": False,
    }
    assert summary.status is RunState.COMPLETED


def test_model_tool_batch_runs_objective_validation_once(tmp_path: Path) -> None:
    provider = Provider(
        (
            LLMResponse(
                actions=(
                    ActionEnvelope(action=ToolCall(name="list_files", arguments={})),
                    ActionEnvelope(
                        action=ToolCall(
                            name="read_file", arguments={"path": "harness.toml"}
                        )
                    ),
                )
            ),
            response(
                ToolCall(
                    name="edit_file",
                    arguments={"path": "answer.txt", "content": "done"},
                )
            ),
            response(FinishAction(summary="done")),
        )
    )
    validator = Validator((validation(1, "foundation missing"), validation(0)))
    deps, _, _, _ = dependencies(tmp_path, provider, validator)
    read_executor = ReadExecutor()
    for name, schema in (
        ("list_files", {"type": "object", "properties": {}}),
        (
            "read_file",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
    ):
        deps.tools.register(
            ToolDefinition(name=name, description=name, input_schema=schema),
            read_executor,
        )

    summary = AgentLoop().run(uuid4(), "inspect before editing", deps)

    assert summary.status is RunState.COMPLETED
    assert validator.calls == 2


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
    assert records.iterations[0].schema_validation is not None
    assert not records.iterations[0].schema_validation.valid
    assert records.iterations[0].policy_decision is None


def test_invalid_tool_arguments_are_rejected_before_policy(tmp_path: Path) -> None:
    provider = Provider(
        (
            response(ToolCall(name="edit_file", arguments={"path": "a.py"})),
        )
    )
    deps, records, executor, _ = dependencies(
        tmp_path,
        provider,
        Validator(()),
        budget=BudgetLimits(total_model_calls=1),
    )

    summary = AgentLoop().run(uuid4(), "invalid schema", deps)

    invalid = records.iterations[0]
    assert summary.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert invalid.feedback is not None
    assert invalid.feedback.kind is FeedbackKind.INVALID_ACTION
    assert invalid.schema_validation is not None
    assert not invalid.schema_validation.valid
    assert invalid.policy_decision is None
    assert not executor.calls


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
    assert summary.resource_usage.model_calls == 2
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
    cancelled = loop.cancel(cancelled_id, "cancelled", deps)
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
        deps, _, _, _ = dependencies(
            tmp_path,
            provider,
            Validator((validation(0),)),
            mode=PermissionMode.STRICT,
        )
        approvals = ApprovalService(run_id=run.id, store=records)
        deps = replace(
            deps,
            approvals=approvals,
            events=records,
            iterations=records,
            sessions=records,
        )
        dependency_map[run.id] = deps
        return deps

    service = RunService(records, loop, factory)
    run = service.create_run(RunRequest(task="fix", permission_mode=PermissionMode.STRICT))
    paused = service.resume(run.id)
    assert paused.status is RunState.WAITING_APPROVAL
    assert service.get_approval(paused.approvals[-1]) == records.get_approval(paused.approvals[-1])
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

    pending_cancel = service.create_run(
        RunRequest(task="cancel pending", permission_mode=PermissionMode.STRICT)
    )
    pending_summary = service.resume(pending_cancel.id)
    pending_request = pending_summary.approvals[-1]
    assert service.cancel(pending_cancel.id).status is RunState.CANCELLED
    with pytest.raises(StaleApprovalError):
        service.approve(pending_request)
    assert records.get_approval(pending_request).status is ApprovalStatus.REJECTED  # type: ignore[union-attr]


def test_run_service_pause_persists_nonterminal_paused_state(tmp_path: Path) -> None:
    store = RunRecords()
    deps, records, _, _ = dependencies(tmp_path, Provider(()), Validator(()))
    service = RunService(store, AgentLoop(), lambda run: deps)
    run = service.create_run(RunRequest(task="pause before execution"))

    summary = service.pause(run.id)

    assert summary.status is RunState.PAUSED
    assert summary.stop_reason is None
    assert store.get_run(run.id).state is RunState.PAUSED  # type: ignore[union-attr]
    assert records.get_loop_session(run.id).state is RunState.PAUSED  # type: ignore[union-attr]


@pytest.mark.parametrize("operation", ("resume", "cancel"))
def test_run_service_returns_authoritative_terminal_summary_after_status_race(
    tmp_path: Path,
    operation: str,
) -> None:
    store = RacingRunRecords()

    def factory(run: Run) -> LoopDependencies:
        deps, _, _, _ = dependencies(tmp_path, Provider(()), Validator(()))
        return deps

    service = RunService(store, StaleRunLoop(), factory)  # type: ignore[arg-type]
    run = service.create_run(RunRequest(task="race status persistence"))

    summary = service.resume(run.id) if operation == "resume" else service.cancel(run.id)

    assert store.authoritative is not None
    assert store.get_run(run.id) == store.authoritative
    assert summary.status is RunState.COMPLETED
    assert summary.stop_reason is StopReason.SUCCESS


@pytest.mark.parametrize("operation", ("resume", "cancel"))
def test_run_service_terminal_operations_return_authoritative_state_without_reentry(
    tmp_path: Path,
    operation: str,
) -> None:
    store = RunRecords()
    terminal = Run(
        task="immutable terminal",
        state=RunState.COMPLETED,
        stop_reason=StopReason.SUCCESS,
    )
    store.create_run(terminal)
    loop = StaleRunLoop()
    service = RunService(
        store,
        loop,  # type: ignore[arg-type]
        lambda run: dependencies(tmp_path, Provider(()), Validator(()))[0],
    )

    summary = service.resume(terminal.id) if operation == "resume" else service.cancel(terminal.id)

    assert summary.status is RunState.COMPLETED
    assert summary.stop_reason is StopReason.SUCCESS
    assert loop.run_calls == 0
    assert loop.cancel_calls == 0
    assert store.get_run(terminal.id) == terminal


@pytest.mark.parametrize("operation", ("resume", "cancel"))
def test_run_service_preserves_unknown_run_errors(
    tmp_path: Path,
    operation: str,
) -> None:
    store = RunRecords()
    service = RunService(
        store,
        AgentLoop(),
        lambda run: dependencies(tmp_path, Provider(()), Validator(()))[0],
    )

    with pytest.raises(KeyError, match="unknown run"):
        getattr(service, operation)(uuid4())


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
            run_id=run.id, store=records, clock=now, ttl=timedelta(seconds=1)
        )
        return replace(
            deps,
            approvals=approvals,
            events=records,
            iterations=records,
            sessions=records,
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


def test_sqlite_reconstruction_approves_and_resumes_exact_pending_action(
    tmp_path: Path,
) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    executed: list[ToolCall] = []

    def service_with(
        responses: Sequence[Any], total_model_calls: int = 1
    ) -> RunService:
        def factory(run: Run) -> LoopDependencies:
            deps, _, executor, _ = dependencies(
                tmp_path,
                Provider(responses),
                Validator((validation(0),)),
                mode=run.permission_mode,
                budget=BudgetLimits(total_model_calls=total_model_calls),
            )
            original_execute = executor.execute

            def execute(call: ToolCall, context: ToolContext) -> ToolResult:
                executed.append(call)
                return original_execute(call, context)

            executor.execute = execute  # type: ignore[method-assign]
            approvals = ApprovalService(run_id=run.id, store=store)
            return replace(
                deps,
                approvals=approvals,
                events=store,
                iterations=store,
                sessions=store,
            )

        return RunService(store, AgentLoop(), factory)

    initial = service_with(
        (
            response(
                ToolCall(
                    name="edit_file", arguments={"path": "a.py", "content": "approved"}
                )
            ),
        ),
        total_model_calls=5,
    )
    run = initial.create_run(
        RunRequest(task="fix", permission_mode=PermissionMode.STRICT)
    )
    paused = initial.resume(run.id)
    request_id = paused.approvals[-1]

    resolver = service_with(())
    resolver.approve(request_id)
    assert resolver.get_summary(run.id).status is RunState.WAITING_APPROVAL

    resumed = service_with((response(FinishAction(summary="done")),))
    completed = resumed.resume(run.id)

    assert completed.status is RunState.COMPLETED
    assert [call.arguments["content"] for call in executed] == ["approved"]
    assert completed.validation_evidence
    assert completed.resource_usage.model_calls == 2
    assert completed.resource_usage.agent_turns == 2
    assert completed.changed_files == ("a.py",)
    assert resumed.get_summary(run.id) == completed
    assert store.get_run(run.id).state is RunState.COMPLETED  # type: ignore[union-attr]
    persisted_approval = store.get_approval(request_id)
    assert persisted_approval is not None
    assert persisted_approval.status is ApprovalStatus.CONSUMED
    assert [record.iteration for record in store.list_iterations(run.id)] == [1, 2, 3]
    snapshot = store.get_loop_session(run.id)
    assert snapshot is not None
    assert snapshot.pending_call is None
    assert snapshot.pending_request is None
    assert snapshot.validation_result is not None
    assert snapshot.validation_revision == "a.py"
    assert snapshot.iteration == 3


def test_sqlite_reconstruction_rejects_pending_action(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.db")

    def make_service(responses: Sequence[Any]) -> RunService:
        def factory(run: Run) -> LoopDependencies:
            deps, _, _, _ = dependencies(
                tmp_path,
                Provider(responses),
                Validator(()),
                mode=run.permission_mode,
            )
            return replace(
                deps,
                approvals=ApprovalService(run_id=run.id, store=store),
                events=store,
                iterations=store,
                sessions=store,
            )

        return RunService(store, AgentLoop(), factory)

    first = make_service(
        (
            response(
                ToolCall(name="edit_file", arguments={"path": "a.py", "content": "x"})
            ),
        )
    )
    run = first.create_run(RunRequest(task="reject", permission_mode=PermissionMode.STRICT))
    request_id = first.resume(run.id).approvals[-1]

    make_service(()).reject(request_id)
    rejected = make_service(()).resume(run.id)

    assert rejected.status is RunState.FAILED
    assert rejected.stop_reason is StopReason.APPROVAL_REJECTED


def test_reconstructed_approval_rechecks_current_hard_and_repository_policy(
    tmp_path: Path,
) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    executed: list[ToolCall] = []

    def make_service(*, writes_allowed: bool, responses: Sequence[Any]) -> RunService:
        def factory(run: Run) -> LoopDependencies:
            deps, _, executor, _ = dependencies(
                tmp_path,
                Provider(responses),
                Validator(()),
                mode=run.permission_mode,
            )
            original_execute = executor.execute

            def execute(call: ToolCall, context: ToolContext) -> ToolResult:
                executed.append(call)
                return original_execute(call, context)

            executor.execute = execute  # type: ignore[method-assign]
            return replace(
                deps,
                policy_config=RepositoryPolicyConfig(
                    repository_root=tmp_path, allow_writes=writes_allowed
                ),
                approvals=ApprovalService(run_id=run.id, store=store),
                events=store,
                iterations=store,
                sessions=store,
            )

        return RunService(store, AgentLoop(), factory)

    first = make_service(
        writes_allowed=True,
        responses=(
            response(
                ToolCall(name="edit_file", arguments={"path": "a.py", "content": "x"})
            ),
        ),
    )
    run = first.create_run(RunRequest(task="policy", permission_mode=PermissionMode.STRICT))
    request_id = first.resume(run.id).approvals[-1]

    reconstructed = make_service(writes_allowed=False, responses=())
    reconstructed.approve(request_id)
    summary = reconstructed.resume(run.id)

    assert summary.status is RunState.FAILED
    assert "config.writes_disabled" in summary.unresolved_risks
    assert not executed


def test_terminal_iterations_capture_schema_policy_and_real_transitions(
    tmp_path: Path,
) -> None:
    provider = Provider(
        (
            response(
                ToolCall(name="edit_file", arguments={"path": "", "content": "same"})
            ),
        )
    )
    deps, records, _, _ = dependencies(
        tmp_path, provider, Validator((validation(0),)), changed_files=[]
    )

    summary = AgentLoop().run(uuid4(), "edit", deps)

    terminal = records.iterations[-1]
    assert summary.stop_reason is StopReason.NO_PROGRESS
    assert terminal.state_before is RunState.RUNNING
    assert terminal.state_after is RunState.FAILED
    assert terminal.stop_reason is StopReason.NO_PROGRESS
    assert terminal.schema_validation is not None
    assert terminal.schema_validation.valid
    assert terminal.policy_decision is not None
    assert terminal.policy_decision.effect == "allow"
    assert terminal.context_summary != "edit"
    assert "message_count" in terminal.context_summary


def test_budget_and_cancel_paths_persist_terminal_iterations(tmp_path: Path) -> None:
    provider = Provider(
        (
            response(
                ToolCall(
                    name="edit_file", arguments={"path": "../escape", "content": "x"}
                )
            ),
        )
    )
    deps, records, _, _ = dependencies(
        tmp_path,
        provider,
        Validator(()),
        budget=BudgetLimits(total_model_calls=1),
    )
    budgeted = AgentLoop().run(uuid4(), "unsafe", deps)
    assert budgeted.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert records.iterations[-1].state_after is RunState.FAILED
    assert records.iterations[-1].stop_reason is StopReason.BUDGET_EXHAUSTED

    run_id = uuid4()
    cancel_records = EventRecords()
    cancel_deps = replace(deps, events=cancel_records, iterations=cancel_records)
    loop = AgentLoop()
    cancelled = loop.cancel(run_id, "cancel", cancel_deps)
    assert cancelled.status is RunState.CANCELLED
    assert cancel_records.iterations[-1].state_before is RunState.RUNNING
    assert cancel_records.iterations[-1].state_after is RunState.CANCELLED


def test_cancel_does_not_mutate_terminal_run(tmp_path: Path) -> None:
    store = RunRecords()

    def factory(run: Run) -> LoopDependencies:
        deps, _, _, _ = dependencies(
            tmp_path,
            Provider(
                (
                    response(
                        ToolCall(
                            name="edit_file",
                            arguments={"path": "a.py", "content": "ok"},
                        )
                    ),
                    response(FinishAction(summary="done")),
                )
            ),
            Validator((validation(0),)),
        )
        return replace(deps, events=store, iterations=store, sessions=store)

    service = RunService(store, AgentLoop(), factory)
    run = service.create_run(RunRequest(task="complete"))
    completed = service.resume(run.id)
    after_cancel = RunService(store, AgentLoop(), factory).cancel(run.id)

    assert completed.status is RunState.COMPLETED
    assert after_cancel == completed
    assert store.get_run(run.id).state is RunState.COMPLETED  # type: ignore[union-attr]


def test_finish_rejects_unresolved_policy_feedback_at_same_revision(tmp_path: Path) -> None:
    provider = Provider(
        (
            response(
                ToolCall(name="edit_file", arguments={"path": "a.py", "content": "ok"})
            ),
            response(
                ToolCall(
                    name="edit_file", arguments={"path": "../escape", "content": "x"}
                )
            ),
            response(FinishAction(summary="must not finish")),
        )
    )
    deps, records, _, _ = dependencies(
        tmp_path,
        provider,
        Validator((validation(0),)),
        budget=BudgetLimits(total_model_calls=3),
    )

    summary = AgentLoop().run(uuid4(), "safe finish", deps)

    assert summary.status is RunState.FAILED
    assert summary.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert "hard.repository_escape" in summary.unresolved_risks
    assert FeedbackKind.POLICY_BLOCKED in summary.completion_blockers
    assert [event.event_type for event in records.events].count("feedback.invalid_action") == 1


def test_passing_validation_does_not_clear_unresolved_policy_risk(
    tmp_path: Path,
) -> None:
    provider = Provider(
        (
            response(
                ToolCall(name="edit_file", arguments={"path": "a.py", "content": "ok"})
            ),
            response(
                ToolCall(
                    name="edit_file", arguments={"path": "../escape", "content": "x"}
                )
            ),
            response(
                ToolCall(name="edit_file", arguments={"path": "b.py", "content": "ok"})
            ),
            response(FinishAction(summary="risk remains")),
        )
    )
    deps, _, _, _ = dependencies(
        tmp_path,
        provider,
        Validator((validation(0), validation(0))),
        budget=BudgetLimits(total_model_calls=4),
    )

    summary = AgentLoop().run(uuid4(), "do not bypass risk", deps)

    assert summary.status is RunState.FAILED
    assert summary.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert "hard.repository_escape" in summary.unresolved_risks
    assert FeedbackKind.POLICY_BLOCKED in summary.completion_blockers


@pytest.mark.parametrize(
    ("boundary", "expected_stop"),
    (
        ("context", "dependency_error"),
        ("provider", "provider_error"),
        ("policy", "dependency_error"),
        ("tool", "dependency_error"),
        ("validator", "dependency_error"),
        ("revision", "dependency_error"),
        ("classifier", "dependency_error"),
    ),
)
def test_dependency_exceptions_become_terminal_summaries(
    tmp_path: Path, boundary: str, expected_stop: str
) -> None:
    action = ToolCall(name="edit_file", arguments={"path": "a.py", "content": "ok"})
    provider: Any = Provider((response(action),))
    deps, records, _, _ = dependencies(
        tmp_path, provider, Validator((validation(0),))
    )

    class RaisesContext:
        def build(self, run_id: UUID, task: str, events: Sequence[Event]) -> ModelContext:
            raise RuntimeError("context failed")

    class RaisesPolicy:
        def evaluate(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("policy failed")

    class RaisesTool:
        def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
            raise RuntimeError("tool failed")

    class RaisesValidator:
        def validate(self) -> ValidationResult:
            raise RuntimeError("validator failed")

    class RaisesClassifier:
        def classify(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("classifier failed")

    if boundary == "context":
        deps = replace(deps, context_builder=RaisesContext())
    elif boundary == "provider":
        deps = replace(deps, provider=RaisingProvider())
    elif boundary == "policy":
        deps = replace(deps, policy=RaisesPolicy())
    elif boundary == "tool":
        registration = ToolRegistry()
        registration.register(deps.tools.definitions()[0], RaisesTool())
        deps = replace(deps, tools=registration)
    elif boundary == "validator":
        deps = replace(deps, validator=RaisesValidator())
    elif boundary == "revision":
        deps = replace(
            deps,
            revision=lambda: (_ for _ in ()).throw(RuntimeError("revision failed")),
        )
    else:
        deps = replace(deps, classifier=RaisesClassifier())

    summary = AgentLoop().run(uuid4(), "boundary", deps)

    assert summary.status is RunState.FAILED
    assert summary.stop_reason is not None
    assert summary.stop_reason.value == expected_stop
    assert records.iterations[-1].state_after is RunState.FAILED
    assert records.iterations[-1].feedback is not None
    assert records.iterations[-1].feedback.kind in {
        FeedbackKind.ENVIRONMENT_FAILURE,
        FeedbackKind.TOOL_ERROR,
    }


@pytest.mark.parametrize(
    "boundary",
    ("context", "policy", "tool", "validator", "classifier"),
)
def test_malformed_dependency_results_become_terminal_summaries(
    tmp_path: Path, boundary: str
) -> None:
    action = ToolCall(name="edit_file", arguments={"path": "a.py", "content": "ok"})
    deps, records, _, _ = dependencies(
        tmp_path, Provider((response(action),)), Validator((validation(0),))
    )

    class MalformedContext:
        def build(self, run_id: UUID, task: str, events: Sequence[Event]) -> Any:
            return {"unexpected": True}

    class MalformedPolicy:
        def evaluate(self, *args: Any, **kwargs: Any) -> Any:
            return {"unexpected": True}

    class MalformedTool:
        def execute(self, call: ToolCall, context: ToolContext) -> Any:
            return {"unexpected": True}

    class MalformedValidator:
        def validate(self) -> Any:
            return {"unexpected": True}

    class MalformedClassifier:
        def classify(self, *args: Any, **kwargs: Any) -> Any:
            return {"unexpected": True}

    if boundary == "context":
        deps = replace(deps, context_builder=MalformedContext())
    elif boundary == "policy":
        deps = replace(deps, policy=MalformedPolicy())
    elif boundary == "tool":
        registry = ToolRegistry()
        registry.register(deps.tools.definitions()[0], MalformedTool())
        deps = replace(deps, tools=registry)
    elif boundary == "validator":
        deps = replace(deps, validator=MalformedValidator())
    else:
        deps = replace(deps, classifier=MalformedClassifier())

    summary = AgentLoop().run(uuid4(), "malformed boundary", deps)

    assert summary.status is RunState.FAILED
    assert summary.stop_reason is StopReason.DEPENDENCY_ERROR
    assert records.iterations[-1].state_after is RunState.FAILED
