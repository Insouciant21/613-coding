# SPEC_PROCESS.md

## Purpose

This file records the human decisions and evidence that produced the approved 613 Coding design. It is a process artifact, not a substitute for `SPEC.md`.

## Brainstorming Iterations

### Iteration 1: Product direction

- Question: which user and high-frequency task should the Harness serve?
- Decision: local development assistant.
- Question: what is the input/output of one run?
- Decision: task-driven closed loop from natural-language task and repository path to modified, validated code or a clear pause.
- Human reasoning: this gives the Harness a concrete coding domain while leaving room for objective tests and safety boundaries.

### Iteration 2: Main mechanism and stack

- Question: which dimension should be the main contribution?
- Decision: feedback loop with deterministic validation, failure classification, bounded stopping, and self-correction.
- Question: language and provider boundary?
- Decision: Python managed by `uv`, OpenAI-compatible LLM/embedding adapters, offline mock providers for tests.
- Question: repository scope and interface?
- Decision: generic local Git repositories with declared argv validation commands; CLI first with a shared FastAPI WebUI.
- Human reasoning: a generic repository boundary demonstrates a real Harness without requiring language-specific analyzers.

### Iteration 3: Governance, memory, and delivery

- Question: governance mode?
- Decision: `strict`, `balanced`, and `autonomous`, with hard rules that no mode can bypass.
- Question: memory?
- Decision: SQLite authoritative state plus LanceDB vector retrieval, redacted before embedding, with SQLite fallback.
- Question: distribution?
- Decision: Python package via `uv tool install` plus Docker demonstration image; public WebUI uses an isolated example repository.
- Human reasoning: local persistence and an embedded vector index make memory testable without a remote service.

### Iteration 4: Claude Code reference and agent loop

- User direction: reference Claude Code.
- Revision: replace the simple single-action description with a tool-use turn. A model response may include multiple tool calls, but every call is schema-validated, policy-checked, recorded, and ordered where writes or commands overlap.
- Confirmed loop: context assembly → LLM tool calls → validation and policy → tool results → objective feedback → state transition → next turn or terminal state.
- Human reasoning: imitate observable tool/permission/context behavior while keeping the loop and mechanisms owned by this repository.

### Iteration 5: Sandbox and multi-agent expansion

- User direction: rename product to 613 Coding and add complete container execution and multi-agent orchestration.
- Scope decision: keep feedback loop as main contribution; implement Sandbox Runtime and Supervisor/worker orchestration as complete supporting subsystems.
- Decisions: one temporary container and task workspace per worker; Supervisor plus planner/coder/tester/reviewer/security roles; workers return versioned artifacts; Supervisor integrates and validates.
- Human reasoning: separate ports and plans protect the main feedback contribution from being diluted by two additional subsystems.

### Iteration 6: Budget policy

- Question: why was a five-turn limit proposed?
- Revision: it is not a product rule. Interactive runs do not use a low fixed five-turn cap; configurable turn, total-call, wall-time, and cost budgets protect unattended runs. Five turns remain only an explicit mock-demo budget.

### Iteration 7: Automatic delivery evidence

- User direction: automatically record delivery requirements in project record files.
- Decision: maintain `AGENT_LOG.md`, `PLAN.md`, `SPEC_PROCESS.md`, and a new `DELIVERY_STATUS.md` summary. Record successes, failures, pauses, approvals, user edits, deviations, commits, commands, verification output, and CI/CD evidence. Never mark an unrun command as passing.

### Iteration 8: Local TUI product direction

- User direction: remove the 613 Coding WebUI, replace it with a Claude Code-like interactive
  TUI, stop treating remote deployment as a deliverable, and use Docker as the reproducible
  release builder.
- Entry-point decision: `613-coding` opens the TUI in the current repository;
  `613-coding "task"` starts with an initial task; existing operational subcommands remain
  scriptable.
- Interaction decision: the first TUI release includes real streaming, tool state, diffs,
  validation, approval, multiline input, interruption, follow-up turns, and session recovery.
- Framework decision: use Textual as a presentation adapter over application services, with
  SQLite-authoritative `InteractiveSession` state and an ephemeral progress sink.
- Removed boundary: the main project will have no FastAPI, browser assets, HTTP server, Render
  manifest, reverse proxy contract, remote host, or public URL requirement.

### Iteration 9: Binary and build distribution

- Binary choice: PyInstaller single-file Linux x86_64 executable, requiring no host Python, while
  continuing to publish wheel and sdist.
