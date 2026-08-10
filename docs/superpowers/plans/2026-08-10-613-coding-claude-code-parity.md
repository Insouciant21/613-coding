# 613 Coding Claude-Code-Like TUI And CLI Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local Textual TUI and root CLI provide one shared, testable Claude-Code-like coding workflow with follow-up sessions, permissions, resume, context controls, and scriptable output.

**Architecture:** Add a typed conversation request/response boundary above the existing
`InteractiveSessionService` and keep `AgentLoop`, policy, approval, validation, feedback, and
SQLite as the authorities. Adapt progress into a versioned redacted `SessionEvent` stream; the
TUI renders it and the CLI serializes it as text, JSON, or JSON-lines. Persist invocation options
with each Run so resume uses the same policy and model context.

**Tech Stack:** Python 3.12, `uv`, Pydantic, SQLite, Textual, Click/Typer-compatible argparse
root parsing, pytest, Textual Pilot, fake LLM/tool providers, Ruff, mypy.

## Global Constraints

- Start implementation only in a fresh worktree created with `using-git-worktrees`; the main worktree's five modified tracked files and untracked files are user-owned and must remain untouched.
- Use TDD for every task: write a focused failing test, run it and retain the RED result, implement the smallest change, run the focused GREEN test, then refactor while green.
- TUI and CLI adapters call application services and never make policy, tool, validation, retry, budget, or completion decisions.
- Keep the owned `AgentLoop`; do not add LangChain `AgentExecutor`, AutoGen, CrewAI, LlamaIndex agents, MCP transport, or another high-level agent runner in this plan.
- Every provider, store, event sink, serializer, diagnostic check, and compactor is injectable; tests never require a real LLM, network, key, Docker daemon, or Git remote.
- SQLite remains the source of truth. LanceDB is only a rebuildable memory index. Redact before persistence, output, event publication, or embedding.
- Hard safety rules precede repository policy, invocation filters, permission mode, and one-time exact-action approvals. There is no unsafe permission-bypass option.
- Use argv arrays for commands, never `shell=True`; additional directories must pass canonical path and symlink checks.
- Preserve existing management commands and `--json` behavior while adding the root prompt/print contract.
- After each completed task update `PLAN.md`, `AGENT_LOG.md`, and `DELIVERY_STATUS.md` with actual evidence and the task commit hash.

---

## File and boundary map

The implementation is split into seven reviewable units. Each unit has a focused domain boundary,
an independently runnable test set, and a commit. Existing files are extended only where the
current responsibility already belongs; serializers, root parsing, and diagnostics are separate
modules.

- `src/coding613/domain/conversation.py`: immutable prompt/run options, context reports, diagnostic values, and versioned session events.
- `src/coding613/ports/conversation.py`: the application-facing conversation service protocol.
- `src/coding613/application/conversation.py`: session selection, prompt validation, Run creation, execution, and snapshots.
- `src/coding613/application/run_service.py`, `src/coding613/domain/models.py`, `src/coding613/adapters/storage/{schema.sql,sqlite.py}`: persisted invocation options with backward-compatible migration.
- `src/coding613/ports/events.py`, `src/coding613/application/events.py`: progress-to-event bridge, sequencing, redaction, and event sinks.
- `src/coding613/cli/output.py`, `src/coding613/cli/input.py`, `src/coding613/cli/prompt.py`, `src/coding613/cli/entrypoint.py`, `src/coding613/cli/tui.py`: root option decoding, stdin, serializers, exit codes, and non-interactive execution.
- `src/coding613/tui/commands.py`, `src/coding613/tui/controller.py`, `src/coding613/tui/app.py`, `src/coding613/tui/widgets.py`, `src/coding613/tui/renderers.py`: command catalog, history, diagnostics, context actions, and event rendering.
- `src/coding613/domain/permissions.py`, `src/coding613/application/policy.py`, `src/coding613/application/loop.py`, `src/coding613/application/composition.py`: invocation allow/deny filters that cannot override hard policy.
- `src/coding613/application/context.py`, `src/coding613/application/diagnostics.py`, `src/coding613/ports/context.py`, `src/coding613/adapters/storage/{schema.sql,sqlite.py}`: context accounting, explicit compaction, and diagnostics.
- `README.md`, `docs/development.md`, `tests/docs/test_docs.py`, and delivery records: user-facing command/output/permission documentation and evidence.

## Worktree and baseline gate

Before Task 1, execute the `using-git-worktrees` skill and create an isolated branch from the
current committed `main` tip:

```bash
git check-ignore -q .worktrees
git worktree add .worktrees/claude-code-parity -b feature/claude-code-parity HEAD
cd .worktrees/claude-code-parity
uv run pytest -q --ignore=tmp
uv run ruff check .
uv run mypy src
```

Record the exact baseline counts. If `.worktrees` is not ignored, use the skill's documented
fallback directory outside the repository. Do not copy or stage the dirty main-worktree files.

---

### Task 1: Typed conversation requests and resumable invocation options

