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

from coding613.adapters.credentials.keyring import KeyringCredentialStore
from coding613.adapters.embeddings.mock import DeterministicEmbedding
from coding613.adapters.llm.credentialed import (
    ClientFactory,
    CredentialedOpenAICompatibleLLM,
)
from coding613.adapters.storage.lancedb_index import LanceMemoryIndex
from coding613.adapters.storage.memory import MemoryRepository
from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.adapters.tools.repository import build_repository_tools
from coding613.application.approvals import ApprovalService
from coding613.application.budgets import BudgetLimits
from coding613.application.context import ContextAssembler
from coding613.application.feedback import FeedbackClassifier
from coding613.application.loop import AgentLoop, LoopDependencies
from coding613.application.policy import PolicyEngine
from coding613.application.run_service import RunRequest, RunService
from coding613.config import load_config
from coding613.domain.events import Event
from coding613.domain.models import Project, Run
from coding613.ports.llm import LLMProvider, LLMResponse, ModelContext, ToolDefinition


class ProviderConfigurationError(RuntimeError):
    """Raised when a local bundle has no configured LLM provider."""


class DeferredLLMProvider(LLMProvider):
    def complete(self, context: ModelContext, tools: Sequence[ToolDefinition]) -> LLMResponse:
        del context, tools
        raise ProviderConfigurationError(
            "no LLM provider is configured; inject an LLMProvider before resuming this run"
        )


class ConfiguredRunService(RunService):
    def __init__(
        self,
        project: Project,
        *args: Any,
        events: SqliteEventStore,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        self._events = events

    def create_run(self, request: RunRequest) -> Run:
        if request.project_id is None:
            request = request.model_copy(update={"project_id": self.project.id})
        return super().create_run(request)

    def list_events(self, run_id: UUID) -> list[Event]:
        return self._events.list_for_run(run_id)


class LocalServices:
    def __init__(self, run_service: ConfiguredRunService, events: SqliteEventStore) -> None:
        self.run_service = run_service
        self._events = events

    def list_events(self, run_id: UUID) -> list[Event]:
        return self._events.list_for_run(run_id)


def build_services(
    repo_root: str | Path,
    *,
    provider: LLMProvider | None = None,
    credential_store: KeyringCredentialStore | None = None,
    client_factory: ClientFactory | None = None,
) -> LocalServices:
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
    if provider is None and config.llm is not None:
        store_for_credentials = credential_store or KeyringCredentialStore()
        provider = CredentialedOpenAICompatibleLLM(
            provider=config.llm.credential,
            base_url=config.llm.base_url,
            model=config.llm.model,
            read_secret=store_for_credentials.read_secret,
            timeout_seconds=config.llm.timeout_seconds,
            client_factory=client_factory,
        )
    provider = provider or DeferredLLMProvider()
    tools, validator, changed_files = build_repository_tools(
        root, config.validation_commands
    )

    def dependencies(run: Run) -> LoopDependencies:
        return LoopDependencies(
            context_builder=context,
            provider=provider,
            tools=tools,
            policy=policy,
            policy_config=config.policy,
            permission_mode=run.permission_mode,
            approvals=ApprovalService(run_id=run.id, store=store),
            events=store,
            iterations=store,
            sessions=store,
            validator=validator,
            classifier=FeedbackClassifier(),
            budget_limits=BudgetLimits.model_validate(config.budgets.model_dump()),
            revision=lambda: _repository_revision(root, state_root),
            changed_files=lambda: tuple(changed_files),
            clock=lambda: datetime.now(UTC),
        )

    service = ConfiguredRunService(
        project,
        store,
        AgentLoop(),
        dependencies,
        events=store,
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
