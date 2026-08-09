# 613 Coding TUI And Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the main Web/HTTP product surface with a Claude Code-like local Textual TUI and publish a tested Linux x86_64 executable plus Python package artifacts.

**Architecture:** SQLite-authoritative interactive sessions group immutable auditable Runs. The existing loop gains a streaming provider boundary, ephemeral progress sink, and cooperative cancellation while retaining persisted final responses and state transitions. A Textual adapter drives application services; a pinned multi-stage Dockerfile builds and exports PyInstaller, wheel, sdist, and checksum artifacts for CI/CD.

**Tech Stack:** Python 3.12, `uv`, Pydantic, SQLite, LanceDB, HTTPX streaming, Textual 3.x, Typer, PyInstaller 6.x, Docker BuildKit, pytest, Textual Pilot, Ruff, mypy, GitHub Actions, GitLab CI.

## Global Constraints

- Begin only after the safe repository mutations plan is merged and freshly verified on main.
- Use a new isolated worktree created with `using-git-worktrees`; preserve unrelated main and Cube changes.
- Use TDD for each task and retain exact RED output before implementation.
- `613-coding` opens the TUI; `613-coding "task"` starts it with a prompt; management subcommands remain scriptable.
- TUI presentation code cannot make policy, approval, validation, tool, budget, or completion decisions.
- SQLite remains authoritative. Token deltas are ephemeral; final model responses and audit events are persisted.
- Esc cooperatively pauses the active Run. It must not silently mark the Run failed or cancel the interactive session.
- Remove the main FastAPI, Uvicorn, static WebUI, Render, SSH, reverse-proxy, health endpoint, and runtime-container surface.
- Do not remove or redesign the separate `tmp/cube` React/FastAPI application.
- First binary target is Linux x86_64 and must run without host Python.
- Docker is the canonical release builder and has no product runtime stage.
- Never put provider keys in arguments, files, databases, events, prompts, build layers, binaries, CI definitions, or worker containers.
- Keep the container worker sandbox and Supervisor/multi-agent product capabilities intact.
- Update `PLAN.md`, `AGENT_LOG.md`, `DELIVERY_STATUS.md`, README, and deployment/development guidance with actual evidence.

---

## File Map

- `src/coding613/domain/interactive.py`: interactive session and transcript value objects.
- `src/coding613/ports/progress.py`: immutable progress event and sink protocol.
- `src/coding613/application/progress.py`: null/recording sinks, cancellation token, and provider cancellation exception.
- `src/coding613/application/interactive.py`: session lifecycle, follow-up Run creation, transcript assembly, and resumable execution facade.
- `src/coding613/application/context.py`: bounded previous-session context injection.
- `src/coding613/application/loop.py`: progress publication and cooperative pause transition.
- `src/coding613/application/run_service.py`: pause request and Run lookup needed by interactive services.
- `src/coding613/ports/llm.py`: optional streaming-provider protocol while preserving non-streaming test providers.
- `src/coding613/adapters/llm/openai_compatible.py`: SSE accumulation for text and tool-call deltas.
- `src/coding613/adapters/llm/credentialed.py`: lazy keyring-backed streaming delegation.
- `src/coding613/adapters/llm/mock.py`: deterministic streaming test provider.
- `src/coding613/adapters/storage/schema.sql`, `sqlite.py`: session schema, backward-compatible migration, and queries.
- `src/coding613/tui/`: Textual app, controller, widgets, slash commands, renderers, and styles.
- `src/coding613/cli/entrypoint.py`, `main.py`, `tui.py`: root dispatch and management subcommands.
- `packaging/613-coding.spec`: PyInstaller collection and executable definition.
- `packaging/launcher.py`: absolute-import executable entrypoint for PyInstaller.
- `scripts/build_artifacts.sh`, `scripts/smoke_artifacts.sh`: reproducible build and artifact execution gates.
- `Dockerfile`: pinned BuildKit builder and scratch artifact-export target.
- `.github/workflows/ci.yml`, `.gitlab-ci.yml`: verified artifact publication.
- Removed: `src/coding613/api/`, `src/coding613/web/`, `tests/api/`, `tests/web/`, `render.yaml`, `docker/entrypoint.sh`, `scripts/smoke_container.sh`.

### Task 1: Interactive Session Domain And SQLite Migration

**Files:**
- Create: `src/coding613/domain/interactive.py`
- Modify: `src/coding613/domain/models.py`
- Modify: `src/coding613/domain/__init__.py`
- Modify: `src/coding613/ports/storage.py`
- Modify: `src/coding613/adapters/storage/schema.sql`
- Modify: `src/coding613/adapters/storage/sqlite.py`
- Create: `tests/domain/test_interactive.py`
- Modify: `tests/adapters/storage/test_sqlite.py`

