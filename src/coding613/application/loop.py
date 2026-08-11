# Dependency ports may raise arbitrary runtime exceptions that must become domain states.
# ruff: noqa: BLE001
"""Explicit feedback-driven agent state machine owned by 613 Coding."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError

from coding613.application.approvals import (
    ApprovalError,
    ApprovalService,
)
from coding613.application.budgets import BudgetLimits, BudgetTracker
from coding613.application.feedback import FeedbackClassifier
from coding613.application.policy import PolicyEngine, RepositoryPolicyConfig
from coding613.application.progress import (
    CancellationToken,
    ProviderCancelledError,
    complete_with_progress,
)
from coding613.application.resources import (
    ResourceProfile,
    TaskBudgetRequest,
    resource_profile,
)
from coding613.application.tool_registry import ToolRegistry, ToolRegistryError
from coding613.application.validation import ValidationResult, ValidationTracker
from coding613.domain.actions import ActionEnvelope, FinishAction, ToolCall
from coding613.domain.events import Event, redact_payload
from coding613.domain.models import (
    ApprovalRequest,
    ApprovalStatus,
    Feedback,
    FeedbackKind,
    IterationRecord,
    LoopSession,
    PermissionMode,
    PolicyDecisionEvidence,
    RunState,
    RunSummary,
    SchemaValidationEvidence,
    StopReason,
)
from coding613.domain.permissions import ToolFilter
from coding613.domain.redaction import redact_text
from coding613.ports.llm import (
    LLMProvider,
    LLMResponse,
    ModelContext,
    RetryableProviderError,
    ToolDefinition,
)
from coding613.ports.policy import PolicyDecision, PolicyEffect
from coding613.ports.progress import NullProgressSink, ProgressKind, ProgressSink, RunProgress
from coding613.ports.storage import EventStore, LoopSessionStore
from coding613.ports.tools import ToolContext, ToolResult

_FINISH_TOOL = ToolDefinition(
    name="finish",
    description=(
        "Finish the task only after objective validation is fresh and passing. "
        "Put the complete user-facing final answer in summary; do not use planning narration."
    ),
    input_schema={
        "type": "object",
        "properties": {"summary": {"type": "string", "minLength": 1}},
        "required": ["summary"],
        "additionalProperties": False,
    },
)

_TASK_BUDGET_TOOL = ToolDefinition(
    name="set_task_budget",
    description=(
        "Classify the task before repository work and select standard or complex "
        "resource limits (standard targets 16,384 output tokens; complex targets 128,000). "
        "The configured provider ceiling may clamp the target. Call this once at the start "
        "of a run."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "difficulty": {
                "type": "string",
                "enum": ["standard", "complex"],
            }
        },
        "required": ["difficulty"],
        "additionalProperties": False,
    },
)

_READ_ONLY_TOOLS = frozenset({"git_diff", "list_files", "read_file", "search_files"})
_WRITE_TOOLS = frozenset(
    {"apply_patch", "delete_file", "edit_file", "write_file", "install_dependency"}
)
# Writes only invalidate freshness. Validation is requested explicitly by the model
# or once at the task-end ``finish`` boundary; a write must not launch a subprocess.
_VALIDATION_TRIGGER_TOOLS = frozenset({"run_validation"})
# A text-only response can be a transient planning turn, but repeating it is
# deterministic evidence that the provider is not driving the tool loop.
_MAX_NO_ACTION_STREAK = 2
# Codex's Responses provider defaults to five retries after the initial call,
# surfaced as reconnects 1/5 ... 5/5.  Keep this as a retry-count limit: the
# sixth provider failure is terminal.
_MAX_PROVIDER_RETRIES = 5
_TOOL_PROGRESS_OUTPUT_LIMIT = 10_000_000
_MAX_PARALLEL_READ_TOOLS = 4
# A stale patch must be regenerated from current file content.  Permit one
# deterministic repair turn, then stop rather than rendering an endless stream
# of identical failed tool calls (the failure pattern shown in the TUI report).
_PATCH_CONFLICT_REPEAT_LIMIT = 2


def _progress_text(value: str, limit: int = _TOOL_PROGRESS_OUTPUT_LIMIT) -> str:
    safe = redact_text(value)
    if len(safe) <= limit:
        return safe
    return f"{safe[:limit]}\n... output truncated ({len(safe) - limit} characters omitted)"


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
    sessions: LoopSessionStore
    validator: ObjectiveValidator
    classifier: FeedbackClassifier
    budget_limits: BudgetLimits
    revision: Callable[[], str]
    changed_files: Callable[[], Sequence[str]]
    clock: Callable[[], datetime]
    progress: ProgressSink = field(default_factory=NullProgressSink)
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    tool_filter: ToolFilter = field(default_factory=ToolFilter)
    # Provider-hosted tools are definitions only; their calls are executed by
    # the Responses provider and therefore never enter ToolRegistry.dispatch.
    provider_tools: tuple[ToolDefinition, ...] = ()
    max_output_tokens: int = 128_000


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
    completion_blockers: list[FeedbackKind] = field(default_factory=list)
    stop_reason: StopReason | None = None
    changed_files: list[str] = field(default_factory=list)
    context_summary: str = ""
    classifier_state: dict[str, Any] | None = None
    force_write: bool = False
    no_action_streak: int = 0
    provider_error_streak: int = 0
    resource_profile: ResourceProfile | None = None

    @classmethod
    def restore(
        cls,
        snapshot: LoopSession,
        limits: BudgetLimits,
        configured_max_output_tokens: int = 128_000,
    ) -> _Session:
        restored_limits = (
            BudgetLimits.model_validate_json(
                json.dumps(snapshot.budget_limits, separators=(",", ":"))
            )
            if snapshot.budget_limits is not None
            else limits
        )
        result = (
            ValidationResult.model_validate_json(
                json.dumps(snapshot.validation_result, separators=(",", ":"))
            )
            if snapshot.validation_result is not None
            else None
        )
        return cls(
            state=snapshot.state,
            budget=BudgetTracker(restored_limits, snapshot.resource_usage),
            validation=ValidationTracker(result, snapshot.validation_revision),
            iteration=snapshot.iteration,
            pending_call=snapshot.pending_call,
            pending_request=snapshot.pending_request,
            validation_evidence=list(snapshot.validation_evidence),
            approvals=list(snapshot.approvals),
            unresolved_risks=list(snapshot.unresolved_risks),
            completion_blockers=list(snapshot.completion_blockers),
            stop_reason=snapshot.stop_reason,
            changed_files=list(snapshot.changed_files),
            context_summary=snapshot.context_summary,
            classifier_state=snapshot.classifier_state,
            force_write=snapshot.force_write,
            no_action_streak=snapshot.no_action_streak,
            provider_error_streak=snapshot.provider_error_streak,
            resource_profile=(
                resource_profile(
                    snapshot.resource_profile,
                    configured_max_output_tokens=configured_max_output_tokens,
                )
                if snapshot.resource_profile
                else None
            ),
        )

    def snapshot(self, run_id: UUID) -> LoopSession:
        result = self.validation.result
        return LoopSession(
            run_id=run_id,
            state=self.state,
            stop_reason=self.stop_reason,
            iteration=self.iteration,
            pending_call=self.pending_call,
            pending_request=self.pending_request,
            validation_result=result.model_dump(mode="json") if result else None,
            validation_revision=self.validation.revision,
            validation_evidence=tuple(self.validation_evidence),
            approvals=tuple(self.approvals),
            unresolved_risks=tuple(self.unresolved_risks),
            completion_blockers=tuple(self.completion_blockers),
            resource_usage=self.budget.usage,
            budget_limits=self.budget.limits.model_dump(mode="json"),
            classifier_state=self.classifier_state,
            changed_files=tuple(self.changed_files),
            context_summary=self.context_summary,
            resource_profile=self.resource_profile.name if self.resource_profile else None,
            max_output_tokens=(
                self.resource_profile.max_output_tokens if self.resource_profile else None
            ),
            force_write=self.force_write,
            no_action_streak=self.no_action_streak,
            provider_error_streak=self.provider_error_streak,
        )


class AgentLoop:
    def run(
        self,
        run_id: UUID,
        task: str,
        dependencies: LoopDependencies,
    ) -> RunSummary:
        session = self._load(run_id, dependencies)
        if session.state.is_terminal:
            return self._summary(run_id, session)

        if session.pending_call is not None:
            pending_summary = self._resume_pending(run_id, task, session, dependencies)
            if pending_summary is not None:
                return pending_summary

        while True:
            state_before = session.state
            budget = session.budget.consume(
                turns=1,
                calls=1,
                seconds=0,
                cost=0,
                commit_on_reject=False,
            )
            if not budget.allowed:
                return self._terminal_without_action(
                    run_id,
                    task,
                    session,
                    dependencies,
                    state_before,
                    StopReason.BUDGET_EXHAUSTED,
                    "run.budget_exhausted",
                    FeedbackKind.RESOURCE_EXHAUSTED,
                    "model-call budget exhausted",
                )

            self._transition(run_id, session, dependencies, RunState.WAITING_MODEL)
            try:
                context = ModelContext.model_validate(
                    dependencies.context_builder.build(
                        run_id, task, dependencies.events.list_for_run(run_id)
                    )
                )
            except Exception as error:
                return self._dependency_failure(
                    run_id,
                    session,
                    dependencies,
                    boundary="context",
                    error=error,
                    state_before=RunState.WAITING_MODEL,
                )
            context = self._with_resource_metadata(context, session, dependencies)
            session.context_summary = self._summarize_context(context)

            try:
                repository_definitions = tuple(
                    ToolDefinition.model_validate(definition)
                    for definition in dependencies.tools.definitions()
                    if (
                        definition.name == "finish"
                        or (
                            definition.name not in dependencies.tool_filter.disallowed
                            and (
                                not dependencies.tool_filter.allowed
                                or definition.name in dependencies.tool_filter.allowed
                            )
                        )
                    )
                    if not (session.force_write and definition.name in _READ_ONLY_TOOLS)
                )
                budget_definition = (
                    (_TASK_BUDGET_TOOL,) if session.resource_profile is None else ()
                )
                hosted_definitions = tuple(
                    definition
                    for definition in dependencies.provider_tools
                    if (
                        definition.name not in dependencies.tool_filter.disallowed
                        and (
                            not dependencies.tool_filter.allowed
                            or definition.name in dependencies.tool_filter.allowed
                        )
                    )
                )
                definitions = (
                    budget_definition
                    + repository_definitions
                    + hosted_definitions
                    + (_FINISH_TOOL,)
                )
            except Exception as error:
                return self._dependency_failure(
                    run_id,
                    session,
                    dependencies,
                    boundary="tool",
                    error=error,
                    state_before=RunState.WAITING_MODEL,
                    context=context,
                )

            started = time.monotonic()
            try:
                raw_response = complete_with_progress(
                    dependencies.provider,
                    context,
                    definitions,
                    lambda delta: self._publish(
                        run_id,
                        ProgressKind.TEXT_DELTA,
                        dependencies,
                        text=delta,
                    ),
                    dependencies.cancellation.is_cancelled,
                )
            except ProviderCancelledError:
                elapsed = time.monotonic() - started
                session.budget.consume(turns=0, calls=0, seconds=elapsed, cost=0)
                self._transition(run_id, session, dependencies, RunState.PAUSED)
                session.stop_reason = None
                self._record(
                    run_id,
                    session,
                    dependencies,
                    state_before=RunState.WAITING_MODEL,
                    context=context,
                )
                return self._summary(run_id, session)
            except Exception as error:
                elapsed = time.monotonic() - started
                post_budget = session.budget.consume(
                    turns=0, calls=0, seconds=elapsed, cost=0
                )
                if isinstance(error, RetryableProviderError):
                    session.provider_error_streak += 1
                if (
                    isinstance(error, RetryableProviderError)
                    and post_budget.allowed
                    and session.provider_error_streak <= _MAX_PROVIDER_RETRIES
                ):
                    self._transition(
                        run_id, session, dependencies, RunState.RUNNING
                    )
                    feedback = Feedback(
                        kind=FeedbackKind.ENVIRONMENT_FAILURE,
                        message=(
                            "provider dependency failed; retrying in the same run "
                            f"(retry {session.provider_error_streak}/"
                            f"{_MAX_PROVIDER_RETRIES})"
                        ),
                        retryable=True,
                        details={
                            "boundary": "provider",
                            "error_type": type(error).__name__,
                            "retry_count": session.provider_error_streak,
                            "max_retries": _MAX_PROVIDER_RETRIES,
                        },
                    )
                    self._feedback_event(dependencies, run_id, feedback)
                    self._record(
                        run_id,
                        session,
                        dependencies,
                        state_before=RunState.WAITING_MODEL,
                        context=context,
                        feedback=feedback,
                    )
                    continue
                return self._dependency_failure(
                    run_id,
                    session,
                    dependencies,
                    boundary="provider",
                    error=error,
                    state_before=RunState.WAITING_MODEL,
                    context=context,
                )

            elapsed = time.monotonic() - started
            try:
                response = LLMResponse.model_validate(raw_response)
            except ValidationError as error:
                post_budget = session.budget.consume(
                    turns=0, calls=0, seconds=elapsed, cost=0
                )
                if not post_budget.allowed:
                    return self._terminal_without_action(
                        run_id,
                        task,
                        session,
                        dependencies,
                        RunState.WAITING_MODEL,
                        StopReason.BUDGET_EXHAUSTED,
                        "run.budget_exhausted",
                        FeedbackKind.RESOURCE_EXHAUSTED,
                        "provider budget exhausted",
                        context=context,
                    )
                self._transition(run_id, session, dependencies, RunState.RUNNING)
                feedback = Feedback(
                    kind=FeedbackKind.INVALID_ACTION,
                    message="provider returned an invalid response",
                    details={"error_type": type(error).__name__},
                )
                self._block(session, feedback.kind)
                self._feedback_event(dependencies, run_id, feedback)
                self._record(
                    run_id,
                    session,
                    dependencies,
                    state_before=state_before,
                    context=context,
                    feedback=feedback,
                    schema_validation=SchemaValidationEvidence(
                        valid=False,
                        target="model_response",
                        error_type=type(error).__name__,
                    ),
                )
                continue

            session.provider_error_streak = 0
            provider_cost = response.provider_metadata.get("cost", 0)
            cost = float(provider_cost) if isinstance(provider_cost, (int, float)) else 0.0
            post_budget = session.budget.consume(
                turns=0, calls=0, seconds=elapsed, cost=cost
            )
            if not post_budget.allowed:
                return self._terminal_without_action(
                    run_id,
                    task,
                    session,
                    dependencies,
                    RunState.WAITING_MODEL,
                    StopReason.BUDGET_EXHAUSTED,
                    "run.budget_exhausted",
                    FeedbackKind.RESOURCE_EXHAUSTED,
                    "provider budget exhausted",
                    context=context,
                    response=response,
                )
            self._transition(run_id, session, dependencies, RunState.RUNNING)
            self._resolve_blocker(session, FeedbackKind.INVALID_ACTION)

            if session.resource_profile is None:
                selected = next(
                    (
                        envelope.action
                        for envelope in response.actions
                        if isinstance(envelope.action, ToolCall)
                        and envelope.action.name == _TASK_BUDGET_TOOL.name
                    ),
                    None,
                )
                if selected is None:
                    # Mocks and older providers may not know the harness control
                    # tool. Keep the loop usable with a conservative standard
                    # profile while giving capable models the chance to select a
                    # larger allocation on their first response.
                    self._select_resource_profile(
                        run_id,
                        session,
                        dependencies,
                        resource_profile(
                            "standard",
                            configured_max_output_tokens=dependencies.max_output_tokens,
                        ),
                        event_type="resource_profile.defaulted",
                    )

            if not response.actions:
                session.no_action_streak += 1
                if session.no_action_streak >= _MAX_NO_ACTION_STREAK:
                    return self._terminal_without_action(
                        run_id,
                        task,
                        session,
                        dependencies,
                        RunState.RUNNING,
                        StopReason.NO_PROGRESS,
                        "run.no_progress",
                        FeedbackKind.NO_PROGRESS,
                        "provider returned no tool action twice; stopping to avoid a repeated model loop",
                        context=context,
                        response=response,
                    )
                feedback = Feedback(
                    kind=FeedbackKind.INVALID_ACTION,
                    message=(
                        "provider response contained no tool action; call a repository tool "
                        "or finish when the task is complete"
                    ),
                )
                self._block(session, feedback.kind)
                self._feedback_event(dependencies, run_id, feedback)
                self._record(
                    run_id,
                    session,
                    dependencies,
                    state_before=state_before,
                    context=context,
                    response=response,
                    feedback=feedback,
                    schema_validation=SchemaValidationEvidence(
                        valid=True, target="model_response"
                    ),
                )
                continue

            session.no_action_streak = 0
            continue_model = False
            validation_action_index = max(
                (
                    action_index
                    for action_index, envelope in enumerate(response.actions)
                    if isinstance(envelope.action, ToolCall)
                    and envelope.action.name in _VALIDATION_TRIGGER_TOOLS
                ),
                default=-1,
            )
            parallel_reads = self._prepare_parallel_read_batch(
                response.actions, run_id, dependencies
            )
            if parallel_reads is not None:
                if self._execute_read_only_batch(
                    run_id,
                    parallel_reads,
                    (context, response),
                    session,
                    dependencies,
                ):
                    return self._summary(run_id, session)
                continue
            for action_index, envelope in enumerate(response.actions):
                action = envelope.action
                if isinstance(action, ToolCall) and action.name == _TASK_BUDGET_TOOL.name:
                    if session.resource_profile is not None:
                        feedback = Feedback(
                            kind=FeedbackKind.INVALID_ACTION,
                            message="task difficulty was already selected for this run",
                            details={"tool": _TASK_BUDGET_TOOL.name},
                        )
                        self._block(session, feedback.kind)
                        self._feedback_event(dependencies, run_id, feedback)
                        self._record(
                            run_id,
                            session,
                            dependencies,
                            state_before=session.state,
                            context=context,
                            response=response,
                            action=envelope,
                            feedback=feedback,
                            schema_validation=SchemaValidationEvidence(
                                valid=False, target="tool_call"
                            ),
                        )
                        continue_model = True
                        break
                    try:
                        budget_request = TaskBudgetRequest.model_validate(action.arguments)
                    except ValidationError as error:
                        feedback = Feedback(
                            kind=FeedbackKind.INVALID_ACTION,
                            message="set_task_budget arguments failed schema validation",
                            details={
                                "tool": _TASK_BUDGET_TOOL.name,
                                "error_type": type(error).__name__,
                            },
                        )
                        self._block(session, feedback.kind)
                        self._feedback_event(dependencies, run_id, feedback)
                        self._record(
                            run_id,
                            session,
                            dependencies,
                            state_before=session.state,
                            context=context,
                            response=response,
                            action=envelope,
                            feedback=feedback,
                            schema_validation=SchemaValidationEvidence(
                                valid=False, target="tool_call"
                            ),
                        )
                        continue_model = True
                        break
                    difficulty = budget_request.difficulty
                    try:
                        selected_profile = resource_profile(
                            difficulty,
                            configured_max_output_tokens=dependencies.max_output_tokens,
                        )
                    except ValueError as error:
                        feedback = Feedback(
                            kind=FeedbackKind.INVALID_ACTION,
                            message=str(error),
                            details={"tool": _TASK_BUDGET_TOOL.name},
                        )
                        self._block(session, feedback.kind)
                        self._feedback_event(dependencies, run_id, feedback)
                        self._record(
                            run_id,
                            session,
                            dependencies,
                            state_before=session.state,
                            context=context,
                            response=response,
                            action=envelope,
                            feedback=feedback,
                            schema_validation=SchemaValidationEvidence(
                                valid=False, target="tool_call"
                            ),
                        )
                        continue_model = True
                        break
                    self._select_resource_profile(
                        run_id,
                        session,
                        dependencies,
                        selected_profile,
                        turn=(context, response, envelope),
                    )
                    continue
                if isinstance(action, FinishAction):
                    try:
                        revision = dependencies.revision()
                    except Exception as error:
                        return self._dependency_failure(
                            run_id,
                            session,
                            dependencies,
                            boundary="revision",
                            error=error,
                            state_before=session.state,
                            context=context,
                            response=response,
                            action=envelope,
                            schema_validation=SchemaValidationEvidence(
                                valid=True, target="finish"
                            ),
                        )
                    validation_required = bool(session.changed_files)
                    if validation_required and not session.validation.is_fresh_and_passing(revision):
                        automatic_validation = ToolCall(
                            name="run_validation",
                            arguments={"argv": []},
                        )
                        automatic_result = ToolResult(
                            call=automatic_validation,
                            success=True,
                            output="automatic task-end validation",
                        )
                        if self._execute(
                            run_id,
                            automatic_validation,
                            (context, response, envelope),
                            session,
                            dependencies,
                            validate=True,
                            state_before=session.state,
                            schema_validation=SchemaValidationEvidence(
                                valid=True, target="tool_call"
                            ),
                            policy_decision=PolicyDecisionEvidence(
                                effect="allow",
                                rule_id="harness.task_end_validation",
                                reason="validation is deferred until finish",
                            ),
                            dispatch_result=(automatic_result, None),
                            tool_started=True,
                        ):
                            return self._summary(run_id, session)
                        try:
                            revision = dependencies.revision()
                        except Exception as error:
                            return self._dependency_failure(
                                run_id,
                                session,
                                dependencies,
                                boundary="revision",
                                error=error,
                                state_before=session.state,
                                context=context,
                                response=response,
                                action=envelope,
                            )
                        if not session.validation.is_fresh_and_passing(revision):
                            continue_model = True
                            break
                    can_finish = (
                        (
                            not validation_required
                            or session.validation.is_fresh_and_passing(revision)
                        )
                        and not session.completion_blockers
                        and not session.unresolved_risks
                        and session.pending_request is None
                    )
                    if can_finish:
                        if not response.content.strip() and isinstance(envelope.action, FinishAction):
                            self._publish(
                                run_id,
                                ProgressKind.TEXT_DELTA,
                                dependencies,
                                text=envelope.action.summary,
                            )
                        terminal_before = session.state
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
                            session,
                            dependencies,
                            state_before=terminal_before,
                            context=context,
                            response=response,
                            action=envelope,
                            schema_validation=SchemaValidationEvidence(
                                valid=True, target="finish"
                            ),
                        )
                        return self._summary(run_id, session)
                    feedback = Feedback(
                        kind=FeedbackKind.INVALID_ACTION,
                        message=(
                            "finish requires fresh passing validation after repository changes "
                            "and no blockers"
                            if validation_required
                            else "finish is blocked by unresolved feedback or approval"
                        ),
                        details={
                            "validation_required": validation_required,
                            "completion_blockers": [
                                item.value for item in session.completion_blockers
                            ],
                            "approval_pending": session.pending_request is not None,
                        },
                    )
                    self._feedback_event(dependencies, run_id, feedback)
                    self._record(
                        run_id,
                        session,
                        dependencies,
                        state_before=session.state,
                        context=context,
                        response=response,
                        action=envelope,
                        feedback=feedback,
                        schema_validation=SchemaValidationEvidence(
                            valid=True, target="finish"
                        ),
                    )
                    continue_model = True
                    break

                try:
                    dependencies.tools.validate(action)
                except ToolRegistryError as error:
                    feedback = Feedback(
                        kind=FeedbackKind.INVALID_ACTION,
                        message="tool call failed schema validation",
                        details={"error_type": type(error).__name__},
                    )
                    self._block(session, feedback.kind)
                    self._feedback_event(dependencies, run_id, feedback)
                    self._record(
                        run_id,
                        session,
                        dependencies,
                        state_before=session.state,
                        context=context,
                        response=response,
                        action=envelope,
                        feedback=feedback,
                        schema_validation=SchemaValidationEvidence(
                            valid=False,
                            target="tool_call",
                            error_type=type(error).__name__,
                        ),
                    )
                    continue_model = True
                    break
                except Exception as error:
                    return self._dependency_failure(
                        run_id,
                        session,
                        dependencies,
                        boundary="tool",
                        error=error,
                        state_before=session.state,
                        context=context,
                        response=response,
                        action=envelope,
                    )

                schema_evidence = SchemaValidationEvidence(
                    valid=True, target="tool_call"
                )
                if self._is_repeated_read_action(action, run_id, dependencies):
                    feedback = Feedback(
                        kind=FeedbackKind.INVALID_ACTION,
                        message=(
                            "repeated read-only action made no new progress; "
                            "write the required repository change now"
                        ),
                        details={"tool": action.name, "require_write": True},
                    )
                    self._block(session, feedback.kind)
                    session.force_write = True
                    self._feedback_event(dependencies, run_id, feedback)
                    self._record(
                        run_id,
                        session,
                        dependencies,
                        state_before=session.state,
                        context=context,
                        response=response,
                        action=envelope,
                        feedback=feedback,
                        schema_validation=schema_evidence,
                    )
                    continue_model = True
                    break
                if self._is_repeated_write_action(action, run_id, dependencies):
                    try:
                        revision = dependencies.revision()
                    except Exception as error:
                        return self._dependency_failure(
                            run_id,
                            session,
                            dependencies,
                            boundary="revision",
                            error=error,
                            state_before=session.state,
                            context=context,
                            response=response,
                            action=envelope,
                            schema_validation=schema_evidence,
                        )
                    if (
                        session.validation.is_fresh_and_passing(revision)
                        and not session.completion_blockers
                        and not session.unresolved_risks
                        and session.pending_request is None
                    ):
                        terminal_before = session.state
                        self._terminal(
                            run_id,
                            session,
                            dependencies,
                            RunState.COMPLETED,
                            StopReason.SUCCESS,
                            "run.completed.after_repeated_write",
                        )
                        self._record(
                            run_id,
                            session,
                            dependencies,
                            state_before=terminal_before,
                            context=context,
                            response=response,
                            action=envelope,
                            schema_validation=schema_evidence,
                        )
                        return self._summary(run_id, session)
                    feedback = Feedback(
                        kind=FeedbackKind.INVALID_ACTION,
                        message=(
                            "repeated write action was already applied; "
                            "inspect the current file and derive a fresh patch"
                        ),
                        details={"tool": action.name, "require_fresh_patch": True},
                    )
                    self._block(session, feedback.kind)
                    self._feedback_event(dependencies, run_id, feedback)
                    self._record(
                        run_id,
                        session,
                        dependencies,
                        state_before=session.state,
                        context=context,
                        response=response,
                        action=envelope,
                        feedback=feedback,
                        schema_validation=schema_evidence,
                    )
                    continue_model = True
                    break
                patch_conflict_attempts = self._patch_conflict_attempts(
                    action, run_id, dependencies
                )
                if patch_conflict_attempts >= _PATCH_CONFLICT_REPEAT_LIMIT:
                    return self._terminal_without_action(
                        run_id,
                        task,
                        session,
                        dependencies,
                        state_before,
                        StopReason.NO_PROGRESS,
                        "run.no_progress.repeated_patch_conflict",
                        FeedbackKind.NO_PROGRESS,
                        "the same apply_patch conflicted repeatedly; stopping until a fresh patch is generated",
                        context=context,
                        response=response,
                    )
                if patch_conflict_attempts == 1:
                    feedback = Feedback(
                        kind=FeedbackKind.INVALID_ACTION,
                        message=(
                            "the exact apply_patch already conflicted; re-read the affected file "
                            "and generate a different patch before retrying"
                        ),
                        details={
                            "tool": action.name,
                            "require_fresh_patch": True,
                            "patch_fingerprint": self._patch_fingerprint(action),
                        },
                    )
                    self._block(session, feedback.kind)
                    self._feedback_event(dependencies, run_id, feedback)
                    self._record(
                        run_id,
                        session,
                        dependencies,
                        state_before=state_before,
                        context=context,
                        response=response,
                        action=envelope,
                        feedback=feedback,
                        schema_validation=schema_evidence,
                    )
                    continue_model = True
                    break
                try:
                    decision = self._policy_decision(action, dependencies)
                except Exception as error:
                    return self._dependency_failure(
                        run_id,
                        session,
                        dependencies,
                        boundary="policy",
                        error=error,
                        state_before=session.state,
                        context=context,
                        response=response,
                        action=envelope,
                        schema_validation=schema_evidence,
                    )
                policy_evidence = self._policy_evidence(decision)
                if decision.effect is PolicyEffect.DENY:
                    feedback = Feedback(
                        kind=FeedbackKind.POLICY_BLOCKED,
                        message="policy denied action",
                        details={"rule_id": decision.rule_id},
                    )
                    self._block(session, feedback.kind)
                    if decision.rule_id not in session.unresolved_risks:
                        session.unresolved_risks.append(decision.rule_id)
                    self._feedback_event(dependencies, run_id, feedback)
                    self._record(
                        run_id,
                        session,
                        dependencies,
                        state_before=session.state,
                        context=context,
                        response=response,
                        action=envelope,
                        feedback=feedback,
                        schema_validation=schema_evidence,
                        policy_decision=policy_evidence,
                    )
                    continue_model = True
                    break
                if decision.effect is PolicyEffect.ASK:
                    try:
                        request = dependencies.approvals.request(decision)
                    except Exception as error:
                        return self._dependency_failure(
                            run_id,
                            session,
                            dependencies,
                            boundary="approval",
                            error=error,
                            state_before=session.state,
                            context=context,
                            response=response,
                            action=envelope,
                            schema_validation=schema_evidence,
                            policy_decision=policy_evidence,
                        )
                    session.pending_call = action
                    session.pending_request = request.id
                    session.approvals.append(request.id)
                    approval_before = session.state
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
                        session,
                        dependencies,
                        state_before=approval_before,
                        context=context,
                        response=response,
                        action=envelope,
                        schema_validation=schema_evidence,
                        policy_decision=policy_evidence,
                        approval_update=request,
                    )
                    return self._summary(run_id, session)
                if self._execute(
                    run_id,
                    action,
                    (context, response, envelope),
                    session,
                    dependencies,
                    validate=action_index == validation_action_index,
                    state_before=session.state,
                    schema_validation=schema_evidence,
                    policy_decision=policy_evidence,
                ):
                    return self._summary(run_id, session)
            if continue_model:
                continue

    @classmethod
    def _prepare_parallel_read_batch(
        cls,
        actions: Sequence[ActionEnvelope],
        run_id: UUID,
        dependencies: LoopDependencies,
    ) -> tuple[
        tuple[ActionEnvelope, ToolCall, SchemaValidationEvidence, PolicyDecisionEvidence],
        ...,
    ] | None:
        """Preflight an independent read batch without mutating loop state.

        Claude Code-style parallelism is deliberately conservative: only a batch
        containing two or more known read-only tools can enter this path.  Schema,
        replay, and policy checks still happen before any executor starts; anything
        uncertain falls back to the normal ordered action path so governance and
        feedback semantics stay identical.
        """

        if len(actions) < 2 or any(not isinstance(item.action, ToolCall) for item in actions):
            return None
        prepared: list[
            tuple[ActionEnvelope, ToolCall, SchemaValidationEvidence, PolicyDecisionEvidence]
        ] = []
        for envelope in actions:
            action = envelope.action
            if not isinstance(action, ToolCall) or action.name not in _READ_ONLY_TOOLS:
                return None
            try:
                dependencies.tools.validate(action)
                if cls._is_repeated_read_action(action, run_id, dependencies):
                    return None
                decision = cls._policy_decision(action, dependencies)
            except Exception:
                return None
            if decision.effect is not PolicyEffect.ALLOW:
                return None
            prepared.append(
                (
                    envelope,
                    action,
                    SchemaValidationEvidence(valid=True, target="tool_call"),
                    cls._policy_evidence(decision),
                )
            )
        return tuple(prepared)

    def _execute_read_only_batch(
        self,
        run_id: UUID,
        batch: Sequence[
            tuple[ActionEnvelope, ToolCall, SchemaValidationEvidence, PolicyDecisionEvidence]
        ],
        turn: tuple[ModelContext, LLMResponse],
        session: _Session,
        dependencies: LoopDependencies,
    ) -> bool:
        """Dispatch independent reads concurrently, then record them in model order."""

        call_ids = tuple(str(uuid4()) for _ in batch)
        for call_id, (_, call, _, _) in zip(call_ids, batch, strict=True):
            self._publish(
                run_id,
                ProgressKind.TOOL_STARTED,
                dependencies,
                payload={
                    "tool_call_id": call_id,
                    "tool": call.name,
                    "arguments": redact_payload(call.arguments),
                    "parallel": True,
                },
            )

        def dispatch(
            item: tuple[ActionEnvelope, ToolCall, SchemaValidationEvidence, PolicyDecisionEvidence],
        ) -> tuple[ToolResult | None, Exception | None]:
            _, call, _, _ = item
            context = ToolContext(
                run_id=run_id,
                repository_root=dependencies.policy_config.repository_root,
                permission_mode=dependencies.permission_mode,
            )
            try:
                return ToolResult.model_validate(dependencies.tools.dispatch(call, context)), None
            except Exception as error:  # normalized by _execute on the owning thread
                return None, error

        with ThreadPoolExecutor(
            max_workers=min(_MAX_PARALLEL_READ_TOOLS, len(batch)),
            thread_name_prefix="613-read",
        ) as executor:
            outcomes = tuple(executor.map(dispatch, batch))

        context, response = turn
        for call_id, item, outcome in zip(call_ids, batch, outcomes, strict=True):
            envelope, call, schema_evidence, policy_evidence = item
            if self._execute(
                run_id,
                call,
                (context, response, envelope),
                session,
                dependencies,
                validate=False,
                state_before=session.state,
                schema_validation=schema_evidence,
                policy_decision=policy_evidence,
                dispatch_result=outcome,
                tool_call_id=call_id,
                tool_started=True,
            ):
                return True
        return False

    @staticmethod
    def _with_resource_metadata(
        context: ModelContext,
        session: _Session,
        dependencies: LoopDependencies,
    ) -> ModelContext:
        profile = session.resource_profile or resource_profile(
            "standard",
            configured_max_output_tokens=dependencies.max_output_tokens,
        )
        metadata = dict(context.metadata)
        metadata["resource_profile"] = (
            session.resource_profile.name if session.resource_profile else "pending"
        )
        metadata["max_output_tokens"] = profile.max_output_tokens
        return context.model_copy(update={"metadata": metadata})

    def _select_resource_profile(
        self,
        run_id: UUID,
        session: _Session,
        dependencies: LoopDependencies,
        profile: ResourceProfile,
        *,
        turn: tuple[ModelContext, LLMResponse, ActionEnvelope] | None = None,
        event_type: str = "resource_profile.selected",
    ) -> None:
        session.resource_profile = profile
        payload = {
            "profile": profile.name,
            "max_output_tokens": profile.max_output_tokens,
        }
        self._event(dependencies, run_id, event_type, payload)
        if turn is None:
            return
        _context, _response, envelope = turn
        call = envelope.action
        if not isinstance(call, ToolCall):
            return
        result = ToolResult(
            call=call,
            success=True,
            output=json.dumps(payload, sort_keys=True),
        )
        tool_call_id = str(uuid4())
        self._publish(
            run_id,
            ProgressKind.TOOL_STARTED,
            dependencies,
            payload={
                "tool_call_id": tool_call_id,
                "tool": call.name,
                "arguments": redact_payload(call.arguments),
            },
        )
        self._publish(
            run_id,
            ProgressKind.TOOL_FINISHED,
            dependencies,
            payload={
                "tool_call_id": tool_call_id,
                "tool": call.name,
                "success": True,
                "output": result.output,
                "error": "",
                "changed_files": (),
            },
        )
        self._record_from_turn(
            run_id,
            turn,
            call,
            result,
            None,
            session,
            dependencies,
            state_before=session.state,
            schema_validation=SchemaValidationEvidence(valid=True, target="tool_call"),
            policy_decision=PolicyDecisionEvidence(
                effect="allow",
                rule_id="harness.resource_profile",
                reason="model selected bounded task resources",
            ),
        )

    @staticmethod
    def _is_repeated_read_action(
        action: ToolCall, run_id: UUID, dependencies: LoopDependencies
    ) -> bool:
        """Reject an exact repeated read once its prior result is available."""

        if action.name not in _READ_ONLY_TOOLS:
            return False
        for event in reversed(dependencies.events.list_for_run(run_id)):
            if event.event_type != "tool.completed":
                continue
            payload = event.payload
            previous = payload.get("call")
            if not isinstance(previous, dict):
                continue
            if previous.get("name") == action.name and previous.get("arguments") == action.arguments:
                return True
            if payload.get("changed_files"):
                return False
        return False

    @staticmethod
    def _is_repeated_write_action(
        action: ToolCall, run_id: UUID, dependencies: LoopDependencies
    ) -> bool:
        """Reject an exact write replay after a successful file mutation."""

        if action.name not in _WRITE_TOOLS:
            return False
        for event in reversed(dependencies.events.list_for_run(run_id)):
            if event.event_type != "tool.completed":
                continue
            payload = event.payload
            previous = payload.get("call")
            if not isinstance(previous, dict):
                continue
            if previous.get("name") == action.name and previous.get("arguments") == action.arguments:
                return bool(payload.get("success")) and bool(payload.get("changed_files"))
            if payload.get("changed_files"):
                return False
        return False

    @classmethod
    def _patch_conflict_attempts(
        cls, action: ToolCall, run_id: UUID, dependencies: LoopDependencies
    ) -> int:
        """Count consecutive attempts of the same failed patch fingerprint."""

        if action.name != "apply_patch":
            return 0
        fingerprint = cls._patch_fingerprint(action)
        attempts = 0
        for event in reversed(dependencies.events.list_for_run(run_id)):
            if event.event_type == "tool.completed":
                payload = event.payload
                call = payload.get("call")
                if not isinstance(call, dict) or call.get("name") != "apply_patch":
                    break
                arguments = call.get("arguments")
                if not isinstance(arguments, dict):
                    break
                previous = ToolCall(name="apply_patch", arguments=arguments)
                if cls._patch_fingerprint(previous) != fingerprint:
                    break
                error = payload.get("error")
                if payload.get("success") is not False or not (
                    isinstance(error, str) and error.startswith("PatchConflictError")
                ):
                    break
                attempts += 1
                continue
            if event.event_type == "feedback.invalid_action":
                details = event.payload.get("details")
                if (
                    isinstance(details, dict)
                    and details.get("require_fresh_patch") is True
                    and details.get("patch_fingerprint") == fingerprint
                ):
                    attempts += 1
                    continue
            # State, model, feedback.tool_error, and tool.started events do not
            # change the consecutive patch evidence; another completed tool or
            # a different attempted action does.
        return attempts

    @staticmethod
    def _patch_fingerprint(action: ToolCall) -> str:
        patch = action.arguments.get("patch")
        value = patch if isinstance(patch, str) else json.dumps(
            action.arguments, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def cancel(
        self,
        run_id: UUID,
        task: str,
        dependencies: LoopDependencies,
    ) -> RunSummary:
        session = self._load(run_id, dependencies)
        if session.state.is_terminal:
            return self._summary(run_id, session)
        state_before = session.state
        approval_update: ApprovalRequest | None = None
        if session.pending_request is not None:
            try:
                _, approval_update = dependencies.approvals.invalidation_update(
                    session.pending_request
                )
            except ApprovalError:
                pass
            except Exception as error:
                return self._dependency_failure(
                    run_id,
                    session,
                    dependencies,
                    boundary="approval",
                    error=error,
                    state_before=state_before,
                    action=(
                        ActionEnvelope(action=session.pending_call)
                        if session.pending_call is not None
                        else None
                    ),
                )
        session.pending_call = None
        session.pending_request = None
        self._terminal(
            run_id,
            session,
            dependencies,
            RunState.CANCELLED,
            StopReason.CANCELLED,
            "run.cancelled",
        )
        self._record(
            run_id,
            session,
            dependencies,
            state_before=state_before,
            context=ModelContext(run_id=run_id, task=task),
            approval_update=approval_update,
        )
        return self._summary(run_id, session)

    def pause(
        self,
        run_id: UUID,
        task: str,
        dependencies: LoopDependencies,
    ) -> RunSummary:
        session = self._load(run_id, dependencies)
        if session.state.is_terminal:
            return self._summary(run_id, session)
        state_before = session.state
        self._transition(run_id, session, dependencies, RunState.PAUSED)
        session.stop_reason = None
        self._record(
            run_id,
            session,
            dependencies,
            state_before=state_before,
            context=ModelContext(run_id=run_id, task=task),
        )
        return self._summary(run_id, session)

    def get_summary(
        self, run_id: UUID, dependencies: LoopDependencies
    ) -> RunSummary:
        snapshot = dependencies.sessions.get_loop_session(run_id)
        if snapshot is None:
            raise KeyError(f"run has no summary: {run_id}")
        return self._summary(
            run_id,
            _Session.restore(
                snapshot,
                dependencies.budget_limits,
                dependencies.max_output_tokens,
            ),
        )

    def _resume_pending(
        self,
        run_id: UUID,
        task: str,
        session: _Session,
        dependencies: LoopDependencies,
    ) -> RunSummary | None:
        pending = session.pending_call
        if pending is None:
            return None
        if session.pending_request is None:
            feedback = Feedback(
                kind=FeedbackKind.TOOL_ERROR,
                message="pending approval is missing its request",
                retryable=False,
            )
            return self._terminal_feedback(
                run_id,
                session,
                dependencies,
                state_before=session.state,
                state=RunState.FAILED,
                reason=StopReason.DEPENDENCY_ERROR,
                event_type="run.invalid_pending_approval",
                feedback=feedback,
                action=ActionEnvelope(action=pending),
            )
        request_id = session.pending_request
        try:
            request = dependencies.approvals.get_request(request_id)
        except Exception as error:
            return self._dependency_failure(
                run_id,
                session,
                dependencies,
                boundary="approval",
                error=error,
                state_before=session.state,
                action=ActionEnvelope(action=pending),
            )
        if request.status is ApprovalStatus.PENDING:
            session.state = RunState.WAITING_APPROVAL
            session.stop_reason = StopReason.APPROVAL_REQUIRED
            self._save(run_id, session, dependencies)
            return self._summary(run_id, session)
        if request.status is ApprovalStatus.REJECTED:
            return self._terminate_pending_approval(
                run_id,
                pending,
                session,
                dependencies,
                FeedbackKind.POLICY_BLOCKED,
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
                StopReason.TIMEOUT,
                "approval.expired",
            )
        if request.status in {ApprovalStatus.EXECUTING, ApprovalStatus.CONSUMED}:
            return self._pause_pending_claim(
                run_id,
                pending,
                session,
                dependencies,
                state_before=session.state,
                request_id=request_id,
            )
        try:
            dependencies.tools.validate(pending)
        except Exception as error:
            return self._dependency_failure(
                run_id,
                session,
                dependencies,
                boundary="tool",
                error=error,
                state_before=session.state,
                action=ActionEnvelope(action=pending),
                schema_validation=SchemaValidationEvidence(
                    valid=False,
                    target="tool_call",
                    error_type=type(error).__name__,
                ),
            )
        try:
            current_decision = self._policy_decision(pending, dependencies)
        except Exception as error:
            return self._dependency_failure(
                run_id,
                session,
                dependencies,
                boundary="policy",
                error=error,
                state_before=session.state,
                action=ActionEnvelope(action=pending),
            )
        policy_evidence = self._policy_evidence(current_decision)
        if current_decision.effect is PolicyEffect.DENY:
            feedback = Feedback(
                kind=FeedbackKind.POLICY_BLOCKED,
                message="current policy denied approved action",
                retryable=False,
                details={"rule_id": current_decision.rule_id},
            )
            self._block(session, feedback.kind)
            if current_decision.rule_id not in session.unresolved_risks:
                session.unresolved_risks.append(current_decision.rule_id)
            try:
                _, approval_update = dependencies.approvals.invalidation_update(
                    request_id
                )
            except Exception as error:
                return self._dependency_failure(
                    run_id,
                    session,
                    dependencies,
                    boundary="approval",
                    error=error,
                    state_before=session.state,
                    action=ActionEnvelope(action=pending),
                    policy_decision=policy_evidence,
                )
            session.pending_call = None
            session.pending_request = None
            return self._terminal_feedback(
                run_id,
                session,
                dependencies,
                state_before=session.state,
                state=RunState.FAILED,
                reason=StopReason.APPROVAL_REJECTED,
                event_type="approval.policy_rejected",
                feedback=feedback,
                action=ActionEnvelope(action=pending),
                schema_validation=SchemaValidationEvidence(
                    valid=True, target="tool_call"
                ),
                policy_decision=policy_evidence,
                approval_update=approval_update,
            )
        try:
            claim = dependencies.approvals.claim(request_id, pending)
        except Exception as error:
            return self._dependency_failure(
                run_id,
                session,
                dependencies,
                boundary="approval",
                error=error,
                state_before=session.state,
                action=ActionEnvelope(action=pending),
                policy_decision=policy_evidence,
            )
        if not claim.acquired:
            try:
                latest = dependencies.approvals.get_request(request_id)
            except Exception as error:
                return self._dependency_failure(
                    run_id,
                    session,
                    dependencies,
                    boundary="approval",
                    error=error,
                    state_before=session.state,
                    action=ActionEnvelope(action=pending),
                    policy_decision=policy_evidence,
                )
            feedback = Feedback(
                kind=FeedbackKind.TOOL_ERROR,
                message="approval action is already claimed or no longer executable",
                retryable=False,
                details={
                    "request_id": str(request_id),
                    "status": latest.status.value,
                },
            )
            if latest.status in {ApprovalStatus.EXECUTING, ApprovalStatus.CONSUMED}:
                return self._pause_pending_claim(
                    run_id,
                    pending,
                    session,
                    dependencies,
                    state_before=session.state,
                    request_id=request_id,
                )
            return self._terminal_feedback(
                run_id,
                session,
                dependencies,
                state_before=session.state,
                state=RunState.FAILED,
                reason=StopReason.DEPENDENCY_ERROR,
                event_type="approval.stale_claim",
                feedback=feedback,
                action=ActionEnvelope(action=pending),
                schema_validation=SchemaValidationEvidence(
                    valid=True, target="tool_call"
                ),
                policy_decision=policy_evidence,
            )
        state_before = session.state
        session.pending_call = None
        session.pending_request = None
        session.stop_reason = None
        self._transition(run_id, session, dependencies, RunState.RUNNING)
        terminal = self._execute(
            run_id,
            pending,
            None,
            session,
            dependencies,
            state_before=state_before,
            schema_validation=SchemaValidationEvidence(
                valid=True, target="tool_call"
            ),
            policy_decision=policy_evidence,
            approval_update=request.model_copy(
                update={"status": ApprovalStatus.CONSUMED}
            ),
        )
        if terminal:
            return self._summary(run_id, session)
        return None

    def _pause_pending_claim(
        self,
        run_id: UUID,
        pending: ToolCall,
        session: _Session,
        dependencies: LoopDependencies,
        *,
        state_before: RunState,
        request_id: UUID,
    ) -> RunSummary:
        feedback = Feedback(
            kind=FeedbackKind.TOOL_ERROR,
            message="approval execution is uncertain; manual reconciliation required",
            retryable=False,
            details={"request_id": str(request_id)},
        )
        self._block(session, feedback.kind)
        if "approval.execution_uncertain" not in session.unresolved_risks:
            session.unresolved_risks.append("approval.execution_uncertain")
        self._feedback_event(dependencies, run_id, feedback)
        self._transition(run_id, session, dependencies, RunState.PAUSED)
        session.stop_reason = None
        self._record(
            run_id,
            session,
            dependencies,
            state_before=state_before,
            action=ActionEnvelope(action=pending),
            feedback=feedback,
            schema_validation=SchemaValidationEvidence(
                valid=True, target="tool_call"
            ),
            policy_decision=PolicyDecisionEvidence(
                effect="ask",
                rule_id="approval.execution_uncertain",
                reason="approval claim is already executing or consumed",
            ),
        )
        return self._summary(run_id, session)

    def _terminate_pending_approval(
        self,
        run_id: UUID,
        pending: ToolCall,
        session: _Session,
        dependencies: LoopDependencies,
        feedback_kind: FeedbackKind,
        stop_reason: StopReason,
        event_type: str,
    ) -> RunSummary:
        feedback = Feedback(
            kind=feedback_kind,
            message=event_type.replace(".", " "),
            retryable=False,
            details={"request_id": str(session.pending_request)},
        )
        state_before = session.state
        session.pending_call = None
        session.pending_request = None
        return self._terminal_feedback(
            run_id,
            session,
            dependencies,
            state_before=state_before,
            state=RunState.FAILED,
            reason=stop_reason,
            event_type=event_type,
            feedback=feedback,
            action=ActionEnvelope(action=pending),
            schema_validation=SchemaValidationEvidence(
                valid=True, target="tool_call"
            ),
            policy_decision=PolicyDecisionEvidence(
                effect="ask",
                rule_id="approval.exact_action",
                reason="pending exact action approval",
            ),
        )

    def _execute(
        self,
        run_id: UUID,
        call: ToolCall,
        turn: tuple[ModelContext, LLMResponse, ActionEnvelope] | None,
        session: _Session,
        dependencies: LoopDependencies,
        *,
        validate: bool = True,
        state_before: RunState,
        schema_validation: SchemaValidationEvidence,
        policy_decision: PolicyDecisionEvidence,
        approval_update: ApprovalRequest | None = None,
        dispatch_result: tuple[ToolResult | None, Exception | None] | None = None,
        tool_call_id: str | None = None,
        tool_started: bool = False,
    ) -> bool:
        tool_call_id = tool_call_id or str(uuid4())
        context = ToolContext(
            run_id=run_id,
            repository_root=dependencies.policy_config.repository_root,
            permission_mode=dependencies.permission_mode,
        )
        if not tool_started:
            self._publish(
                run_id,
                ProgressKind.TOOL_STARTED,
                dependencies,
                payload={
                    "tool_call_id": tool_call_id,
                    "tool": call.name,
                    "arguments": redact_payload(call.arguments),
                },
            )
        try:
            if dispatch_result is None:
                tool_result = ToolResult.model_validate(
                    dependencies.tools.dispatch(call, context)
                )
            else:
                prepared_result, prepared_error = dispatch_result
                if prepared_error is not None:
                    raise prepared_error
                if prepared_result is None:
                    raise ToolRegistryError("parallel dispatch returned no tool result")
                tool_result = prepared_result
        except ToolRegistryError as error:
            feedback = Feedback(
                kind=FeedbackKind.TOOL_ERROR,
                message="tool dispatch failed",
                details={"error_type": type(error).__name__},
            )
            self._block(session, feedback.kind)
            self._feedback_event(dependencies, run_id, feedback)
            self._record_from_turn(
                run_id,
                turn,
                call,
                tool_result=None,
                feedback=feedback,
                session=session,
                deps=dependencies,
                state_before=state_before,
                schema_validation=SchemaValidationEvidence(
                    valid=False,
                    target="tool_call",
                    error_type=type(error).__name__,
                ),
                policy_decision=policy_decision,
                approval_update=approval_update,
            )
            return False
        except Exception as error:
            self._dependency_failure(
                run_id,
                session,
                dependencies,
                boundary="tool",
                error=error,
                state_before=session.state,
                context=turn[0] if turn else None,
                response=turn[1] if turn else None,
                action=turn[2] if turn else ActionEnvelope(action=call),
                schema_validation=schema_validation,
                policy_decision=policy_decision,
                approval_update=approval_update,
            )
            return True

        self._publish(
            run_id,
            ProgressKind.TOOL_FINISHED,
            dependencies,
            payload={
                "tool_call_id": tool_call_id,
                "tool": call.name,
                "success": tool_result.success,
                "output": _progress_text(tool_result.output),
                "error": _progress_text(tool_result.error or "") if tool_result.error else "",
                "changed_files": tool_result.changed_files,
            },
        )

        for path in tool_result.changed_files:
            if path not in session.changed_files:
                session.changed_files.append(path)
        if call.name in _WRITE_TOOLS and tool_result.success:
            session.force_write = False
        self._event(
            dependencies,
            run_id,
            "tool.completed",
            tool_result.model_dump(mode="json"),
        )
        if not tool_result.success:
            tool_error = tool_result.error or "unknown tool error"
            if call.name == "apply_patch" and tool_error.startswith("PatchConflictError"):
                message = (
                    "apply_patch conflicted with current repository content; "
                    "re-read the affected files and create a fresh patch"
                )
            else:
                message = "tool execution failed"
            feedback = Feedback(
                kind=FeedbackKind.TOOL_ERROR,
                message=message,
                details={
                    "tool": call.name,
                    "error": tool_error,
                    "changed_files": list(tool_result.changed_files),
                },
            )
            self._block(session, feedback.kind)
            self._feedback_event(dependencies, run_id, feedback)
            self._record_from_turn(
                run_id,
                turn,
                call,
                tool_result,
                feedback,
                session,
                dependencies,
                state_before=state_before,
                schema_validation=schema_validation,
                policy_decision=policy_decision,
                approval_update=approval_update,
            )
            return False

        # A successful write that reports no changed path is deterministic
        # no-progress evidence; validate it immediately so the loop can classify
        # the failure instead of asking the model to repeat a no-op forever.
        should_validate = validate or (
            call.name in _WRITE_TOOLS
            and tool_result.success
            and not tool_result.changed_files
        )
        if not should_validate:
            self._record_from_turn(
                run_id,
                turn,
                call,
                tool_result,
                None,
                session,
                dependencies,
                state_before=state_before,
                schema_validation=schema_validation,
                policy_decision=policy_decision,
                approval_update=approval_update,
            )
            return False

        self._publish(run_id, ProgressKind.VALIDATION_STARTED, dependencies)
        try:
            validation = ValidationResult.model_validate(
                dependencies.validator.validate()
            )
        except Exception as error:
            self._publish(
                run_id,
                ProgressKind.VALIDATION_FINISHED,
                dependencies,
                payload={"success": False},
            )
            self._dependency_failure(
                run_id,
                session,
                dependencies,
                boundary="validator",
                error=error,
                state_before=session.state,
                context=turn[0] if turn else None,
                response=turn[1] if turn else None,
                action=turn[2] if turn else ActionEnvelope(action=call),
                tool_result=tool_result,
                schema_validation=schema_validation,
                policy_decision=policy_decision,
                approval_update=approval_update,
            )
            return True
        self._publish(
            run_id,
            ProgressKind.VALIDATION_FINISHED,
            dependencies,
            payload={
                "success": validation.passed,
                "result": redact_payload(validation.model_dump(mode="json")),
            },
        )
        try:
            revision = dependencies.revision()
        except Exception as error:
            self._dependency_failure(
                run_id,
                session,
                dependencies,
                boundary="revision",
                error=error,
                state_before=session.state,
                context=turn[0] if turn else None,
                response=turn[1] if turn else None,
                action=turn[2] if turn else ActionEnvelope(action=call),
                tool_result=tool_result,
                validation=validation,
                schema_validation=schema_validation,
                policy_decision=policy_decision,
                approval_update=approval_update,
            )
            return True
        session.validation.record(validation, revision)
        session.validation_evidence.append(validation.model_dump(mode="json"))
        try:
            changed_files = tuple(dependencies.changed_files())
        except Exception as error:
            self._dependency_failure(
                run_id,
                session,
                dependencies,
                boundary="changed_files",
                error=error,
                state_before=session.state,
                context=turn[0] if turn else None,
                response=turn[1] if turn else None,
                action=turn[2] if turn else ActionEnvelope(action=call),
                tool_result=tool_result,
                validation=validation,
                schema_validation=schema_validation,
                policy_decision=policy_decision,
                approval_update=approval_update,
            )
            return True
        session.changed_files = list(dict.fromkeys((*session.changed_files, *changed_files)))
        if not validation.passed and not changed_files:
            session.force_write = True
        try:
            feedback = Feedback.model_validate(
                dependencies.classifier.classify(validation, call, changed_files)
            )
        except Exception as error:
            self._dependency_failure(
                run_id,
                session,
                dependencies,
                boundary="classifier",
                error=error,
                state_before=session.state,
                context=turn[0] if turn else None,
                response=turn[1] if turn else None,
                action=turn[2] if turn else ActionEnvelope(action=call),
                tool_result=tool_result,
                validation=validation,
                schema_validation=schema_validation,
                policy_decision=policy_decision,
                approval_update=approval_update,
            )
            return True

        self._event(
            dependencies,
            run_id,
            "validation.completed",
            validation.model_dump(mode="json"),
        )
        self._feedback_event(dependencies, run_id, feedback)
        if feedback.kind is FeedbackKind.PASS:
            session.completion_blockers = [
                blocker
                for blocker in session.completion_blockers
                if blocker is FeedbackKind.POLICY_BLOCKED
            ]
        else:
            self._block(session, feedback.kind)

        terminal = False
        if feedback.kind is FeedbackKind.NO_PROGRESS:
            self._terminal(
                run_id,
                session,
                dependencies,
                RunState.FAILED,
                StopReason.NO_PROGRESS,
                "run.no_progress",
            )
            terminal = True
        elif feedback.kind is FeedbackKind.RESOURCE_EXHAUSTED:
            self._terminal(
                run_id,
                session,
                dependencies,
                RunState.FAILED,
                StopReason.VALIDATION_FAILED,
                "run.resource_exhausted",
            )
            terminal = True
        self._record_from_turn(
            run_id,
            turn,
            call,
            tool_result,
            feedback,
            session,
            dependencies,
            validation,
            state_before=state_before,
            schema_validation=schema_validation,
            policy_decision=policy_decision,
            approval_update=approval_update,
        )
        return terminal

    def _dependency_failure(
        self,
        run_id: UUID,
        session: _Session,
        dependencies: LoopDependencies,
        *,
        boundary: str,
        error: Exception,
        state_before: RunState,
        context: ModelContext | None = None,
        response: LLMResponse | None = None,
        action: ActionEnvelope | None = None,
        tool_result: ToolResult | None = None,
        validation: ValidationResult | None = None,
        schema_validation: SchemaValidationEvidence | None = None,
        policy_decision: PolicyDecisionEvidence | None = None,
        approval_update: ApprovalRequest | None = None,
    ) -> RunSummary:
        kind = (
            FeedbackKind.TOOL_ERROR
            if boundary in {"tool", "policy", "approval"}
            else FeedbackKind.ENVIRONMENT_FAILURE
        )
        feedback = Feedback(
            kind=kind,
            message=f"{boundary} dependency failed",
            retryable=False,
            details={"boundary": boundary, "error_type": type(error).__name__},
        )
        self._block(session, feedback.kind)
        reason = (
            StopReason.PROVIDER_ERROR
            if boundary == "provider"
            else StopReason.DEPENDENCY_ERROR
        )
        return self._terminal_feedback(
            run_id,
            session,
            dependencies,
            state_before=state_before,
            state=RunState.FAILED,
            reason=reason,
            event_type=f"run.{boundary}_error",
            feedback=feedback,
            context=context,
            response=response,
            action=action,
            tool_result=tool_result,
            validation=validation,
            schema_validation=schema_validation,
            policy_decision=policy_decision,
            approval_update=approval_update,
        )

    def _terminal_without_action(
        self,
        run_id: UUID,
        task: str,
        session: _Session,
        dependencies: LoopDependencies,
        state_before: RunState,
        reason: StopReason,
        event_type: str,
        feedback_kind: FeedbackKind,
        message: str,
        *,
        context: ModelContext | None = None,
        response: LLMResponse | None = None,
    ) -> RunSummary:
        feedback = Feedback(kind=feedback_kind, message=message, retryable=False)
        self._block(session, feedback.kind)
        return self._terminal_feedback(
            run_id,
            session,
            dependencies,
            state_before=state_before,
            state=RunState.FAILED,
            reason=reason,
            event_type=event_type,
            feedback=feedback,
            context=context or ModelContext(run_id=run_id, task=task),
            response=response,
        )

    def _terminal_feedback(
        self,
        run_id: UUID,
        session: _Session,
        dependencies: LoopDependencies,
        *,
        state_before: RunState,
        state: RunState,
        reason: StopReason,
        event_type: str,
        feedback: Feedback,
        context: ModelContext | None = None,
        response: LLMResponse | None = None,
        action: ActionEnvelope | None = None,
        tool_result: ToolResult | None = None,
        validation: ValidationResult | None = None,
        schema_validation: SchemaValidationEvidence | None = None,
        policy_decision: PolicyDecisionEvidence | None = None,
        approval_update: ApprovalRequest | None = None,
    ) -> RunSummary:
        self._feedback_event(dependencies, run_id, feedback)
        self._terminal(
            run_id, session, dependencies, state, reason, event_type
        )
        self._record(
            run_id,
            session,
            dependencies,
            state_before=state_before,
            context=context,
            response=response,
            action=action,
            tool_result=tool_result,
            feedback=feedback,
            validation=validation,
            schema_validation=schema_validation,
            policy_decision=policy_decision,
            approval_update=approval_update,
        )
        return self._summary(run_id, session)

    def _record_from_turn(
        self,
        run_id: UUID,
        turn: tuple[ModelContext, LLMResponse, ActionEnvelope] | None,
        call: ToolCall,
        tool_result: ToolResult | None,
        feedback: Feedback | None,
        session: _Session,
        deps: LoopDependencies,
        validation: ValidationResult | None = None,
        *,
        state_before: RunState,
        schema_validation: SchemaValidationEvidence,
        policy_decision: PolicyDecisionEvidence,
        approval_update: ApprovalRequest | None = None,
    ) -> None:
        context, response, envelope = turn or (
            None,
            None,
            ActionEnvelope(action=call),
        )
        self._record(
            run_id,
            session,
            deps,
            state_before=state_before,
            context=context,
            response=response,
            action=envelope,
            tool_result=tool_result,
            feedback=feedback,
            validation=validation,
            schema_validation=schema_validation,
            policy_decision=policy_decision,
            approval_update=approval_update,
        )

    def _record(
        self,
        run_id: UUID,
        session: _Session,
        dependencies: LoopDependencies,
        *,
        state_before: RunState,
        context: ModelContext | None = None,
        response: LLMResponse | None = None,
        action: ActionEnvelope | None = None,
        tool_result: ToolResult | None = None,
        feedback: Feedback | None = None,
        validation: ValidationResult | None = None,
        schema_validation: SchemaValidationEvidence | None = None,
        policy_decision: PolicyDecisionEvidence | None = None,
        approval_update: ApprovalRequest | None = None,
    ) -> None:
        if context is not None:
            session.context_summary = self._summarize_context(context)
        session.classifier_state = self._classifier_snapshot(dependencies)
        session.iteration += 1
        iteration = IterationRecord(
            run_id=run_id,
            iteration=session.iteration,
            state_before=state_before,
            state_after=session.state,
            context_summary=session.context_summary,
            model_response=response.model_dump(mode="json") if response else None,
            action=action,
            schema_validation=schema_validation,
            policy_decision=policy_decision,
            tool_results=(
                [tool_result.model_dump(mode="json")]
                if tool_result is not None
                else []
            ),
            validation=validation.model_dump(mode="json") if validation else None,
            feedback=feedback,
            stop_reason=session.stop_reason if session.state.is_terminal else None,
            timestamp=dependencies.clock(),
        )
        state_store = dependencies.sessions
        if hasattr(dependencies.iterations, "save_iteration_and_session"):
            state_store = dependencies.iterations  # type: ignore[assignment]
        state_store.save_iteration_and_session(
            iteration,
            session.snapshot(run_id),
            approval_update,
        )

    def _load(self, run_id: UUID, dependencies: LoopDependencies) -> _Session:
        snapshot = dependencies.sessions.get_loop_session(run_id)
        if snapshot is not None:
            session = _Session.restore(
                snapshot,
                dependencies.budget_limits,
                dependencies.max_output_tokens,
            )
            if session.classifier_state is not None:
                dependencies.classifier.restore(session.classifier_state)
            return session
        session = _Session(
            state=RunState.RUNNING,
            budget=BudgetTracker(dependencies.budget_limits),
        )
        self._save(run_id, session, dependencies)
        return session

    @staticmethod
    def _save(
        run_id: UUID, session: _Session, dependencies: LoopDependencies
    ) -> None:
        session.classifier_state = AgentLoop._classifier_snapshot(dependencies)
        dependencies.sessions.save_loop_session(session.snapshot(run_id))

    @staticmethod
    def _classifier_snapshot(dependencies: LoopDependencies) -> dict[str, Any] | None:
        snapshot = getattr(dependencies.classifier, "snapshot", None)
        if not callable(snapshot):
            return None
        try:
            value = snapshot()
        except Exception:
            return None
        return value if isinstance(value, dict) else None

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
        self._publish(
            run_id,
            ProgressKind.STATE,
            dependencies,
            text=state.value,
            payload={"from": previous.value, "to": state.value},
        )

    @staticmethod
    def _publish(
        run_id: UUID,
        kind: ProgressKind,
        dependencies: LoopDependencies,
        *,
        text: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            dependencies.progress.publish(
                RunProgress(
                    run_id=run_id,
                    kind=kind,
                    text=text,
                    payload=dict(payload or {}),
                )
            )
        except Exception:
            return
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
    def _block(session: _Session, kind: FeedbackKind) -> None:
        if kind is not FeedbackKind.PASS and kind not in session.completion_blockers:
            session.completion_blockers.append(kind)

    @staticmethod
    def _resolve_blocker(session: _Session, kind: FeedbackKind) -> None:
        session.completion_blockers = [
            blocker for blocker in session.completion_blockers if blocker is not kind
        ]

    @staticmethod
    def _policy_evidence(decision: PolicyDecision) -> PolicyDecisionEvidence:
        return PolicyDecisionEvidence(
            effect=decision.effect.value,
            rule_id=decision.rule_id,
            reason=decision.reason,
        )

    @staticmethod
    def _policy_decision(call: ToolCall, dependencies: LoopDependencies) -> PolicyDecision:
        decision = PolicyDecision.model_validate(
            dependencies.policy.evaluate(
                call,
                dependencies.policy_config,
                dependencies.permission_mode,
            )
        )
        return dependencies.tool_filter.apply(call, decision)

    @staticmethod
    def _summarize_context(context: ModelContext) -> str:
        summary = {
            "task": context.task,
            "message_count": len(context.messages),
            "message_roles": [message.role for message in context.messages],
            "feedback_kinds": [feedback.kind.value for feedback in context.feedback],
            "metadata": redact_payload(context.metadata),
        }
        return json.dumps(summary, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _summary(run_id: UUID, session: _Session) -> RunSummary:
        return RunSummary(
            run_id=run_id,
            status=session.state,
            stop_reason=session.stop_reason,
            changed_files=tuple(session.changed_files),
            validation_evidence=tuple(session.validation_evidence),
            approvals=tuple(session.approvals),
            unresolved_risks=tuple(dict.fromkeys(session.unresolved_risks)),
            completion_blockers=tuple(session.completion_blockers),
            resource_usage=session.budget.usage,
            resource_profile=session.resource_profile.name if session.resource_profile else None,
        )