**Files:**
- Create: `src/coding613/domain/conversation.py`
- Create: `src/coding613/ports/conversation.py`
- Create: `src/coding613/application/conversation.py`
- Modify: `src/coding613/domain/models.py`
- Modify: `src/coding613/application/run_service.py`
- Modify: `src/coding613/application/interactive.py`
- Modify: `src/coding613/adapters/storage/schema.sql`
- Modify: `src/coding613/adapters/storage/sqlite.py`
- Modify: `tests/application/test_interactive.py`
- Modify: `tests/adapters/storage/test_sqlite.py`
- Create: `tests/domain/test_conversation.py`
- Create: `tests/application/test_conversation.py`

**Interfaces:**
- Produces `RunOptions(model: str | None, allowed_tools: frozenset[str], disallowed_tools: frozenset[str], additional_dirs: tuple[str, ...], system_prompt: str | None, append_system_prompt: str | None, budget_overrides: dict[str, Any])`.
- Produces `PromptRequest(project_id: UUID, text: str, session_id: UUID | None = None, continue_latest: bool = False, options: RunOptions = ...)`.
- Produces `ContextSummary(summary_revision: str, included_sources: tuple[str, ...], omitted_sources: tuple[str, ...], estimated_tokens: int, max_tokens: int)`.
- Produces `DiagnosticCheck(name: str, status: Literal["pass", "warn", "fail"], detail: str)` and `DiagnosticReport(project_id: UUID, checks: tuple[DiagnosticCheck, ...])`.
- Produces `ConversationService.create_session(title: str | None = None) -> InteractiveSession`, `submit(request: PromptRequest) -> Run`, `execute(run_id: UUID, sink: ProgressSink, cancellation: CancellationToken) -> RunSummary`, `snapshot(session_id: UUID) -> InteractiveSnapshot`, and `sessions() -> list[InteractiveSession]`.
- Adds `Run.options: RunOptions` and `RunRequest.options: RunOptions`, defaulting to an empty value so legacy JSON and SQLite rows remain valid.

- [x] **Step 1: Write the failing domain and persistence tests**

```python
def test_prompt_request_rejects_conflicting_session_selection() -> None:
    with pytest.raises(ValueError, match="continue_latest"):
        PromptRequest(
            project_id=uuid4(),
            text="inspect",
            session_id=uuid4(),
            continue_latest=True,
        )


def test_legacy_run_round_trip_has_empty_options(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.sqlite")
    run = Run(task="legacy task")
    store.create_run(run)
    loaded = store.get_run(run.id)
    assert loaded is not None
    assert loaded.options == RunOptions()


def test_run_options_survive_storage_round_trip(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.sqlite")
    options = RunOptions(
        model="gpt-test",
        allowed_tools=frozenset({"read_file"}),
        append_system_prompt="Use the repository convention.",
    )
    run = Run(task="inspect", options=options)
    store.create_run(run)
    assert store.get_run(run.id).options == options  # type: ignore[union-attr]
```

- [x] **Step 2: Run the RED tests**

```bash
uv run pytest tests/domain/test_conversation.py tests/application/test_conversation.py tests/adapters/storage/test_sqlite.py -q
```

Expected failure: `RunOptions`, `PromptRequest`, `ConversationService`, and the `options_json`
column do not exist.

- [x] **Step 3: Add immutable values and migration-safe storage**

Use Pydantic frozen values. Validate nonblank tool names and prompt text, reject a tool appearing
in both filters, cap option strings at 100,000 characters, and store additional directories as
normalized strings without resolving them in the domain. Add `options_json TEXT NOT NULL DEFAULT '{}'`
to the new `runs` schema. In the SQLite initializer, inspect `PRAGMA table_info(runs)` and add the
column inside the existing transaction when absent. Encode/decode only the non-secret options
fields with sorted JSON; omit prompt contents from option metadata.

- [x] **Step 4: Implement the conversation facade and preserve wrappers**

`ConversationService.submit` must select an explicit session, the latest project session, or a new
session in that order; it must reject a session belonging to another project before creating a
Run. It delegates execution to `RunService` and snapshots to the existing store. Adapt
`InteractiveSessionService.submit` to construct `PromptRequest` so current TUI tests and callers
remain valid. Pass `RunOptions.model` into `ModelContext.metadata["model"]` through the existing
dependency factory without placing it in logs or events.

- [x] **Step 5: Run focused GREEN and static checks**

```bash
uv run pytest tests/domain/test_conversation.py tests/application/test_conversation.py tests/application/test_interactive.py tests/adapters/storage/test_sqlite.py -q
uv run ruff check src/coding613/domain/conversation.py src/coding613/ports/conversation.py src/coding613/application/conversation.py src/coding613/application/run_service.py src/coding613/application/interactive.py src/coding613/adapters/storage tests/domain/test_conversation.py tests/application/test_conversation.py
uv run mypy src/coding613/domain src/coding613/ports/conversation.py src/coding613/application/conversation.py src/coding613/application/run_service.py src/coding613/application/interactive.py src/coding613/adapters/storage
```

- [x] **Step 6: Commit the typed conversation boundary**