**Interfaces:**
- Produces: `InteractiveSession(id: UUID, project_id: UUID, title: str | None, created_at: datetime, updated_at: datetime)`.
- Produces: nullable `Run.session_id: UUID | None` without changing existing serialized Runs.
- Produces store methods `create_interactive_session`, `get_interactive_session`, `list_interactive_sessions(project_id, limit=50)`, and `list_runs_for_session(session_id)`.
- Produces SQLite `PRAGMA user_version = 1` migration for existing `.613-coding/state.sqlite` files.

- [ ] **Step 1: Write RED domain and migration tests**

Test a session round trip and ordered run listing. Create a legacy database by executing the
current pre-change schema with `user_version=0`, insert a Project and Run, reopen it with
`SqliteEventStore`, and assert the old Run still loads with `session_id is None`.

```python
def test_session_round_trip_and_ordered_runs(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    project = Project(canonical_root=tmp_path)
    store.create_project(project)
    session = InteractiveSession(project_id=project.id, title="Repair tests")
    store.create_interactive_session(session)
    first = Run(project_id=project.id, session_id=session.id, task="first")
    second = Run(project_id=project.id, session_id=session.id, task="second")
    store.create_run(first)
    store.create_run(second)
    assert store.get_interactive_session(session.id) == session
    assert store.list_runs_for_session(session.id) == [first, second]
```

- [ ] **Step 2: Run RED tests**

```bash
uv run pytest tests/domain/test_interactive.py tests/adapters/storage/test_sqlite.py -q
```

Expected: collection or construction FAILS because the session type, `Run.session_id`, and store
methods do not exist.

- [ ] **Step 3: Add domain values and storage protocol**

Use the existing `DomainModel`, UUID defaults, and timezone-aware timestamp conventions. Enforce
nonblank titles when present and a maximum of 200 characters. Add `session_id` to `Run` with a
default of `None` so old model JSON remains valid.

- [ ] **Step 4: Add schema and idempotent migration**

Add `interactive_sessions` before `runs` in the current schema and add nullable `session_id` to
new `runs` tables. In `SqliteEventStore.__init__`, after executing base `CREATE IF NOT EXISTS`
statements, inspect `PRAGMA table_info(runs)`. For a legacy table missing the column, execute:

```sql
CREATE TABLE IF NOT EXISTS interactive_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE runs ADD COLUMN session_id TEXT REFERENCES interactive_sessions(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_runs_session_created ON runs(session_id, created_at);
PRAGMA user_version = 1;
```

Perform the migration in one transaction with foreign keys enabled. Do not rebuild or discard
existing run/event data.

- [ ] **Step 5: Implement store queries and pass tests**

Serialize timestamps and UUIDs using the same helpers as Projects and Runs. Sort sessions by
`updated_at DESC, id ASC` and session Runs by `created_at ASC, id ASC`. Update session
`updated_at` when a linked Run is created.

Run:

```bash
uv run pytest tests/domain/test_interactive.py tests/adapters/storage/test_sqlite.py -q
uv run ruff check src/coding613/domain src/coding613/ports/storage.py src/coding613/adapters/storage tests/domain/test_interactive.py tests/adapters/storage/test_sqlite.py
uv run mypy src/coding613/domain src/coding613/ports/storage.py src/coding613/adapters/storage
```

- [ ] **Step 6: Commit**

```bash
git add src/coding613/domain src/coding613/ports/storage.py src/coding613/adapters/storage/schema.sql src/coding613/adapters/storage/sqlite.py tests/domain/test_interactive.py tests/adapters/storage/test_sqlite.py
git commit -m "feat: persist interactive coding sessions"
```

### Task 2: Streaming Provider And Ephemeral Progress Contracts

**Files:**
- Create: `src/coding613/ports/progress.py`
- Create: `src/coding613/application/progress.py`
- Modify: `src/coding613/ports/llm.py`
- Modify: `src/coding613/adapters/llm/openai_compatible.py`
- Modify: `src/coding613/adapters/llm/credentialed.py`
- Modify: `src/coding613/adapters/llm/mock.py`
- Create: `tests/application/test_progress.py`
- Modify: `tests/adapters/llm/test_openai_compatible.py`
- Modify: `tests/adapters/llm/test_credentialed.py`
- Modify: `tests/adapters/llm/test_mock.py`

