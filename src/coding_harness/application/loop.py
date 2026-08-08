"""Explicit feedback-driven agent state machine owned by 613 Coding."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import ValidationError

from coding_harness.application.approvals import ApprovalService
from coding_harness.application.budgets import BudgetLimits, BudgetTracker
from coding_harness.application.feedback import FeedbackClassifier
from coding_harness.application.policy import PolicyEngine, RepositoryPolicyConfig
from coding_harness.application.tool_registry import ToolRegistry, ToolRegistryError
from coding_harness.application.validation import (
    ValidationResult,
    ValidationTracker,
)
from coding_harness.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding_harness.domain.events import Event
from coding_harness.domain.models import (
    ApprovalStatus,
    Feedback,
    FeedbackKind,
    IterationRecord,
    PermissionMode,
    RunState,
    RunSummary,
    StopReason,
)
from coding_harness.ports.llm import LLMProvider, LLMResponse, ModelContext
from coding_harness.ports.policy import PolicyEffect
from coding_harness.ports.storage import EventStore
from coding_harness.ports.tools import ToolContext, ToolResult


class ContextBuilder(Protocol):
    def build(
        self, run_id: UUID, task: str, events: Sequence[Event]
    ) -> ModelContext: ...


class IterationSink(Protocol):
    def save_iteration(self, iteration: IterationRecord) -> None: ...


class ObjectiveValidator(Protocol):
    def validate(self) -> ValidationResult: ...


@dataclass(frozen=True, slots=True)
class LoopDependencies:
    context_builder: ContextBuilder
    provider: LLMProvider
    tools: ToolRegistry
    policy: PolicyEngine
    policy_config: RepositoryPolicyConfig
    permission_mode: PermissionMode
    approvals: ApprovalService
    events: EventStore
    iterations: IterationSink
    validator: ObjectiveValidator
    classifier: FeedbackClassifier
    budget_limits: BudgetLimits
    revision: Callable[[], str]
    changed_files: Callable[[], Sequence[str]]
    clock: Callable[[], datetime]


@dataclass(slots=True)
class _Session:
    state: RunState
    budget: BudgetTracker
    validation: ValidationTracker = field(default_factory=ValidationTracker)
    iteration: int = 0
    pending_call: ToolCall | None = None
    pending_request: UUID | None = None
    validation_evidence: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[UUID] = field(default_factory=list)
    unresolved_risks: list[str] = field(default_factory=list)
    stop_reason: StopReason | None = None


class AgentLoop:
    def __init__(self) -> None:
        self._sessions: dict[UUID, _Session] = {}
        self._cancelled: set[UUID] = set()

    def cancel(self, run_id: UUID) -> None:
        self._cancelled.add(run_id)
        session = self._sessions.get(run_id)
        if session is not None:
            session.state = RunState.CANCELLED
            session.stop_reason = StopReason.CANCELLED

    def run(
        self,
        run_id: UUID,
        task: str,
        dependencies: LoopDependencies,
    ) -> RunSummary:
        session = self._sessions.setdefault(
            run_id,
            _Session(state=RunState.RUNNING, budget=BudgetTracker(dependencies.budget_limits)),
        )
        if run_id in self._cancelled:
            session.state = RunState.CANCELLED
            session.stop_reason = StopReason.CANCELLED
            self._event(dependencies, run_id, "run.cancelled", {})
            return self._summary(run_id, session, dependencies)
        if session.state.is_terminal:
            return self._summary(run_id, session, dependencies)

        if session.pending_call is not None:
            if session.pending_request is None:
                self._terminal(
                    run_id,
                    session,
                    dependencies,
                    RunState.FAILED,
                    StopReason.PROVIDER_ERROR,
                    "run.invalid_pending_approval",
                )
                return self._summary(run_id, session, dependencies)
            request = dependencies.approvals.get_request(session.pending_request)
            if request.status is ApprovalStatus.PENDING:
                session.state = RunState.WAITING_APPROVAL
                session.stop_reason = StopReason.APPROVAL_REQUIRED
                return self._summary(run_id, session, dependencies)
            pending = session.pending_call
            if request.status is ApprovalStatus.REJECTED:
                return self._terminate_pending_approval(
                    run_id,
                    pending,
                    session,
                    dependencies,
                    FeedbackKind.POLICY_BLOCKED,
                    RunState.FAILED,
                    StopReason.APPROVAL_REJECTED,
                    "approval.rejected",
                )
            if request.status is ApprovalStatus.EXPIRED:
                return self._terminate_pending_approval(
                    run_id,
                    pending,
                    session,
                    dependencies,
                    FeedbackKind.TIMEOUT,
                    RunState.FAILED,
                    StopReason.TIMEOUT,
                    "approval.expired",
                )
            if not dependencies.approvals.consume(pending):
                return self._terminate_pending_approval(
                    run_id,
                    pending,
                    session,
                    dependencies,
                    FeedbackKind.TIMEOUT,
                    RunState.FAILED,
                    StopReason.TIMEOUT,
                    "approval.expired",
                )
            session.pending_call = None
            session.pending_request = None
            session.state = RunState.RUNNING
            session.stop_reason = None
            terminal = self._execute(run_id, task, pending, None, session, dependencies)
            if terminal:
                return self._summary(run_id, session, dependencies)

        while True:
            if run_id in self._cancelled:
                session.state = RunState.CANCELLED
                session.stop_reason = StopReason.CANCELLED
                return self._summary(run_id, session, dependencies)
            budget = session.budget.consume(turns=1, calls=1, seconds=0, cost=0)
            if not budget.allowed:
                self._terminal(
                    run_id,
                    session,
                    dependencies,
                    RunState.FAILED,
                    StopReason.BUDGET_EXHAUSTED,
                    "run.budget_exhausted",
                )
                return self._summary(run_id, session, dependencies)

            self._transition(run_id, session, dependencies, RunState.WAITING_MODEL)
            context = dependencies.context_builder.build(
                run_id, task, dependencies.events.list_for_run(run_id)
            )
            started = time.monotonic()
            try:
                raw_response = dependencies.provider.complete(
                    context, dependencies.tools.definitions()
                )
                response = LLMResponse.model_validate(raw_response)
            except (IndexError, RuntimeError, ValidationError) as error:
                elapsed = time.monotonic() - started
                post_call_budget = session.budget.consume(
                    turns=0, calls=0, seconds=elapsed, cost=0
                )
                if not post_call_budget.allowed:
                    self._terminal(
                        run_id,
                        session,
                        dependencies,
                        RunState.FAILED,
                        StopReason.BUDGET_EXHAUSTED,
                        "run.budget_exhausted",
                    )
                    return self._summary(run_id, session, dependencies)
                feedback = Feedback(
                    kind=FeedbackKind.INVALID_ACTION,
                    message="provider returned an invalid response",
                    details={"error_type": type(error).__name__},
                )
                self._transition(run_id, session, dependencies, RunState.RUNNING)
                self._feedback_event(dependencies, run_id, feedback)
                self._record(
                    run_id, context, None, None, None, feedback, session, dependencies
                )
                continue
            elapsed = time.monotonic() - started
            provider_cost = response.provider_metadata.get("cost", 0)
            cost = float(provider_cost) if isinstance(provider_cost, (int, float)) else 0.0
            post_call_budget = session.budget.consume(
                turns=0, calls=0, seconds=elapsed, cost=cost
            )
            if not post_call_budget.allowed:
                self._terminal(
                    run_id,
                    session,
                    dependencies,
                    RunState.FAILED,
                    StopReason.BUDGET_EXHAUSTED,
                    "run.budget_exhausted",
                )
                return self._summary(run_id, session, dependencies)
            self._transition(run_id, session, dependencies, RunState.RUNNING)

            if not response.actions:
                feedback = Feedback(
                    kind=FeedbackKind.INVALID_ACTION,
                    message="provider response contained no action",
                )
                self._feedback_event(dependencies, run_id, feedback)
                self._record(
                    run_id, context, response, None, None, feedback, session, dependencies
                )
                continue

            continue_model = False
            for envelope in response.actions:
                action = envelope.action
                if isinstance(action, FinishAction):
                    if session.validation.is_fresh_and_passing(dependencies.revision()):
                        self._terminal(
                            run_id,
                            session,
                            dependencies,
                            RunState.COMPLETED,
                            StopReason.SUCCESS,
                            "run.completed",
                        )
                        self._record(
                            run_id,
                            context,
                            response,
                            envelope,
                            None,
                            None,
                            session,
                            dependencies,
                        )
                        return self._summary(run_id, session, dependencies)
                    feedback = Feedback(
                        kind=FeedbackKind.INVALID_ACTION,
                        message="finish requires fresh passing validation",
                    )
                    self._feedback_event(dependencies, run_id, feedback)
                    self._record(
                        run_id,
                        context,
                        response,
                        envelope,
                        None,
                        feedback,
                        session,
                        dependencies,
                    )
                    continue_model = True
                    break

                decision = dependencies.policy.evaluate(
                    action, dependencies.policy_config, dependencies.permission_mode
                )
                if decision.effect is PolicyEffect.DENY:
                    feedback = Feedback(
                        kind=FeedbackKind.POLICY_BLOCKED,
                        message="policy denied action",
                        details={"rule_id": decision.rule_id},
                    )
                    session.unresolved_risks.append(decision.rule_id)
                    self._feedback_event(dependencies, run_id, feedback)
                    self._record(
                        run_id,
                        context,
                        response,
                        envelope,
                        None,
                        feedback,
                        session,
                        dependencies,
                    )
                    continue_model = True
                    break
                if decision.effect is PolicyEffect.ASK:
                    request = dependencies.approvals.request(decision)
                    session.pending_call = action
                    session.pending_request = request.id
                    session.approvals.append(request.id)
                    self._transition(
                        run_id, session, dependencies, RunState.WAITING_APPROVAL
                    )
                    session.stop_reason = StopReason.APPROVAL_REQUIRED
                    self._event(
                        dependencies,
                        run_id,
                        "approval.requested",
                        {"request_id": str(request.id), "rule_id": decision.rule_id},
                    )
                    self._record(
                        run_id,
                        context,
                        response,
                        envelope,
                        None,
                        None,
                        session,
                        dependencies,
                    )
                    return self._summary(run_id, session, dependencies)
                if self._execute(
                    run_id, task, action, (context, response, envelope), session, dependencies
                ):
                    return self._summary(run_id, session, dependencies)
            if continue_model:
                continue

    def _terminate_pending_approval(
        self,
        run_id: UUID,
        pending: ToolCall,
        session: _Session,
        dependencies: LoopDependencies,
        feedback_kind: FeedbackKind,
        state: RunState,
        stop_reason: StopReason,
        event_type: str,
    ) -> RunSummary:
        feedback = Feedback(
            kind=feedback_kind,
            message=event_type.replace(".", " "),
            retryable=False,
            details={"request_id": str(session.pending_request)},
        )
        session.pending_call = None
        session.pending_request = None
        self._feedback_event(dependencies, run_id, feedback)
        self._terminal(
            run_id,
            session,
            dependencies,
            state,
            stop_reason,
            event_type,
        )
        self._record_from_turn(
            run_id,
            None,
            pending,
            tool_result=None,
            feedback=feedback,
            session=session,
            deps=dependencies,
        )
        return self._summary(run_id, session, dependencies)

    def _execute(
        self,
        run_id: UUID,
        task: str,
        call: ToolCall,
        turn: tuple[ModelContext, LLMResponse, ActionEnvelope] | None,
        session: _Session,
        dependencies: LoopDependencies,
    ) -> bool:
        del task
        context = ToolContext(
            run_id=run_id,
            repository_root=dependencies.policy_config.repository_root,
            permission_mode=dependencies.permission_mode,
        )
        try:
            tool_result = dependencies.tools.dispatch(call, context)
        except ToolRegistryError as error:
            feedback = Feedback(
                kind=FeedbackKind.TOOL_ERROR,
                message="tool dispatch failed",
                details={"error_type": type(error).__name__},
            )
            self._feedback_event(dependencies, run_id, feedback)
            self._record_from_turn(
                run_id,
                turn,
                call,
                tool_result=None,
                feedback=feedback,
                session=session,
                deps=dependencies,
            )
            return False
        self._event(
            dependencies,
            run_id,
            "tool.completed",
            tool_result.model_dump(mode="json"),
        )
        if not tool_result.success:
            feedback = Feedback(kind=FeedbackKind.TOOL_ERROR, message="tool execution failed")
            self._feedback_event(dependencies, run_id, feedback)
            self._record_from_turn(
                run_id, turn, call, tool_result, feedback, session, dependencies
            )
            return False

        validation = dependencies.validator.validate()
        revision = dependencies.revision()
        session.validation.record(validation, revision)
        session.validation_evidence.append(validation.model_dump(mode="json"))
        feedback = dependencies.classifier.classify(
            validation, call, dependencies.changed_files()
        )
        self._event(
            dependencies,
            run_id,
            "validation.completed",
            validation.model_dump(mode="json"),
        )
        self._feedback_event(dependencies, run_id, feedback)
        self._record_from_turn(
            run_id,
            turn,
            call,
            tool_result,
            feedback,
            session,
            dependencies,
            validation,
        )
        if feedback.kind is FeedbackKind.NO_PROGRESS:
            self._terminal(
                run_id,
                session,
                dependencies,
                RunState.FAILED,
                StopReason.NO_PROGRESS,
                "run.no_progress",
            )
            return True
        if feedback.kind is FeedbackKind.RESOURCE_EXHAUSTED:
            self._terminal(
                run_id,
                session,
                dependencies,
                RunState.FAILED,
                StopReason.VALIDATION_FAILED,
                "run.resource_exhausted",
            )
            return True
        return False

    def _record_from_turn(
        self,
        run_id: UUID,
        turn: tuple[ModelContext, LLMResponse, ActionEnvelope] | None,
        call: ToolCall,
        tool_result: ToolResult | None,
        feedback: Feedback,
        session: _Session,
        deps: LoopDependencies,
        validation: ValidationResult | None = None,
    ) -> None:
        context, response, envelope = turn or (
            ModelContext(run_id=run_id, task="approved action"),
            None,
            ActionEnvelope(action=call),
        )
        self._record(
            run_id,
            context,
            response,
            envelope,
            tool_result,
            feedback,
            session,
            deps,
            validation,
        )

    def _record(
        self,
        run_id: UUID,
        context: ModelContext,
        response: LLMResponse | None,
        action: ActionEnvelope | None,
        tool_result: ToolResult | None,
        feedback: Feedback | None,
        session: _Session,
        dependencies: LoopDependencies,
        validation: ValidationResult | None = None,
    ) -> None:
        session.iteration += 1
        dependencies.iterations.save_iteration(
            IterationRecord(
                run_id=run_id,
                iteration=session.iteration,
                state_before=RunState.RUNNING,
                state_after=session.state,
                context_summary=context.task,
                model_response=response.model_dump(mode="json") if response else None,
                action=action,
                tool_results=(
                    [tool_result.model_dump(mode="json")] if tool_result is not None else []
                ),
                validation=validation.model_dump(mode="json") if validation else None,
                feedback=feedback,
                stop_reason=session.stop_reason if session.state.is_terminal else None,
                timestamp=dependencies.clock(),
            )
        )

    def _transition(
        self,
        run_id: UUID,
        session: _Session,
        dependencies: LoopDependencies,
        state: RunState,
    ) -> None:
        previous = session.state
        session.state = state
        self._event(
            dependencies,
            run_id,
            "state.transition",
            {"from": previous.value, "to": state.value},
        )

    def _terminal(
        self,
        run_id: UUID,
        session: _Session,
        dependencies: LoopDependencies,
        state: RunState,
        reason: StopReason,
        event_type: str,
    ) -> None:
        self._transition(run_id, session, dependencies, state)
        session.stop_reason = reason
        self._event(dependencies, run_id, event_type, {"stop_reason": reason.value})

    @staticmethod
    def _event(
        dependencies: LoopDependencies,
        run_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        dependencies.events.append(
            Event.new(event_type, run_id, payload, dependencies.clock())
        )

    @classmethod
    def _feedback_event(
        cls, dependencies: LoopDependencies, run_id: UUID, feedback: Feedback
    ) -> None:
        cls._event(
            dependencies,
            run_id,
            f"feedback.{feedback.kind.value}",
            feedback.model_dump(mode="json"),
        )

    @staticmethod
    def _summary(
        run_id: UUID, session: _Session, dependencies: LoopDependencies
    ) -> RunSummary:
        return RunSummary(
            run_id=run_id,
            status=session.state,
            stop_reason=session.stop_reason,
            changed_files=tuple(dependencies.changed_files()),
            validation_evidence=tuple(session.validation_evidence),
            approvals=tuple(session.approvals),
            unresolved_risks=tuple(dict.fromkeys(session.unresolved_risks)),
        )