```bash
git add src/coding613/domain/conversation.py src/coding613/domain/models.py src/coding613/ports/conversation.py src/coding613/application/conversation.py src/coding613/application/run_service.py src/coding613/application/interactive.py src/coding613/adapters/storage/schema.sql src/coding613/adapters/storage/sqlite.py tests/domain/test_conversation.py tests/application/test_conversation.py tests/application/test_interactive.py tests/adapters/storage/test_sqlite.py
git commit -m "feat: add shared conversation request boundary"
```

---

### Task 2: Versioned session events and output serializers

**Files:**
- Create: `src/coding613/ports/events.py`
- Create: `src/coding613/application/events.py`
- Create: `src/coding613/cli/output.py`
- Modify: `src/coding613/ports/progress.py`
- Modify: `src/coding613/tui/controller.py`
- Modify: `src/coding613/domain/events.py`
- Create: `tests/application/test_events.py`
- Create: `tests/cli/test_output.py`
- Modify: `tests/tui/test_controller.py`

**Interfaces:**
- Produces `SessionEvent(event_id: UUID, schema_version: int = 1, sequence: int, session_id: UUID, run_id: UUID, type: EventType, timestamp: datetime, data: dict[str, Any])`.
- Produces `EventType` values `session.started`, `user.message`, `assistant.delta`, `tool.started`, `tool.finished`, `validation.started`, `validation.finished`, `approval.requested`, `run.paused`, `run.completed`, `run.failed`, and `diagnostic.completed`.
- Produces `EventSink.publish(event: SessionEvent) -> None`, `SequencedEventSink`, and `ProgressEventBridge(session_id, run_id, sink)`.
- Produces `RunEnvelope.from_summary(summary: RunSummary, session_id: UUID, assistant_text: str, events: tuple[SessionEvent, ...])`, `TextOutputSerializer.render(envelope: RunEnvelope, verbose: bool)`, `JsonOutputSerializer.render(envelope: RunEnvelope)`, and `StreamJsonSerializer.render_event(event: SessionEvent)`.

- [x] **Step 1: Write the failing event and serializer tests**

```python
def test_progress_bridge_sequences_and_redacts_tool_output() -> None:
    sink = RecordingEventSink()
    bridge = ProgressEventBridge(session_id, run_id, sink)
    bridge.publish(RunProgress(run_id=run_id, kind=ProgressKind.TOOL_FINISHED, payload={"tool_call_id": "c1", "output": "token=secret-value"}))
    bridge.publish(RunProgress(run_id=run_id, kind=ProgressKind.TEXT_DELTA, text="done"))
    assert [event.sequence for event in sink.events] == [1, 2]
    assert "secret-value" not in json.dumps(sink.events[0].data)


def test_stream_json_is_one_versioned_redacted_line_per_event() -> None:
    rendered = StreamJsonSerializer().render_event(event)
    value = json.loads(rendered)
    assert value["schema_version"] == 1
    assert value["sequence"] == 1
    assert rendered.endswith("\n")
```

- [x] **Step 2: Run the RED tests**

```bash
uv run pytest tests/application/test_events.py tests/cli/test_output.py tests/tui/test_controller.py -q
```

Expected failure: no versioned event envelope or serializer exists, and progress is still keyed
only by the current TUI rendering path.

- [x] **Step 3: Implement immutable events and sequencing**

Make `SessionEvent` frozen and validate timezone-aware timestamps, positive sequence numbers, and
JSON-compatible data. `SequencedEventSink` assigns the next sequence atomically and applies the
existing `redact_payload` before forwarding. `ProgressEventBridge` maps each `ProgressKind` to an
`EventType`, copies `tool_call_id`, and never uses a tool name as identity. Keep token deltas
ephemeral; only the selected output sink receives them.

- [x] **Step 4: Implement the three serializers**

Text output returns assistant text plus `status=<state> stop_reason=<reason>` and includes tool/
validation detail only when verbose. JSON serializes one `RunEnvelope`; when `--input-format
stream-json` yields multiple runs, serialize a `SessionEnvelope` containing
`schema_version`, `session_id`, and ordered `runs`. Stream JSON emits exactly one compact object
per line and ends with a terminal run event. Use `model_dump(mode="json")`, sorted keys, and no
secret-bearing exception chaining.

- [x] **Step 5: Connect the controller without changing policy**

Give `TuiController` a queue-backed `EventSink` and retain a compatibility `drain_progress` view
for existing tests. The controller creates one bridge per run and forwards both progress rendering
and serialized event output through the shared sequencing boundary.

- [x] **Step 6: Run focused GREEN and static checks**

```bash
uv run pytest tests/application/test_events.py tests/cli/test_output.py tests/tui/test_controller.py -q
uv run ruff check src/coding613/ports/events.py src/coding613/application/events.py src/coding613/cli/output.py src/coding613/tui/controller.py tests/application/test_events.py tests/cli/test_output.py
uv run mypy src/coding613/ports/events.py src/coding613/application/events.py src/coding613/cli/output.py src/coding613/tui/controller.py
```

- [x] **Step 7: Commit event and output contracts**