**Interfaces:**
- Produces: `ProgressKind` values `STATE`, `TEXT_DELTA`, `TOOL_STARTED`, `TOOL_FINISHED`, `VALIDATION_STARTED`, `VALIDATION_FINISHED`, and `ERROR`.
- Produces: `RunProgress(run_id: UUID, kind: ProgressKind, text: str = "", payload: dict[str, Any] = Field(default_factory=dict))`.
- Produces: `ProgressSink.publish(update: RunProgress) -> None` and `NullProgressSink`.
- Produces: thread-safe `CancellationToken.cancel()`, `is_cancelled()`, and `reset()`.
- Produces: runtime-checkable `StreamingLLMProvider.complete_stream(context, tools, on_text_delta, cancelled) -> LLMResponse`.
- Preserves: `LLMProvider.complete(context, tools) -> LLMResponse` for existing mocks and adapters.

- [ ] **Step 1: Write RED contract and SSE tests**

Build an HTTPX MockTransport response containing Chat Completions SSE chunks for text `hello`, one
function call named `read_file`, split JSON arguments across chunks, and `[DONE]`. Assert each
text delta reaches a recording callback and the final response equals a normal `LLMResponse` with
the assembled action. Add malformed JSON, premature EOF, HTTP failure, and cancellation tests.

- [ ] **Step 2: Run RED tests**

```bash
uv run pytest tests/application/test_progress.py tests/adapters/llm -q
```

Expected: FAIL because progress and streaming contracts are absent.

- [ ] **Step 3: Implement progress values and cancellation**

Use immutable Pydantic values for progress, a no-op sink, and `threading.Event` inside
`CancellationToken`. Add `ProviderCancelledError` as an application boundary exception. Never
persist `RunProgress` automatically.

- [ ] **Step 4: Implement optional stream dispatch without breaking providers**

Add a helper:

```python
def complete_with_progress(
    provider: LLMProvider,
    context: ModelContext,
    tools: Sequence[ToolDefinition],
    on_text_delta: Callable[[str], None],
    cancelled: Callable[[], bool],
) -> LLMResponse:
    if isinstance(provider, StreamingLLMProvider):
        return provider.complete_stream(context, tools, on_text_delta, cancelled)
    response = provider.complete(context, tools)
    if response.text:
        on_text_delta(response.text)
    return response
```

Existing two-argument fake providers must continue passing without edits.

- [ ] **Step 5: Implement OpenAI-compatible SSE accumulation**

Send the same message/tool payload as `complete` plus `stream: true`. Use
`httpx.Client.stream("POST", "/chat/completions", json=payload)`. Parse only `data:` records,
check cancellation between records, concatenate text by choice index, and accumulate tool calls by
their streamed `index`, preserving `id`, name, and argument fragments. Reuse the existing final
schema parser so streamed and non-streamed calls have identical validation and finish behavior.

- [ ] **Step 6: Delegate streaming through credentials and mocks**

The credentialed adapter reads the key lazily once per client exactly as `complete` does, then
calls the lower-level streaming adapter. Add deterministic `ScriptedStreamingLLM` that emits a
configured tuple of deltas before returning its scripted response.

- [ ] **Step 7: Run tests, static checks, and commit**

```bash
uv run pytest tests/application/test_progress.py tests/adapters/llm -q
uv run ruff check src/coding613/ports src/coding613/application/progress.py src/coding613/adapters/llm tests/application/test_progress.py tests/adapters/llm
uv run mypy src/coding613/ports src/coding613/application/progress.py src/coding613/adapters/llm
git add src/coding613/ports src/coding613/application/progress.py src/coding613/adapters/llm tests/application/test_progress.py tests/adapters/llm
git commit -m "feat: stream provider progress through application ports"
```

### Task 3: Agent Loop Progress And Cooperative Pause

**Files:**
- Modify: `src/coding613/application/loop.py`
- Modify: `src/coding613/application/run_service.py`
- Modify: `src/coding613/application/composition.py`
- Modify: `tests/application/test_loop.py`
- Create: `tests/application/test_run_service.py`
- Modify: `tests/application/test_composition.py`

**Interfaces:**
- Extends: `LoopDependencies` with `progress: ProgressSink` and `cancellation: CancellationToken`.
- Produces: `RunService.pause(run_id: UUID) -> RunSummary`.
- Produces state progress at every loop transition and tool/validation boundary.
- Converts `ProviderCancelledError` into persisted `RunState.PAUSED` with no terminal stop reason.

- [ ] **Step 1: Write RED loop tests**

