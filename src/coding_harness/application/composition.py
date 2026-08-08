"""Default local service composition for the CLI and operations console.

The composition deliberately has no implicit provider credential.  It wires
the real persistence, memory, policy, and loop boundaries; a provider-backed
bundle can replace the deferred provider through the same injected factory.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from coding_harness.adapters.embeddings.mock import DeterministicEmbedding
from coding_harness.adapters.storage.lancedb_index import LanceMemoryIndex
from coding_harness.adapters.storage.memory import MemoryRepository
from coding_harness.adapters.storage.sqlite import SqliteEventStore
from coding_harness.application.approvals import ApprovalService
from coding_harness.application.budgets import BudgetLimits
from coding_harness.application.context import ContextAssembler
from coding_harness.application.feedback import FeedbackClassifier
from coding_harness.application.loop import AgentLoop, LoopDependencies
from coding_harness.application.policy import PolicyEngine
from coding_harness.application.run_service import RunRequest, RunService
from coding_harness.application.tool_registry import ToolRegistry
from coding_harness.application.validation import ValidationKind, ValidationResult
from coding_harness.config import load_config
from coding_harness.domain.events import Event
from coding_harness.domain.models import Project, Run
from coding_harness.ports.llm import LLMProvider, LLMResponse, ModelContext, ToolDefinition


class ProviderConfigurationError(RuntimeError):
    """Raised when a local bundle has no configured LLM provider."""


class DeferredLLMProvider(LLMProvider):
    def complete(self, context: ModelContext, tools: Sequence[ToolDefinition]) -> LLMResponse:
        del context, tools
        raise ProviderConfigurationError(
            "no LLM provider is configured; inject an LLMProvider before resuming this run"
        )


class _UnavailableValidator:
    def validate(self) -> ValidationResult:
        return ValidationResult(
            command=("provider-not-configured",),
            kind=ValidationKind.OTHER,
            exit_code=1,
            stderr="validation is unavailable until an LLM provider is configured",
            duration_seconds=0,
        )


class ConfiguredRunService(RunService):
    def __init__(self, project: Project, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.project = project

    def create_run(self, request: RunRequest) -> Run:
        if request.project_id is None:
            request = request.model_copy(update={"project_id": self.project.id})
        return super().create_run(request)


class LocalServices:
    def __init__(self, run_service: ConfiguredRunService, events: SqliteEventStore) -> None:
        self.run_service = run_service
        self._events = events

    def list_events(self, run_id: UUID) -> list[Event]:
        return self._events.list_for_run(run_id)


def build_services(repo_root: str | Path) -> LocalServices:
    root = Path(repo_root).expanduser().resolve(strict=True)
    config = load_config(root)
    state_root = root / ".613-coding"
    state_root.mkdir(parents=True, exist_ok=True)
    store = SqliteEventStore(state_root / "state.sqlite")
    project = store.get_project_by_root(root)
    if project is None:
        project = Project(canonical_root=root)
        store.create_project(project)

    embedding = DeterministicEmbedding(dimension=8)
    memory = MemoryRepository(store.path)
    index = LanceMemoryIndex(state_root / "vectors", dimension=8)
    context = ContextAssembler(memory, index, embedding)
    policy = PolicyEngine()
    provider: LLMProvider = DeferredLLMProvider()

    def dependencies(run: Run) -> LoopDependencies:
        return LoopDependencies(
            context_builder=context,
            provider=provider,
            tools=ToolRegistry(),
            policy=policy,
            policy_config=config.policy,
            permission_mode=run.permission_mode,
            approvals=ApprovalService(run_id=run.id, store=store),
            events=store,
            iterations=store,
            sessions=store,
            validator=_UnavailableValidator(),
            classifier=FeedbackClassifier(),
            budget_limits=BudgetLimits.model_validate(config.budgets.model_dump()),
            revision=lambda: _repository_revision(root, state_root),
            changed_files=lambda: (),
            clock=lambda: datetime.now(UTC),
        )

    service = ConfiguredRunService(
        project,
        store,
        AgentLoop(),
        dependencies,
    )
    return LocalServices(service, store)


def _repository_revision(root: Path, state_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path == state_root or state_root in path.parents or not path.is_file():
            continue
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()