```bash
git add src/coding613/ports/events.py src/coding613/application/events.py src/coding613/cli/output.py src/coding613/ports/progress.py src/coding613/tui/controller.py src/coding613/domain/events.py tests/application/test_events.py tests/cli/test_output.py tests/tui/test_controller.py
git commit -m "feat: add versioned conversation event stream"
```

---

### Task 3: Root print CLI, stdin, continuation, and exit codes

**Files:**
- Create: `src/coding613/cli/input.py`
- Create: `src/coding613/cli/prompt.py`
- Create: `src/coding613/cli/exit_codes.py`
- Modify: `src/coding613/cli/entrypoint.py`
- Modify: `src/coding613/cli/tui.py`
- Modify: `src/coding613/cli/main.py`
- Modify: `tests/cli/test_entrypoint.py`
- Create: `tests/cli/test_prompt.py`
- Create: `tests/cli/test_input.py`

**Interfaces:**
- Produces `RootLaunchRequest(repo: Path, prompt: str | None, print_mode: bool, continue_latest: bool, resume: str | None, input_format: InputFormat, output_format: OutputFormat, model: str | None, permission_mode: PermissionMode, options: RunOptions, verbose: bool)`.
- Produces `parse_root_args(argv: Sequence[str]) -> RootLaunchRequest` and `run_print(request, services_factory, stdin, stdout) -> int`.
- Produces `parse_text_input(stream) -> tuple[str, ...]` and `parse_stream_json_input(stream) -> tuple[str, ...]`; malformed JSON, unknown schema versions, and blank prompts raise `InputFormatError`.
- Produces `ExitCode` values `SUCCESS=0`, `FAILURE=1`, `INVALID_INPUT=2`, `POLICY_BLOCKED=3`, `PROVIDER_UNAVAILABLE=4`, and `BUDGET_STOP=5`.

- [x] **Step 1: Write the failing root and stdin tests**

```python
def test_print_request_captures_prompt_and_options() -> None:
    request = parse_root_args([
        "-p", "--repo", str(repo), "--output-format", "json",
        "--permission-mode", "strict", "--model", "gpt-test", "repair tests",
    ])
    assert request.print_mode is True
    assert request.prompt == "repair tests"
    assert request.options.model == "gpt-test"
    assert request.permission_mode is PermissionMode.STRICT


def test_stream_json_input_preserves_order_and_rejects_unknown_type() -> None:
    assert parse_stream_json_input(io.StringIO('{"schema_version":1,"type":"user.message","text":"one"}\n{"schema_version":1,"type":"user.message","text":"two"}\n')) == ("one", "two")
    with pytest.raises(InputFormatError, match="unknown event type"):
        parse_stream_json_input(io.StringIO('{"schema_version":1,"type":"tool.result","text":"x"}\n'))
```

- [x] **Step 2: Run the RED tests**

```bash
uv run pytest tests/cli/test_prompt.py tests/cli/test_input.py tests/cli/test_entrypoint.py -q
```

Expected failure: the root parser only understands `--repo`/`--resume`, and no print execution or
input decoder exists.

- [x] **Step 3: Implement strict root parsing**

Parse management commands before root options. Support the canonical options from the approved
spec, both `--allowed-tools`/`--allowedTools` and `--disallowed-tools`/`--disallowedTools`, repeated
`--add-dir`, `--`, and a prompt remainder. Reject `--continue` with an explicit `--resume`, reject
`--system-prompt` plus an empty value, validate paths before service construction, and preserve the
current no-argument TUI behavior.

- [x] **Step 4: Implement input decoding and exit mapping**

Text input reads one prompt from the positional value or stdin. Stream JSON validates each line
with Pydantic and returns ordered user-message texts. Map `RunSummary` stop reasons and typed
provider/policy/input exceptions to the `ExitCode` table; never print exception causes that may
contain credentials.

- [x] **Step 5: Implement `run_print` on the shared service**

Build services once, select/create/continue the session through `ConversationService`, execute each
prompt in order with a `SequencedEventSink`, and call the selected serializer. A prompt invocation
without `-p` launches the existing TUI with the same `RootLaunchRequest`; `-p` never imports or
starts Textual. Inject stdin/stdout and the service factory for tests.

- [x] **Step 6: Add CLI contract tests for every option**

Assert that `--continue`, `--resume`, model, permission mode, tool filters, additional directories,
system-prompt options, all four budget options, verbose, text/json/stream-json, and `--` reach one
`PromptRequest` with no duplicate Run. Assert invalid options fail before `create_session` or
`create_run` is called. Add success, provider, policy, validation, timeout, and budget exit tests.

- [x] **Step 7: Run focused GREEN and static checks**

```bash
uv run pytest tests/cli/test_prompt.py tests/cli/test_input.py tests/cli/test_entrypoint.py tests/cli/test_output.py -q
uv run ruff check src/coding613/cli tests/cli
uv run mypy src/coding613/cli
```

- [x] **Step 8: Commit the print CLI**