Use `ScriptedStreamingLLM`, a recording sink, and a cancellation token. Assert ordered
`WAITING_MODEL`, text delta, tool start/result, validation start/result, and final state updates.
Add a provider that cancels after its first delta; assert the returned summary and persisted loop
session are `PAUSED`, not `FAILED` or `CANCELLED`, and no token-delta event was persisted.

- [ ] **Step 2: Run RED tests**

```bash
uv run pytest tests/application/test_loop.py tests/application/test_composition.py -q
```

Expected: FAIL because dependencies have no progress/cancellation and cancellation maps to provider
failure.

- [ ] **Step 3: Publish loop progress at owned boundaries**

Add a private `_publish(run_id: UUID, kind: ProgressKind, dependencies: LoopDependencies, *, text: str = "", payload: Mapping[str, Any] | None = None) -> None` helper that catches sink exceptions and
records no domain failure: a broken UI observer cannot change agent correctness. Publish before and
after provider calls, each tool dispatch, each objective validation, and every state transition.
Publish redacted summaries, never raw secrets or entire environment maps.

- [ ] **Step 4: Add cooperative provider pause**

Call `complete_with_progress` with a delta callback that publishes `TEXT_DELTA` and with the
dependency token. Catch only `ProviderCancelledError`, transition to `PAUSED`, snapshot the loop
session, persist the Run state through `RunService`, and return a nonterminal summary.

- [ ] **Step 5: Add RunService pause request and dependency lookup**

`pause(run_id)` sets the active dependency token. If no execution is active, transition a
nonterminal Run directly to `PAUSED` with compare-and-set persistence. A terminal Run returns its
terminal summary unchanged. `resume` resets the token before entering the loop.

- [ ] **Step 6: Run focused and regression suites**

```bash
uv run pytest tests/application/test_loop.py tests/application/test_composition.py tests/cli/test_runs.py -q
uv run ruff check src/coding613/application tests/application
uv run mypy src/coding613/application
```

- [ ] **Step 7: Commit**

```bash
git add src/coding613/application tests/application tests/cli/test_runs.py
git commit -m "feat: pause runs with streamed progress"
```

### Task 4: Interactive Session Application Service

**Files:**
- Create: `src/coding613/application/interactive.py`
- Modify: `src/coding613/application/context.py`
- Modify: `src/coding613/application/composition.py`
- Create: `tests/application/test_interactive.py`
- Modify: `tests/application/test_context.py`
- Modify: `tests/application/test_composition.py`

**Interfaces:**
- Produces: `InteractiveSessionService.create(title: str | None = None) -> InteractiveSession`.
- Produces: `submit(session_id: UUID, message: str, permission_mode: PermissionMode | None = None) -> Run`.
- Produces: `execute(run_id: UUID, progress: ProgressSink, cancellation: CancellationToken) -> RunSummary`.
- Produces: `resume_session(session_id: UUID) -> InteractiveSnapshot`.
- Produces: `InteractiveSnapshot(session, runs, active_run, transcript)` and `TranscriptEntry(role, text, run_id)`.
- Produces: `SessionContextBuilder` that injects at most 12 prior transcript entries and 12,000 characters.

- [ ] **Step 1: Write RED session workflow tests**

Create a session, submit two messages, execute each with scripted providers, restart composition,
and assert ordered transcript restoration. Assert each message creates a distinct Run linked to
the same session, completed Runs stay terminal, and a paused latest Run is returned as
`active_run`.

- [ ] **Step 2: Run RED tests**

```bash
uv run pytest tests/application/test_interactive.py tests/application/test_context.py tests/application/test_composition.py -q
```

Expected: FAIL because no interactive service or context builder exists.

- [ ] **Step 3: Implement session lifecycle and transcript values**

Reject blank messages and messages over 100,000 characters. Derive transcript user entries from
`Run.task`; derive assistant entries only from persisted final model-response events, never from
ephemeral deltas. Return runs in store order and select the newest nonterminal Run as active.

- [ ] **Step 4: Implement bounded prior-session context**

Wrap the existing `ContextAssembler` for linked Runs. Insert prior transcript messages after the
system instruction and memory but before the current task. Exclude the current Run, redact stored
text again before context construction, cap entries/characters deterministically, and summarize
older omitted entries with a count only.

- [ ] **Step 5: Wire composition**

Expose `LocalServices.interactive`. Build per-execution loop dependencies with the TUI-provided
progress sink and cancellation token while preserving the same ToolRegistry, PolicyEngine,
ApprovalService, SQLite store, validator, and configured provider.

- [ ] **Step 6: Run tests and commit**