- Docker choice: a pinned multi-stage Dockerfile is the sole canonical artifact builder and has no
  product runtime stage.
- CI/CD choice: GitHub and GitLab execute and upload the binary, wheel, sdist, and checksums. Tag
  builds attach the verified files to releases.
- Runtime boundary: Docker Engine remains required only when users execute isolated workers.

### Iteration 10: Safe mutation and Cube recovery

- Security direction: add a versioned schema-validated unified-diff `apply_patch` and redesign
  `delete_file` with descriptor-relative `O_NOFOLLOW` traversal and unlinking.
- Scope split: (1) safe repository mutations, (2) TUI/Web removal/distribution, then (3) Cube
  recovery and completion through 613 Coding.
- Cube boundary: the Cube Solver keeps its React/Three.js/FastAPI local browser architecture;
  WebUI removal applies only to 613 Coding.
- Recovery decision: preserve Task 2 commit and all worker-authored RED Task 3 artifacts. Resume
  with small patch operations after the harness mutation and TUI work is verified.
- Credential evidence: `ai2: configured (source=keyring)` was verified without reading or
  displaying key material.

Iterations 8 through 10 supersede only the WebUI, remote-deployment, release-container, terminal
interaction, and repository-mutation decisions recorded in Iterations 2 and 3. The owned feedback
loop, governance, SQLite/LanceDB authority, worker sandbox, and multi-agent decisions remain in
force.

## Approaches Considered

1. Core state machine with CLI/WebUI adapters: selected because it gives clear injectable boundaries and a deep feedback mechanism.
2. Full event-sourced workflow engine: adopted only for structured events, not full replay infrastructure, to control scope.
3. Plugin-first platform: rejected as the primary structure because it would dilute the feedback-loop contribution.

### 2026-08-09 Redesign Approaches

1. Three sequential subprojects: selected because safe mutation is a prerequisite for reliable
   TUI-driven Cube work and each stage has an independent security or product acceptance boundary.
2. One combined harness rewrite followed by Cube: rejected because mutation security, streaming
   state, presentation removal, and binary packaging would be too large for one reviewable unit.
3. TUI before mutation hardening: rejected because it would expose a polished interface while the
   agent still lacked a reliable focused-edit primitive.

## Cold-Start Validation

### Trial

- Date: 2026-08-08.
- Agent: fresh different-model agent, with no conversation history.
- Supplied material: only `SPEC.md`, `PLAN.md`, and the detailed plan files linked from `PLAN.md` in a temporary `/tmp` archive of commit `66f3bce`.
- Requested tasks: `CORE-01` and `CORE-02`.
- Isolation note: `git worktree add` was blocked because the environment could not create Git ref lock files. The trial therefore used the temporary archive and did not modify the main workspace.
- Report: `/tmp/613-cold-start.T1D2Hh/cold-start-report.md`.

### Findings

1. The plan used `uv run pytest` before defining how a fresh, network-restricted environment obtains pytest.
2. CORE-02 required Pydantic, but the bootstrap path did not say whether Pydantic is preinstalled, cached, vendored, or fetched.
3. `uv` could not build the temporary project without an explicitly documented build-backend/bootstrap decision.

### Revision After Trial

- Before: the specification said tests run offline and CORE-01 immediately ran `uv run pytest`.
- After: the specification distinguishes first-time dependency provisioning from offline test execution. `uv sync --all-extras --frozen` is the online bootstrap; `uv sync --all-extras --frozen --offline` requires a populated uv cache or wheelhouse and fails clearly otherwise.
- Before: the first test assumed pytest was installed.
- After: CORE-01 uses standard-library `unittest` with `PYTHONPATH=src` and introduces `scripts/bootstrap_dev.py` plus `docs/development.md`. CORE-02 now has a hard prerequisite that Pydantic and pytest be provisioned.
- Result: the plan now tells a fresh agent exactly which check to run, how to distinguish an environment block from a code failure, and when to pause rather than guess.

## Reflection Notes

The strongest brainstorming outcome was forcing explicit boundaries around objective feedback, dangerous actions, memory authority, and the distinction between the development host and the delivered Harness. The main unresolved execution risk is scope: three substantial runtime areas must be delivered with the feedback loop still visibly deeper than the supporting systems.

### Iteration 12: Parity execution approval