```bash
git add src/coding613/cli/input.py src/coding613/cli/prompt.py src/coding613/cli/exit_codes.py src/coding613/cli/entrypoint.py src/coding613/cli/tui.py src/coding613/cli/main.py tests/cli/test_prompt.py tests/cli/test_input.py tests/cli/test_entrypoint.py
git commit -m "feat: add prompt and print CLI modes"
```

---

### Task 4: TUI command catalog, history, diagnostics, and context actions

**Files:**
- Modify: `src/coding613/tui/commands.py`
- Modify: `src/coding613/tui/controller.py`
- Modify: `src/coding613/tui/app.py`
- Modify: `src/coding613/tui/widgets.py`
- Modify: `src/coding613/tui/renderers.py`
- Modify: `src/coding613/tui/styles.tcss`
- Modify: `tests/tui/test_commands.py`
- Modify: `tests/tui/test_controller.py`
- Modify: `tests/tui/test_app.py`
- Modify: `tests/tui/test_renderers.py`

**Interfaces:**
- Produces `CommandSpec(name: str, usage: str, description: str, argument_parser: Callable[[tuple[str, ...]], ParsedCommand])` and `CommandCatalog.parse(text)`, `.help(name: str | None)`, and `.names()`.
- Extends `TuiController` with `history()`, `context_report()`, `compact()`, `diagnostics()`, and `status()` methods that delegate to injected services.
- Extends `TaskComposer` with draft/history navigation without writing history outside the session store.

- [x] **Step 1: Write failing catalog and Pilot tests**

```python
def test_catalog_lists_and_parses_all_commands() -> None:
    catalog = CommandCatalog.default()
    assert {"help", "compact", "context", "cost", "doctor", "model", "permissions", "resume", "runs", "status", "clear", "quit"} <= set(catalog.names())
    assert catalog.parse('/resume latest').arguments == ("latest",)
    with pytest.raises(ValueError, match="unknown slash command"):
        catalog.parse('/not-a-command')


async def test_pilot_history_restores_previous_prompt() -> None:
    app = CodingApp(controller=fake_controller())
    async with app.run_test() as pilot:
        composer = app.query_one(TaskComposer)
        composer.load_text("first")
        await pilot.press("enter")
        await pilot.press("up")
        assert composer.text == "first"
```

- [x] **Step 2: Run RED tests**

```bash
uv run pytest tests/tui/test_commands.py tests/tui/test_controller.py tests/tui/test_app.py -q
```

Expected failure: commands are hard-coded in `CodingApp`, no history navigation exists, and
controller methods for context/diagnostics are absent.

- [x] **Step 3: Add the command catalog and strict argument parsers**

Move command definitions into `CommandCatalog.default()` for `/help`, `/clear`, `/compact`,
`/context`, `/cost`, `/doctor`, `/model`, `/permissions`, `/resume`, `/runs`, `/status`, and
`/quit`. Keep `shlex` parsing, validate modes and UUIDs, and make `/help [COMMAND]` use the same
catalog as parsing. `//text` becomes a model prompt beginning with `/text`.

- [x] **Step 4: Add controller service calls and prompt history**

Have the controller pass `PromptRequest` options to `ConversationService`, serialize history from
the current snapshot's user transcript entries, and expose async wrappers for context, compaction,
diagnostics, cost, and status. Keep all blocking calls in `asyncio.to_thread`. History navigation
must preserve the current draft and never submit automatically.

- [x] **Step 5: Render active operation, diagnostics, context, and long output safely**

Add widgets for context source counts, compaction result, diagnostic check status, cost/budget, and
pending approvals. Use call IDs for tool widget maps; render long paths/output in scrollable
containers and redact values before mounting. Keep input disabled only while a blocking operation
is active or approval is unresolved.

- [x] **Step 6: Run focused GREEN, Pilot, and static checks**

```bash
uv run pytest tests/tui/test_commands.py tests/tui/test_controller.py tests/tui/test_app.py tests/tui/test_renderers.py -q
uv run ruff check src/coding613/tui tests/tui
uv run mypy src/coding613/tui
```

- [x] **Step 7: Commit the TUI parity adapter**

```bash
git add src/coding613/tui tests/tui
git commit -m "feat: expand tui conversation controls"
```

---

### Task 5: Invocation tool filters and permission-rule persistence

**Files:**
- Create: `src/coding613/domain/permissions.py`
- Modify: `src/coding613/application/policy.py`
- Modify: `src/coding613/application/loop.py`
- Modify: `src/coding613/application/composition.py`
- Modify: `src/coding613/application/run_service.py`
- Modify: `src/coding613/adapters/storage/schema.sql`
- Modify: `src/coding613/adapters/storage/sqlite.py`
- Modify: `src/coding613/tui/commands.py`
- Modify: `src/coding613/cli/prompt.py`
- Create: `tests/application/test_permission_filters.py`
- Modify: `tests/application/test_policy.py`
- Modify: `tests/application/test_loop.py`
- Modify: `tests/adapters/storage/test_sqlite.py`
- Modify: `tests/tui/test_commands.py`
- Modify: `tests/cli/test_prompt.py`