```bash
uv run pytest tests/application/test_interactive.py tests/application/test_context.py tests/application/test_composition.py -q
uv run ruff check src/coding613/application tests/application
uv run mypy src/coding613/application
git add src/coding613/application tests/application
git commit -m "feat: coordinate persisted interactive sessions"
```

### Task 5: Root Command Dispatch And Textual Shell

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/coding613/cli/tui.py`
- Modify: `src/coding613/cli/entrypoint.py`
- Modify: `src/coding613/cli/main.py`
- Create: `src/coding613/tui/__init__.py`
- Create: `src/coding613/tui/app.py`
- Create: `src/coding613/tui/widgets.py`
- Create: `src/coding613/tui/styles.tcss`
- Create: `tests/cli/test_entrypoint.py`
- Create: `tests/tui/test_app.py`

**Interfaces:**
- Produces: `TuiLaunchRequest(repo: Path, initial_task: str | None, resume: str | None)`.
- Produces: `parse_tui_args(argv: Sequence[str]) -> TuiLaunchRequest`.
- Produces: `dispatch(argv: Sequence[str]) -> int` and `run_management(argv: Sequence[str]) -> int`.
- Produces: `launch_tui(request: TuiLaunchRequest, services_factory=build_services) -> None`.
- Produces: `CodingApp(App[None])` with `ConversationLog`, `TaskComposer`, and `StatusFooter`.
- Preserves management commands: `credentials`, `config`, `run`, `runs`, and `demo`.

- [ ] **Step 1: Add dependencies and RED entrypoint tests**

Add `"textual>=3.7,<4"` to runtime dependencies and `"pytest-asyncio>=0.25,<1"` to dev dependencies,
then run `uv lock`. Test dispatch without spawning a real terminal:

```python
@pytest.mark.parametrize(
    ("argv", "expected_task"),
    [([], None), (["repair", "tests"], "repair tests"), (["--", "runs"], "runs")],
)
def test_root_invocations_launch_tui(monkeypatch, argv, expected_task) -> None:
    launched: list[TuiLaunchRequest] = []
    monkeypatch.setattr(entrypoint, "launch_tui", launched.append)
    assert entrypoint.dispatch(argv) == 0
    assert launched[0].initial_task == expected_task

@pytest.mark.parametrize("command", ["credentials", "config", "run", "runs", "demo"])
def test_reserved_management_commands_use_typer(monkeypatch, command) -> None:
    delegated: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        entrypoint,
        "run_management",
        lambda argv: delegated.append(tuple(argv)) or 0,
    )
    assert entrypoint.dispatch([command, "--help"]) == 0
    assert delegated == [(command, "--help")]