- Question: which workflow should execute the approved Claude-Code-like TUI/CLI parity plan?
- Decision: the user approved Inline Execution after the detailed plan review; implementation is isolated in `.worktrees/claude-code-parity` and proceeds task-by-task with TDD.
- Uncertainty exposed: permissions and context controls must be shared application services rather than TUI-only state. Task 5 therefore added persisted project rules and run-scoped filters behind the existing policy boundary before continuing to context work.
- Before/after: before, the root registry and delivery status marked parity implementation pending; after approval and Task 5, Tasks 1-5 are committed and offline verified while Tasks 6-7 remain explicitly open.

### Iteration 11: Official OpenAI SDK migration

- Question: should the LLM adapter continue maintaining direct HTTP/SSE protocol code or use the
  official OpenAI Python SDK?
- User decision: migrate chat and tool calls to the official SDK using Chat Completions.
- Selected boundary: retain the project-owned `LLMProvider`, AgentLoop, schemas, governance,
  deterministic feedback, cancellation, absolute deadline, Keyring lifecycle, and offline fakes;
  replace only provider request/response transport and parsing with SDK calls and typed values.
- Compatibility decision: keep custom `base_url` and the `openai-compatible` configuration value;
  do not migrate the independent embedding adapter in this change.
- Uncertainty exposed: Responses API would widen the migration and reduce compatible-endpoint
  coverage, while using only the SDK transport would preserve the custom parsing burden. Both were
  rejected in favor of `chat.completions.create`.
- Meaningful before/after: before, production code posts directly to `/chat/completions` and parses
  SSE records; after, production chat calls and streams go through an injected official SDK client
  and are converted back into project-owned domain values.
- Approved design: `docs/superpowers/specs/2026-08-10-openai-sdk-llm-design.md`.

### Iteration 12: Claude-Code-like TUI and CLI parity

- Question: how should the request for Claude Code-like TUI and CLI behavior be made testable
  without coupling the product to Anthropic's private implementation?
- Decision: define parity as equivalent local coding-agent workflow and stable user-facing
  contracts: one shared conversation service, multiple follow-up prompts, session continuation and
  resume, approvals and permission modes, context diagnostics/compaction, TUI progress, and CLI
  text/JSON/stream-JSON input/output.
- Scope decision: keep the existing owned `AgentLoop`, deterministic feedback classifiers,
  governance, SQLite authority, sandbox, and tool registry. Do not add an unsafe permission bypass,
  WebUI, account/telemetry behavior, or MCP transport in this implementation slice; retain an
  injectable tool boundary for a later MCP adapter.
- Meaningful before/after: before, the root command primarily launches a basic TUI and management
  commands expose lower-level run operations; after the approved design, root prompt/print modes,
  session controls, event serializers, TUI commands, diagnostics, and permission filters share one
  application contract.
- Human decision: user approved the proposed scope on 2026-08-10.
- Approved design: `docs/superpowers/specs/2026-08-10-613-coding-claude-code-parity-design.md`.
- Plan revision: the detailed plan adds a versioned `SessionEnvelope` for multiple stream-JSON
  input messages so the output contract remains deterministic without dropping ordered follow-up
  runs. Plan: `docs/superpowers/plans/2026-08-10-613-coding-claude-code-parity.md`.

### Iteration 13: Responses API support

- Question: should the official SDK integration expose only Chat Completions, or also support the
  Responses API used by current reasoning and coding-agent workflows?
- User decision: add Responses API support while retaining Chat Completions compatibility; do not
  use the SDK's hosted agent runner.
- Selected boundary: add a separate `ResponsesLLM`/credentialed adapter, selected by `[llm].api`,
  with project-owned request mapping, tool dispatch, validation, feedback, and stop logic.
- Meaningful before/after: before, the SDK migration only called `chat.completions.create`; after,
  `responses.create` supports synchronous output items and streamed text/function-call events,
  normalized usage metadata, and a `store=false` state boundary. Existing configurations default
  unchanged to `chat_completions`.
- Uncertainty exposed: Responses uses flat function schemas and `output` items rather than nested
  Chat messages; fake-client tests now lock both mappings and malformed-call behavior.
- Evidence: `docs/superpowers/specs/2026-08-11-responses-api-llm-design.md`,
  `docs/superpowers/plans/2026-08-11-responses-api-llm.md`, and current `PLAN.md`/`AGENT_LOG.md`.

### Iteration 14: User-scoped provider and budget configuration

- Question: which settings belong in a repository `harness.toml` when a user wants to switch
  between several OpenAI-compatible APIs and retain one budget policy across repositories?