**Interfaces:**
- Produces `ToolFilter(allowed: frozenset[str], disallowed: frozenset[str])` with validated tool identifiers and `apply(call: ToolCall, decision: PolicyDecision) -> PolicyDecision`.
- Adds `tool_filter: ToolFilter` to `LoopDependencies`, defaulting to empty filters for existing tests.
- Produces `PermissionRule(scope: Literal["tool", "path"], pattern: str, effect: Literal["allow", "deny"])` and a store protocol for project-scoped rules.
- Produces `/permissions list`, `/permissions allow TOOL`, `/permissions deny TOOL`, and `/permissions clear TOOL` through the application service; UI parsing never edits SQLite directly.

- [x] **Step 1: Write RED precedence and persistence tests**

```python
def test_disallowed_tool_cannot_override_hard_secret_denial(tmp_path: Path) -> None:
    call = ToolCall(name="read_file", arguments={"path": "config", "token": "secret"})
    hard = PolicyEngine().evaluate(call, RepositoryPolicyConfig(repository_root=tmp_path), PermissionMode.AUTONOMOUS)
    result = ToolFilter(disallowed=frozenset({"read_file"})).apply(call, hard)
    assert result.effect is PolicyEffect.DENY
    assert result.rule_id == "hard.secret_material"


def test_project_permission_rule_round_trip(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.sqlite")
    rule = PermissionRule(scope="tool", pattern="read_file", effect="allow")
    store.save_permission_rule(project_id, rule)
    assert store.list_permission_rules(project_id) == [rule]
```

- [x] **Step 2: Run RED tests**

```bash
uv run pytest tests/application/test_permission_filters.py tests/application/test_policy.py tests/application/test_loop.py tests/adapters/storage/test_sqlite.py -q
```

Expected failure: `ToolFilter`, `PermissionRule`, `LoopDependencies.tool_filter`, and the rule
table do not exist.

- [x] **Step 3: Implement filters after hard policy evaluation**

Keep `PolicyEngine.evaluate` first so hard denial identifiers win. Apply invocation filters only
when the policy decision is not already `DENY`; an allowlist denies names not listed and a denylist
denies listed names. A filter never changes a hard denial into allow or changes an unknown tool into
an allowed tool. Persist the selected filters in `RunOptions` and inject them when a Run's loop
dependencies are built.

- [x] **Step 4: Add schema-validated project rules**

Create `permission_rules(project_id, scope, pattern, effect, created_at)` with a uniqueness key.
Migrate existing databases idempotently. Validate tool patterns against the registered tool names,
normalize path patterns without resolving outside the project, and reject shell syntax or secret
material. The PolicyEngine consults rules after hard checks and repository policy but before mode
and approval.

- [x] **Step 5: Connect CLI/TUI commands and tests**

Route CLI tool options and slash commands through `PromptRequest.options` and the conversation
service. Test that invalid tools fail before a Run exists, exact rules persist across a new service
composition, strict writes still ask for approval, autonomous mode still denies hard escapes, and
approval rechecks the current policy before execution.

- [x] **Step 6: Run focused GREEN and static checks**

```bash
uv run pytest tests/application/test_permission_filters.py tests/application/test_policy.py tests/application/test_loop.py tests/adapters/storage/test_sqlite.py tests/tui/test_commands.py tests/cli/test_prompt.py -q
uv run ruff check src/coding613/domain/permissions.py src/coding613/application/policy.py src/coding613/application/loop.py src/coding613/application/composition.py src/coding613/adapters/storage tests/application/test_permission_filters.py
uv run mypy src/coding613/domain/permissions.py src/coding613/application/policy.py src/coding613/application/loop.py src/coding613/application/composition.py src/coding613/adapters/storage
```

- [x] **Step 7: Commit the permission boundary**

```bash
git add src/coding613/domain/permissions.py src/coding613/application/policy.py src/coding613/application/loop.py src/coding613/application/composition.py src/coding613/application/run_service.py src/coding613/adapters/storage/schema.sql src/coding613/adapters/storage/sqlite.py src/coding613/tui/commands.py src/coding613/cli/prompt.py tests/application/test_permission_filters.py tests/application/test_policy.py tests/application/test_loop.py tests/adapters/storage/test_sqlite.py tests/tui/test_commands.py tests/cli/test_prompt.py
git commit -m "feat: enforce invocation permission filters"
```

---

#### Task 5 execution evidence

- RED: `uv run pytest tests/application/test_permission_filters.py tests/adapters/storage/test_permissions.py -q` initially reported the missing SQLite permission-rule methods; policy RED then reported that `RepositoryPolicyConfig` ignored project rules; loop RED reported the missing `LoopDependencies.tool_filter` field; application-service RED reported the missing module.
- GREEN: permission, policy, loop, composition, storage, TUI, and CLI focused suite passed 126 tests. Final Task 5 gate passed 36 focused tests, `uv run ruff check .`, `uv run mypy src`, and `git diff --check`.
- Commit: `b7111cd` (`feat: enforce invocation permission filters`). Hard safety decisions remain authoritative; invocation filters and persisted project rules cannot turn a denial into an allow.

### Task 6: Context accounting, explicit compaction, and diagnostics