```

Also assert `--repo`, `--resume latest`, unknown options, nonexistent repositories, and
`613-coding --help` behavior.

- [ ] **Step 2: Run RED tests**

```bash
uv run pytest tests/cli/test_entrypoint.py tests/tui/test_app.py -q
```

Expected: collection FAILS because the TUI modules do not exist.

- [ ] **Step 3: Implement deterministic root dispatch**

In the installed entrypoint, inspect argv before invoking Typer. If the first non-option token is
a reserved management command, delegate unchanged to the existing Typer app. `--help` shows root
help. Otherwise parse TUI flags and join remaining task words. Strip a leading `--` so a task may
begin with a reserved word. Never interpolate arguments into a shell command.

- [ ] **Step 4: Build the stable Textual shell**

Use one full-height layout: scrollable log, fixed active-operation row, 3-8 line composer, and
one-line footer. Avoid dashboard cards and nested panels. Bind `ctrl+j` to newline, `enter` to
submit, `escape` to pause, `ctrl+c` to pause/exit confirmation, and `ctrl+q` to explicit exit.
Provide textual screen-reader labels and ensure the composer/footer fit an 80x24 terminal.

- [ ] **Step 5: Pass Pilot shell and dispatch tests**

Use `async with app.run_test(size=(80, 24)) as pilot` to assert initial focus, task insertion,
multiline editing, stable widget dimensions, and narrow `60x20` rendering without overlap.

Run:

```bash
uv run pytest tests/cli/test_entrypoint.py tests/tui/test_app.py -q
uv run ruff check src/coding613/cli src/coding613/tui tests/cli tests/tui
uv run mypy src/coding613/cli src/coding613/tui
uv lock --check
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/coding613/cli src/coding613/tui tests/cli/test_entrypoint.py tests/tui/test_app.py
git commit -m "feat: open interactive tui from root command"
```

### Task 6: Complete Claude Code-Like TUI Interaction

**Files:**
- Create: `src/coding613/tui/controller.py`
- Create: `src/coding613/tui/commands.py`
- Create: `src/coding613/tui/renderers.py`
- Modify: `src/coding613/tui/app.py`
- Modify: `src/coding613/tui/widgets.py`
- Modify: `src/coding613/tui/styles.tcss`
- Create: `tests/tui/test_controller.py`
- Create: `tests/tui/test_commands.py`
- Modify: `tests/tui/test_app.py`

**Interfaces:**
- Produces: `TuiController.submit`, `pause`, `approve`, `reject`, `resume`, `list_sessions`, and `snapshot` async-facing methods.
- Produces: `SlashCommand.parse(text) -> ParsedCommand` for `/help`, `/model`, `/permissions`, `/resume`, `/runs`, `/clear`, and `/quit`.
- Produces renderers for assistant Markdown, tool call/result, unified diff, validation result, approval request, error, and budget state.

- [x] **Step 1: Write RED controller and command tests**

Use fake interactive services and a thread-safe progress queue. Assert deltas append to one active
assistant message, final text replaces/finishes it without duplication, tool status updates in
place, and persisted snapshots rebuild the same transcript after restart. Parameterize every slash
command and invalid arguments.

- [x] **Step 2: Add RED approval, diff, interruption, and long-output Pilot tests**

Drive a strict-mode `apply_patch` approval with a 200-line diff. Assert the diff is scrollable,
approve/reject are explicit keyboard actions, no text overlaps at 80x24 and 60x20, Esc calls pause
once, and reopening `--resume latest` restores the paused run. Add provider error, expired approval,
and unavailable keyring display tests with secret-shaped input that must not appear.

- [x] **Step 3: Run RED tests**

```bash
uv run pytest tests/tui -q
```

Expected: FAIL because controller, slash commands, and renderers are missing.

- [x] **Step 4: Implement background execution and progress draining**

Run blocking application execution with `asyncio.to_thread`. Send progress through
`queue.SimpleQueue`; use a Textual timer or worker message to drain updates on the UI thread.
Disable task submission only while an active Run is executing or awaiting an explicit modal
decision. Never mutate Textual widgets from the provider thread.

- [x] **Step 5: Implement renderers and approval flow**

Render text with Textual Markdown, tool arguments as bounded syntax-highlighted JSON, patch text as
unified diff, and validation as command/exit/duration plus capped stdout/stderr. The approval view
shows the exact action fingerprint, policy reason, affected paths, and diff before enabling approve
or reject. After resolution, call resume on the same Run.

- [x] **Step 6: Implement slash commands and session restoration**

`/model` shows configured non-secret provider/model/base URL metadata; `/permissions` shows or
changes the next Run's strict/balanced/autonomous mode; `/runs` lists recent session Runs;
`/resume [latest|UUID]` restores; `/clear` creates a new visual session without deleting persisted
history; `/quit` pauses an active Run before closing. `/help` lists commands and no hidden
implementation tutorial text remains on the normal screen.

- [x] **Step 7: Run TUI and application regressions**

```bash
uv run pytest tests/tui tests/cli tests/application/test_interactive.py tests/application/test_loop.py -q
uv run ruff check src/coding613/tui src/coding613/cli tests/tui tests/cli
uv run mypy src/coding613/tui src/coding613/cli
```

- [x] **Step 8: Commit**

```bash
git add src/coding613/tui tests/tui
git commit -m "feat: add streamed coding conversation tui"
```

Task 6 evidence: `.superpowers/sdd/2026-08-09-613-coding-tui-distribution/task-6-report.md`;
commit `048bdbc`; focused regression suite passed 95 tests with Ruff, mypy, lock, and diff checks.

### Task 7: Remove Main Web And HTTP Surfaces

**Files:**
- Delete: `src/coding613/api/`
- Delete: `src/coding613/web/`
- Delete: `tests/api/`
- Delete: `tests/web/`
- Delete: `render.yaml`
- Delete: `docker/entrypoint.sh`
- Delete: `scripts/smoke_container.sh`
- Modify: `src/coding613/cli/main.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `tests/test_distribution.py`
- Modify: `tests/test_docs.py`
- Delete: `tests/test_container_smoke_script.py`

**Interfaces:**
- Removes: `613-coding web`, `coding613.api`, `coding613.web`, FastAPI, Uvicorn, `/healthz`, and Render.
- Preserves: TUI root command, all management CLI subcommands, RunService, SQLite/LanceDB, worker Docker runtime, and multi-agent orchestration.

- [ ] **Step 1: Replace old positive-Web tests with RED absence contracts**