- Decision: keep `harness.toml` project-policy-only. Store named provider profiles, active selection,
  context-window/output/reasoning options, and budgets in a user-wide config file; store API keys
  only in the OS keyring. Expose profile lifecycle through `613-coding providers` and switching
  through TUI `/provider use NAME`.
- Uncertainty exposed: a global active provider can affect offline tests. The test suite overrides
  `CODING613_CONFIG_FILE` per test, while production composition uses the real default path. The
  existing `tmp/cube` metadata was migrated without copying secrets.
- Before/after: before, project config mixed policy, provider, and budget data and `/config` edited
  provider fields; after, project files reject those sections, `/config` edits only policy/budgets
  through the correct owner, provider profiles are switchable, and API-key output remains redacted.

### Iteration 15: Provider model catalogs, Anthropic, and interactive slash menus

- Question: how can one user provider expose several models and reasoning profiles while keeping
  provider credentials/endpoint metadata shared, and how should common slash commands avoid a
  brittle free-form key/value workflow?
- Decision: store model aliases as nested user-config tables under each provider, resolve the active
  alias into the existing `LLMConfig` boundary, and expose model lifecycle through `providers
  models`. Add a low-level official Anthropic Messages adapter without adopting an SDK agent runner.
  Use Textual `OptionList` menus for `/config`, `/provider`, and `/model`, with explicit keyboard
  routing because the app's priority Enter/up/down bindings otherwise intercept menu navigation.
- Uncertainty exposed: Textual's `OptionList` constructor is variadic rather than list-based, and
  Anthropic's extended-thinking budget must remain below `max_tokens`; both constraints are now
  encoded in implementation and offline regressions.
- Before/after: before, a provider had one model and `/config` required manual arguments; after,
  aliases can be switched persistently with per-model reasoning/resource overrides, Anthropic is a
  supported SDK transport, and the TUI presents discoverable selectable menus.

### Iteration 16: Deterministic `apply_patch` recovery barrier

- Question: why can a failed strict patch still consume turns with alternate stale patches, and
  what harness boundary should make recovery deterministic?
- Decision: retain exact hunk matching, but persist the normalized conflict paths in
  `LoopSession.patch_repair_paths`. Until every path has a successful `read_file`, the loop
  rejects writes, finish/validation actions, and mixed read/write responses without dispatching
  them. Successful reads clear only their matching paths; the existing repeated-conflict
  classifier remains the bounded no-progress guard.
- Before/after: before, the prompt asked the model to reread files and the loop inferred repeated
  `apply_patch` conflicts from old events; after, the required read state is explicit, durable
  across resume/restart, and enforced for every write tool.
- Uncertainty exposed: the recovery read must be observed in a separate model response, so a
  response that mixes `read_file` and a write is rejected rather than allowing the write to run
  against content the model has not yet seen.
- Evidence: `docs/superpowers/specs/2026-08-12-apply-patch-recovery-design.md`,
  `docs/superpowers/plans/2026-08-12-apply-patch-recovery-plan.md`, and the reproduced
  `tmp/cube` run `be51368d-c571-4fec-8a05-e699d72c6752`.

### Iteration 17: Dangerous permission-bypass mode

- Question: should shell automation be folded into `autonomous`, exposed as a separate boolean,
  or represented by a fourth first-class permission mode?
- User decision: 采用方案 A（新增一等 `bypass` 模式），语义类似 Claude Code 的 dangerous
  permission-skip behavior.
- Decision: every policy result that would request one-time approval becomes allowed in bypass
  mode. Deterministic denials, schema validation, explicit deny rules, `allow_writes = false`,
  repository and credential boundaries, sandbox constraints, feedback, and budgets remain active.
- Interface decision: support `--permission-mode bypass`, the explicit
  `--dangerously-skip-permissions` alias, `/permissions bypass`, and `/config set mode bypass`.
  Conflicting CLI selections fail rather than silently overriding each other, and the TUI displays
  a conspicuous dangerous-mode warning.
- Uncertainty exposed: “bypass” can mean bypassing approvals or bypassing every policy. The approved
  interpretation is approval bypass only: `ASK` becomes `ALLOW`; `DENY` remains `DENY`.
- Before/after: before, every mode asks for undeclared shell commands and command batches; after,
  explicitly selected bypass runs execute all otherwise approval-eligible actions immediately and
  leave an auditable `mode.bypass.*` decision trail.
- Evidence: `docs/superpowers/specs/2026-08-13-dangerous-bypass-permission-design.md`.