**Files:**
- Create: `src/coding613/ports/context.py`
- Create: `src/coding613/application/diagnostics.py`
- Modify: `src/coding613/application/context.py`
- Modify: `src/coding613/application/composition.py`
- Modify: `src/coding613/adapters/storage/schema.sql`
- Modify: `src/coding613/adapters/storage/sqlite.py`
- Modify: `src/coding613/ports/llm.py`
- Modify: `src/coding613/adapters/llm/openai_compatible.py`
- Modify: `src/coding613/tui/controller.py`
- Modify: `tests/application/test_context.py`
- Create: `tests/application/test_diagnostics.py`
- Create: `tests/application/test_compaction.py`
- Modify: `tests/adapters/llm/test_openai_compatible.py`
- Modify: `tests/tui/test_controller.py`

**Interfaces:**
- Produces `ContextService.report(session_id: UUID) -> ContextSummary` and `compact(session_id: UUID) -> ContextSummary`.
- Produces `ContextCompactor.compact(transcript: tuple[TranscriptEntry, ...], max_chars: int) -> str` and a deterministic fake for tests.
- Produces `DiagnosticCheck`/`DiagnosticReport` results through `DiagnosticService.run(project_id: UUID)` with injected checks.
- Adds `context_summary(session_id, revision, text, created_at)` persistence; original transcript rows remain unchanged.
- Allows `ModelContext.metadata["model"]`, `metadata["system_prompt"]`, and `metadata["append_system_prompt"]` to alter one provider request without logging secret values.

- [ ] **Step 1: Write RED accounting, compaction, diagnostics, and model override tests**

```python
def test_context_report_counts_omitted_entries_without_deleting_transcript(fake_store) -> None:
    summary = service.report(session_id)
    assert summary.estimated_tokens > 0
    assert summary.omitted_sources
    before = fake_store.list_runs_for_session(session_id)
    service.compact(session_id)
    assert fake_store.list_runs_for_session(session_id) == before


def test_openai_adapter_uses_context_model_override(fake_client) -> None:
    provider = OpenAICompatibleLLM(
        "https://api.example.test/v1",
        "configured-model",
        fake_client,
    )
    provider.complete(
        ModelContext(run_id=uuid4(), task="x", metadata={"model": "gpt-test"}),
        (),
    )
    assert fake_client.chat.completions.calls[0]["model"] == "gpt-test"
```

- [ ] **Step 2: Run RED tests**

```bash
uv run pytest tests/application/test_context.py tests/application/test_compaction.py tests/application/test_diagnostics.py tests/adapters/llm/test_openai_compatible.py tests/tui/test_controller.py -q
```

Expected failure: no summary store, context service, diagnostics service, or per-request model /
system-prompt override exists.

- [ ] **Step 3: Add authoritative summary storage and deterministic accounting**

Create the summary table and migration. Extend `SessionContextBuilder` to expose included and
omitted transcript entries, memory IDs, and a character-based token estimate. `ContextService`
persists a redacted summary revision; a failed compactor leaves the table and transcript unchanged.
Use a deterministic fake compactor in tests and make the real compactor an injected provider seam.

- [ ] **Step 4: Add system-prompt and model metadata safely**

Merge `RunOptions.system_prompt`/`append_system_prompt` into model messages at context assembly.
Use `metadata["model"]` only as a provider request override, preserving the configured model when
absent. Whitelist these metadata keys, redact values in events, and test that no credentials or
full environment data enter the context.

- [ ] **Step 5: Implement injected diagnostics**

Create checks for repository readability, harness configuration, provider metadata/credential
availability without reading key material, writable state directory, and optional Docker Engine
availability. Each check returns pass/warn/fail with redacted detail; a failed optional check does
not mutate run state. `/doctor` and CLI verbose diagnostics call this service.

- [ ] **Step 6: Run focused GREEN and static checks**

```bash
uv run pytest tests/application/test_context.py tests/application/test_compaction.py tests/application/test_diagnostics.py tests/adapters/llm/test_openai_compatible.py tests/tui/test_controller.py -q
uv run ruff check src/coding613/ports/context.py src/coding613/application/context.py src/coding613/application/diagnostics.py src/coding613/application/composition.py src/coding613/adapters/llm/openai_compatible.py tests/application/test_compaction.py tests/application/test_diagnostics.py
uv run mypy src/coding613/ports/context.py src/coding613/application/context.py src/coding613/application/diagnostics.py src/coding613/application/composition.py src/coding613/adapters/llm/openai_compatible.py
```

- [ ] **Step 7: Commit context and diagnostics**

```bash
git add src/coding613/ports/context.py src/coding613/application/context.py src/coding613/application/diagnostics.py src/coding613/application/composition.py src/coding613/adapters/storage/schema.sql src/coding613/adapters/storage/sqlite.py src/coding613/ports/llm.py src/coding613/adapters/llm/openai_compatible.py src/coding613/tui/controller.py tests/application/test_context.py tests/application/test_compaction.py tests/application/test_diagnostics.py tests/adapters/llm/test_openai_compatible.py tests/tui/test_controller.py
git commit -m "feat: add context compaction and diagnostics"
```