Assert `pyproject.toml` has no FastAPI/Uvicorn dependency, root help has no `web`, removed import
specs are `None`, `render.yaml` and runtime entrypoint are absent, and current README/deployment
guidance contains no WebUI/Render/SSH/proxy instructions. Keep historical evidence files out of the
current-guidance scan.

- [ ] **Step 2: Run RED removal tests**

```bash
uv run pytest tests/test_distribution.py tests/test_docs.py -q
```

Expected: FAIL on the still-present command, dependencies, files, and guidance.

- [ ] **Step 3: Delete HTTP code and dependencies**

Remove only the listed main-project files. Remove FastAPI/Uvicorn imports and dependencies, run
`uv lock`, and verify no application/domain code imported the deleted adapter. Do not touch
`tmp/cube/apps/api` or its FastAPI dependency.

- [ ] **Step 4: Pass removal and regression tests**

```bash
uv run pytest tests/test_distribution.py tests/test_docs.py tests/cli tests/application -q
uv run ruff check .
uv run mypy src
uv lock --check
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add -A src/coding613/api src/coding613/web tests/api tests/web render.yaml docker/entrypoint.sh scripts/smoke_container.sh tests/test_container_smoke_script.py pyproject.toml uv.lock src/coding613/cli/main.py tests/test_distribution.py tests/test_docs.py
git commit -m "refactor: replace web console with local tui"
```

### Task 8: PyInstaller And Docker Artifact Builder

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `packaging/launcher.py`
- Create: `packaging/613-coding.spec`
- Create: `scripts/build_artifacts.sh`
- Create: `scripts/smoke_artifacts.sh`
- Replace: `Dockerfile`
- Modify: `.dockerignore`
- Modify: `tests/test_distribution.py`
- Create: `tests/test_artifact_scripts.py`

**Interfaces:**
- Produces: `dist/613-coding-linux-x86_64`.
- Produces: `dist/613_coding-<version>-py3-none-any.whl`.
- Produces: `dist/613_coding-<version>.tar.gz`.
- Produces: `dist/SHA256SUMS` with exactly the other three basenames.
- Produces Docker target `artifacts` for `--output type=local,dest=dist`.

- [ ] **Step 1: Add build dependency and RED artifact contract tests**

Add `"pyinstaller>=6.16,<7"` to the dev dependency group and lock it. Replace runtime-container
assertions with checks for a pinned first `FROM`, a named builder, `FROM scratch AS artifacts`, no
`ENTRYPOINT`, `CMD`, `EXPOSE`, or `HEALTHCHECK`, and copies of exactly four artifact classes.
Test both scripts with fake `uv`, `pyinstaller`, and `sha256sum` executables to verify argv and
failure propagation.

- [ ] **Step 2: Run RED distribution tests**

```bash
uv run pytest tests/test_distribution.py tests/test_artifact_scripts.py -q
```

Expected: FAIL because the runtime Dockerfile and old smoke contract are still present.

- [ ] **Step 3: Add deterministic PyInstaller spec**

Create `packaging/launcher.py` with an absolute import and direct `main()` call. Set executable
name `613-coding-linux-x86_64`, entry script `packaging/launcher.py`, `console=True`, and no UPX.
Use PyInstaller collection helpers
for `coding613`, `textual`, `lancedb`, `pyarrow`, and `keyring.backends`; include
`src/coding613/adapters/storage/schema.sql` and `src/coding613/tui/styles.tcss`. Fail the build if a
required hidden import or data file cannot be collected.

- [ ] **Step 4: Add build and smoke scripts**

`build_artifacts.sh` uses `set -eu`, empties only its explicit build-output directory, runs
`uv build --out-dir`, runs PyInstaller with isolated work/spec paths, copies the executable, then
generates sorted checksums. `smoke_artifacts.sh` verifies checksums, executable bit, binary
`--help`, an isolated `config check`, the deterministic core demo, wheel installation into an
explicit temporary uv environment, and matching `613-coding --help` output.

- [ ] **Step 5: Replace Dockerfile with builder-only stages**

Retain the current pinned base exactly:

```dockerfile
FROM python:3.12.8-slim-bookworm@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0 AS builder
```

Install `uv==0.8.14`, copy lock/metadata and sources, run `uv sync --frozen`, run the build script
into `/out`, and end with:

```dockerfile
FROM scratch AS artifacts
COPY --from=builder /out/ /
```

No stage starts or deploys 613 Coding.

- [ ] **Step 6: Pass unit contracts and build real artifacts**

