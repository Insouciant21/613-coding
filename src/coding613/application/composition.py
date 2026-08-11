"""Default local service composition for the CLI and operations console.

The composition deliberately has no implicit provider credential.  It wires
the real persistence, memory, policy, and loop boundaries; a provider-backed
bundle can replace the deferred provider through the same injected factory.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from coding613.adapters.credentials.keyring import KeyringCredentialStore
from coding613.adapters.embeddings.mock import DeterministicEmbedding
from coding613.adapters.llm.credentialed import (
    AnthropicClientFactory,
    CredentialedAnthropicLLM,
    CredentialedOpenAICompatibleLLM,
    CredentialedResponsesLLM,
    SDKClientFactory,
)
from coding613.adapters.llm.openai_tools import build_responses_tools
from coding613.adapters.storage.lancedb_index import LanceMemoryIndex
from coding613.adapters.storage.memory import MemoryRepository
from coding613.adapters.storage.sqlite import SqliteEventStore
from coding613.adapters.tools.repository import (
    RepositoryValidator,
    build_repository_tools,
)
from coding613.application.approvals import ApprovalService
from coding613.application.budgets import BudgetLimits
from coding613.application.configuration import ConfigurationService
from coding613.application.context import ContextAssembler, ContextService, SessionContextBuilder
from coding613.application.conversation import ConversationService
from coding613.application.diagnostics import DiagnosticService, local_diagnostic_checks
from coding613.application.feedback import FeedbackClassifier
from coding613.application.interactive import (
    ConversationInteractiveAdapter,
    InteractiveSessionService,
)
from coding613.application.loop import AgentLoop, LoopDependencies
from coding613.application.permissions import PermissionRuleService
from coding613.application.policy import PolicyEngine
from coding613.application.progress import CancellationToken
from coding613.application.run_service import RunRequest, RunService
from coding613.application.tool_registry import ToolRegistry
from coding613.application.user_configuration import UserConfigurationService
from coding613.config import (
    DEFAULT_CONTEXT_WINDOW_CHARS,
    MAX_OUTPUT_TOKENS,
    HarnessConfig,
    LLMConfig,
    UserConfig,
    load_config,
)
from coding613.domain.events import Event
from coding613.domain.models import PermissionMode, Project, Run
from coding613.domain.permissions import ToolFilter
from coding613.ports.llm import LLMProvider, LLMResponse, ModelContext, ToolDefinition
from coding613.ports.progress import NullProgressSink


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
        permission_mode: PermissionMode,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        self._events = events
        self._permission_mode = permission_mode

    def create_run(self, request: RunRequest) -> Run:
        updates: dict[str, Any] = {}
        if request.project_id is None:
            updates["project_id"] = self.project.id
        if request.permission_mode is None:
            updates["permission_mode"] = self._permission_mode
        if updates:
            request = request.model_copy(update=updates)
        return super().create_run(request)

    def list_events(self, run_id: UUID) -> list[Event]:
        return self._events.list_for_run(run_id)

    def set_default_permission_mode(self, mode: PermissionMode) -> None:
        self._permission_mode = mode


@dataclass(slots=True)
class _RuntimeConfiguration:
    config: HarnessConfig
    user_config: UserConfig
    provider: LLMProvider
    tools: ToolRegistry
    validator: RepositoryValidator
    changed_files: list[str]


class LocalServices:
    def __init__(
        self,
        run_service: ConfiguredRunService,
        events: SqliteEventStore,
        interactive: InteractiveSessionService,
        *,
        llm_metadata: LLMConfig | None,
        permission_mode: PermissionMode,
        context: ContextService,
        diagnostics: DiagnosticService,
        configuration: ConfigurationService,
        user_configuration: UserConfigurationService,
        active_provider: Callable[[], LLMConfig | None],
        select_provider: Callable[[str], UserConfig],
        select_model: Callable[[str, str], UserConfig],
        set_model_reasoning: Callable[[str, str, str], UserConfig],
        reload_configuration: Callable[[], HarnessConfig],
    ) -> None:
        self.run_service = run_service
        self._events = events
        self._legacy_interactive = interactive
        self.llm_metadata = llm_metadata
        self.permission_mode = permission_mode
        self.configuration = configuration
        self.user_configuration = user_configuration
        self._active_provider = active_provider
        self._select_provider = select_provider
        self._select_model = select_model
        self._set_model_reasoning = set_model_reasoning
        self._reload_configuration = reload_configuration
        self.context = context
        self.diagnostics = diagnostics
        self.permission_rules = PermissionRuleService(self.run_service.project.id, self._events)
        self.conversation = ConversationService(
            self.run_service.project.id,
            self._events,
            self.run_service,
            context=self.context,
            diagnostics=self.diagnostics,
        )
        self.interactive = ConversationInteractiveAdapter(
            self.conversation,
            self.run_service.project.id,
        )

    def list_events(self, run_id: UUID) -> list[Event]:
        return self._events.list_for_run(run_id)

    def reload_configuration(self) -> HarnessConfig:
        config = self._reload_configuration()
        self.llm_metadata = self._active_provider()
        self.permission_mode = config.permission_mode
        self.run_service.set_default_permission_mode(config.permission_mode)
        return config

    def switch_provider(self, name: str) -> UserConfig:
        config = self._select_provider(name)
        self.llm_metadata = self._active_provider()
        return config

    def switch_model(self, provider: str, alias: str) -> UserConfig:
        config = self._select_model(provider, alias)
        self.llm_metadata = self._active_provider()
        return config

    def switch_model_reasoning(
        self, provider: str, alias: str, reasoning_effort: str
    ) -> UserConfig:
        config = self._set_model_reasoning(provider, alias, reasoning_effort)
        self.llm_metadata = self._active_provider()
        return config


def build_services(
    repo_root: str | Path,
    *,
    provider: LLMProvider | None = None,
    credential_store: KeyringCredentialStore | None = None,
    client_factory: SDKClientFactory | None = None,
    anthropic_client_factory: AnthropicClientFactory | None = None,
    user_config_path: str | Path | None = None,
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
    store_for_credentials = credential_store or KeyringCredentialStore()
    user_configuration = UserConfigurationService(
        user_config_path,
        credential_store=store_for_credentials,
    )
    user_config = user_configuration.load()
    active_provider = _active_provider(user_config)
    base_context = ContextAssembler(
        memory,
        index,
        embedding,
        repository_root=root,
        max_context_chars=(
            active_provider.context_window_chars
            if active_provider is not None
            else DEFAULT_CONTEXT_WINDOW_CHARS
        ),
    )
    context = SessionContextBuilder(
        base_context,
        store,
    )
    context_service = ContextService(store)
    policy = PolicyEngine()
    injected_provider = provider is not None
    tools, validator, changed_files = build_repository_tools(root, config.validation_commands)
    runtime = _RuntimeConfiguration(
        config=config,
        user_config=user_config,
        provider=provider or _build_provider(
            active_provider,
            store_for_credentials,
            client_factory,
            anthropic_client_factory,
        ),
        tools=tools,
        validator=validator,
        changed_files=changed_files,
    )

    def dependencies(run: Run) -> LoopDependencies:
        selected_provider = _active_provider(runtime.user_config)
        policy_config = runtime.config.policy.model_copy(
            update={"permission_rules": tuple(store.list_permission_rules(project.id))}
        )
        return LoopDependencies(
            context_builder=context,
            provider=runtime.provider,
            tools=runtime.tools,
            policy=policy,
            policy_config=policy_config,
            permission_mode=run.permission_mode,
            approvals=ApprovalService(run_id=run.id, store=store),
            events=store,
            iterations=store,
            sessions=store,
            validator=runtime.validator,
            classifier=FeedbackClassifier(),
            budget_limits=_budget_limits_for_run(
                runtime.user_config.budgets, run.options.budget_overrides
            ),
            revision=lambda: _repository_revision(root, state_root),
            changed_files=lambda: tuple(runtime.changed_files),
            clock=lambda: datetime.now(UTC),
            progress=NullProgressSink(),
            cancellation=CancellationToken(),
            tool_filter=ToolFilter(
                allowed=run.options.allowed_tools,
                disallowed=run.options.disallowed_tools,
            ),
            provider_tools=build_responses_tools(selected_provider)
            if selected_provider is not None
            else (),
            max_output_tokens=_max_output_tokens(runtime.user_config),
        )

    service = ConfiguredRunService(
        project,
        store,
        AgentLoop(),
        dependencies,
        events=store,
        permission_mode=runtime.config.permission_mode,
    )
    interactive = InteractiveSessionService(project.id, store, service)

    def reload_configuration() -> HarnessConfig:
        updated = load_config(root)
        updated_user = user_configuration.load()
        selected = _active_provider(updated_user)
        if not injected_provider:
            previous = runtime.provider
            runtime.provider = _build_provider(
                selected,
                store_for_credentials,
                client_factory,
                anthropic_client_factory,
            )
            close = getattr(previous, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - reload must keep the new config usable
                    close = None
        runtime.config = updated
        runtime.user_config = updated_user
        base_context.set_max_context_chars(
            selected.context_window_chars
            if selected is not None
            else DEFAULT_CONTEXT_WINDOW_CHARS
        )
        (
            runtime.tools,
            runtime.validator,
            runtime.changed_files,
        ) = build_repository_tools(
            root, updated.validation_commands
        )
        service.set_default_permission_mode(updated.permission_mode)
        return updated

    def active_provider_config() -> LLMConfig | None:
        return _active_provider(runtime.user_config)

    def select_provider(name: str) -> UserConfig:
        user_configuration.select_provider(name)
        reload_configuration()
        return runtime.user_config

    def select_model(provider: str, alias: str) -> UserConfig:
        user_configuration.select_model(provider, alias)
        reload_configuration()
        return runtime.user_config

    def set_model_reasoning(provider: str, alias: str, reasoning_effort: str) -> UserConfig:
        user_configuration.set_model_reasoning(provider, alias, reasoning_effort)
        reload_configuration()
        return runtime.user_config

    return LocalServices(
        service,
        store,
        interactive,
        llm_metadata=active_provider,
        permission_mode=runtime.config.permission_mode,
        context=context_service,
        diagnostics=DiagnosticService(
            local_diagnostic_checks(
                root,
                state_root,
                provider_configured=active_provider is not None,
            )
        ),
        configuration=ConfigurationService(root),
        user_configuration=user_configuration,
        active_provider=active_provider_config,
        select_provider=select_provider,
        select_model=select_model,
        set_model_reasoning=set_model_reasoning,
        reload_configuration=reload_configuration,
    )


def _build_provider(
    config: LLMConfig | None,
    credential_store: KeyringCredentialStore,
    client_factory: SDKClientFactory | None,
    anthropic_client_factory: AnthropicClientFactory | None,
) -> LLMProvider:
    if config is None:
        return DeferredLLMProvider()
    config = config.effective()
    if config.api in {"anthropic", "messages"} or config.provider.lower() in {
        "anthropic",
        "anthropic-sdk",
        "claude",
    }:
        anthropic_base_url = (
            None
            if config.base_url == "https://api.openai.com/v1"
            else config.base_url
        )
        return CredentialedAnthropicLLM(
            provider=config.credential,
            base_url=anthropic_base_url,
            model=config.model,
            read_secret=credential_store.read_secret,
            timeout_seconds=config.timeout_seconds,
            client_factory=anthropic_client_factory,
            max_output_tokens=config.max_output_tokens,
            reasoning_effort=config.reasoning_effort,
            streaming=config.streaming,
        )
    if config.api == "responses":
        return CredentialedResponsesLLM(
            provider=config.credential,
            base_url=config.base_url,
            model=config.model,
            read_secret=credential_store.read_secret,
            timeout_seconds=config.timeout_seconds,
            client_factory=client_factory,
            max_output_tokens=config.max_output_tokens,
            reasoning_effort=config.reasoning_effort,
            streaming=config.streaming,
        )
    return CredentialedOpenAICompatibleLLM(
        provider=config.credential,
        base_url=config.base_url,
        model=config.model,
        read_secret=credential_store.read_secret,
        timeout_seconds=config.timeout_seconds,
        client_factory=client_factory,
        max_output_tokens=config.max_output_tokens,
        reasoning_effort=config.reasoning_effort,
        streaming=config.streaming,
    )


def _active_provider(config: UserConfig) -> LLMConfig | None:
    if config.active_provider is None:
        return None
    return config.providers[config.active_provider].effective()


def _max_output_tokens(config: UserConfig) -> int:
    provider = _active_provider(config)
    return provider.max_output_tokens if provider is not None else MAX_OUTPUT_TOKENS


def _repository_revision(root: Path, state_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path == state_root or state_root in path.parents or not path.is_file():
            continue
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _budget_limits_for_run(
    configured: BudgetLimits, overrides: dict[str, Any]
) -> BudgetLimits:
    """Apply invocation-scoped finite limits without mutating project config."""

    if not overrides:
        return configured
    values = configured.model_dump()
    values.update(overrides)
    return BudgetLimits.model_validate(values)