---

### Task 7: Documentation, compatibility suite, and final delivery evidence

**Files:**
- Modify: `README.md`
- Modify: `docs/development.md`
- Modify: `tests/test_docs.py`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `SPEC_PROCESS.md`
- Modify: `DELIVERY_STATUS.md`
- Create: `tests/cli/test_parity_contract.py`
- Create: `tests/tui/test_parity_contract.py`

**Interfaces:**
- Documents root interactive/print commands, stdin stream format, output schemas, exit codes,
  session continuation, permissions, `.env` risk, keyring, Docker Engine requirement, and the
  explicit MCP boundary.
- Produces an offline deterministic parity demo that performs a wrong patch, failed validation,
  feedback repair, successful validation, approval blocking, and resume using fake provider/tool
  fixtures.

- [ ] **Step 1: Write failing documentation and end-to-end contract tests**

```python
def test_readme_documents_print_stream_and_resume_contract() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    for marker in ("613-coding -p", "--output-format stream-json", "--continue", "--resume", "permission-mode"):
        assert marker in text


def test_print_and_tui_use_the_same_fake_conversation_service() -> None:
    assert run_print(fake_request, services_factory=fake_services) == 0
    assert pilot_submits_initial_prompt(fake_services) == fake_services.recorded_requests
```

- [ ] **Step 2: Run RED tests**

```bash
uv run pytest tests/test_docs.py tests/cli/test_parity_contract.py tests/tui/test_parity_contract.py -q
```

Expected failure: README lacks the new command/output contract and no cross-adapter parity test
exists.

- [ ] **Step 3: Update user documentation and examples**

Document interactive, prompt, print, stdin, stream-JSON, continue/resume, model, permissions,
tool filters, context commands, exit codes, supported platforms, keyring setup, `.env` plaintext
risk, Docker Engine sandbox requirement, and the non-MCP boundary. Keep the student-authored
`REFLECTION.md` untouched except for a disclosure if the student elects to edit it.

- [ ] **Step 4: Add the deterministic cross-adapter demo**

Use a fake provider sequence and temporary repository to prove both adapters submit identical
`PromptRequest` values and receive identical terminal summaries. Assert redaction, no network, no
real keyring read, policy approval, failed validation feedback, repaired file, fresh passing
validation, and persisted resume.

- [ ] **Step 5: Run the complete verification gate**

```bash
uv run pytest -q --ignore=tmp
uv run ruff check .
uv run mypy src
uv lock --check
git diff --check
```

Also run a pseudo-terminal smoke for `613-coding --help`, `613-coding -p` with the deterministic
provider fixture, and an 80x24 Textual Pilot session. Record exact pass counts, warnings, and any
environment-only skips; do not claim an unrun provider, Docker, or remote CI check.

- [ ] **Step 6: Perform spec-compliance and code-quality review**

Review every item in `docs/superpowers/specs/2026-08-10-613-coding-claude-code-parity-design.md`,
then review type boundaries, redaction, migration idempotence, exit codes, and main-worktree
protection. Resolve all Critical findings before integration.

- [ ] **Step 7: Update delivery records with evidence**

For each task, record the RED command/result, GREEN command/result, static checks, commit hash,
review findings, human intervention, and lesson in `AGENT_LOG.md`; update the task checkbox and
verification in `PLAN.md`; add the design/plan links and final timestamp to `DELIVERY_STATUS.md`.

- [ ] **Step 8: Commit documentation and evidence**

```bash
git add README.md docs/development.md tests/test_docs.py tests/cli/test_parity_contract.py tests/tui/test_parity_contract.py PLAN.md AGENT_LOG.md SPEC_PROCESS.md DELIVERY_STATUS.md
git commit -m "docs: document Claude Code parity contracts"
```

## Self-review checklist

- Spec coverage: shared service and session state are Task 1; event and output contracts are Task 2;
  root CLI and stdin are Task 3; all TUI controls are Task 4; permission precedence is Task 5;
  context, compaction, diagnostics, and model/system-prompt overrides are Task 6; documentation,
  deterministic demo, review, and evidence are Task 7.
- Reserved-marker scan: the plan contains no unresolved implementation marker or unspecified
  implementation step; each task has explicit files, signatures, RED command, implementation
  action, GREEN command, and commit command.
- Type consistency: `RunOptions` is produced by Task 1 and consumed by Tasks 3, 5, and 6;
  `PromptRequest` is produced by Task 1 and consumed by Tasks 3 and 4; `SessionEvent` is produced
  by Task 2 and consumed by the TUI and serializers; `ToolFilter` is produced by Task 5 and wired
  through `LoopDependencies`; `ContextSummary` and `DiagnosticReport` are produced by Task 6 and
  rendered by Task 4.
- Safety: all invocation options pass through existing policy and redaction boundaries; the plan
  never adds a permission bypass, shell command path, secret persistence, or network requirement.
- Delivery: implementation starts only after the worktree baseline, all task commits remain
  reviewable, and main's unrelated dirty files are not staged.