```bash
uv run pytest tests/test_distribution.py tests/test_artifact_scripts.py -q
docker build --pull=false --target artifacts --output type=local,dest=dist .
scripts/smoke_artifacts.sh dist
docker run --rm -v "$PWD/dist:/artifacts:ro" debian:bookworm-slim /artifacts/613-coding-linux-x86_64 --help
```

The final command proves execution in a container without Python installed. Record executable
size, `file` output, and checksum verification.

- [ ] **Step 7: Run static checks and commit**

```bash
uv run ruff check .
uv run mypy src
uv lock --check
git diff --check
git add pyproject.toml uv.lock packaging scripts/build_artifacts.sh scripts/smoke_artifacts.sh Dockerfile .dockerignore tests/test_distribution.py tests/test_artifact_scripts.py
git commit -m "build: export runnable tui and python artifacts"
```

### Task 9: CI/CD, Documentation, Review, And Final Evidence

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.gitlab-ci.yml`
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Modify: `docs/development.md`
- Modify: `tests/test_distribution.py`
- Modify: `tests/test_docs.py`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `DELIVERY_STATUS.md`

**Interfaces:**
- Produces CI artifacts `613-coding-linux-x86_64`, wheel, sdist, and `SHA256SUMS` on every successful pipeline.
- Produces tag releases containing the exact previously verified files.
- Produces current local-only TUI/CLI operation documentation with no remote deployment steps.

- [ ] **Step 1: Write RED CI and documentation contracts**

Assert both CI files invoke `docker build --target artifacts --output`, run
`scripts/smoke_artifacts.sh`, upload `dist/`, and retain GitLab job `unit-test`. Assert GitHub tag
configuration attaches the four artifacts. Assert README documents root TUI, initial prompt,
resume, management subcommands, `uv tool install`, binary checksum, host Docker sandbox
prerequisite, keyring, and `.env` risk while excluding server/port/proxy/Render/SSH instructions.

- [ ] **Step 2: Run RED tests**

```bash
uv run pytest tests/test_distribution.py tests/test_docs.py -q
```

Expected: FAIL against existing container-build/smoke and deployment guidance.

- [ ] **Step 3: Update GitHub and GitLab pipelines**

Keep offline test, quality, and demo gates. Replace runtime image jobs with artifact-builder jobs.
Upload `dist/*` only after checksum and binary/wheel smoke pass. Use `actions/upload-artifact@v4` on
push/PR and an explicit tag-only release step using repository `contents: write`. GitLab exposes
the same `dist/` with a finite expiry and no deployment environment.

- [ ] **Step 4: Rewrite current operation and development guidance**

Document exact local commands, keyring metadata configuration, Secret Service behavior on
headless Linux, interactive controls, session recovery, artifact verification, supported Linux
boundary, PyInstaller glibc boundary, Docker worker prerequisite, builder command, CI artifact
location, and sandbox limitations. Preserve old deployment facts only in chronological evidence
logs, not current instructions.

- [ ] **Step 5: Run complete local verification**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
uv lock --check
git diff --check
docker build --pull=false --target artifacts --output type=local,dest=dist .
scripts/smoke_artifacts.sh dist
```

Also run a pseudo-terminal TUI smoke with a deterministic provider, pause it, restart with
`--resume latest`, and confirm the transcript and Run ID persist. Record commands and terminal
results without provider secrets.

- [ ] **Step 6: Request spec and code-quality reviews**

Review the full branch against
`docs/superpowers/specs/2026-08-09-613-coding-tui-distribution-design.md`. Require explicit findings
on token persistence, cancellation races, approval fingerprints, session migrations, UI-thread
access, root dispatch, removed Web imports, PyInstaller completeness, and CI artifact execution.
Repair every Critical or Important finding with RED/GREEN evidence.

- [ ] **Step 7: Update records and commit**

Record every task commit, fresh test counts, artifact names/checksums, binary runtime evidence,
reviewers, repairs, and the deliberate removal of remote deployment from current scope.

```bash
git add .github/workflows/ci.yml .gitlab-ci.yml README.md docs/deployment.md docs/development.md tests/test_distribution.py tests/test_docs.py PLAN.md AGENT_LOG.md DELIVERY_STATUS.md
git commit -m "docs: publish local tui artifact workflow"
```

- [ ] **Step 8: Publish only after exact-main verification**

Integrate the reviewed branch without overwriting user files. Run the complete gates and artifact
build on exact main. Push only after local success, wait for GitHub Actions, and record the exact
commit/run/job/artifact evidence. GitLab remains configured evidence unless a runner is available;
do not invent a remote GitLab pass. Do not deploy to `edward@int21`, Render, or any other server.
