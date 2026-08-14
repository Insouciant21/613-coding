# 613 Coding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver 613 Coding as a self-owned local TUI/CLI Coding Agent Harness with an objective
feedback loop, safe focused mutation, container-isolated workers, Supervisor orchestration, secure
memory, and CI-built executable/Python artifacts, then finish Cube Solver through that harness.

**Architecture:** A domain/application core owns the agent loop, tool protocol, governance,
feedback classification, interactive sessions, and run state. SQLite is authoritative for
structured state and memory text; LanceDB is a rebuildable vector index. Descriptor-relative
filesystem adapters enforce mutation safety, Textual provides the local interaction adapter, and
Docker remains a worker runtime boundary plus the reproducible release builder.

**Tech Stack:** Python 3.12+, `uv`, Pydantic, pytest, Ruff, mypy, Textual, Typer, SQLite,
LanceDB, `keyring`, Docker Engine API/BuildKit, the official OpenAI SDK for chat providers,
HTTPX for the independent embedding adapter, `unidiff`, and PyInstaller.

## Global Constraints

- Do not use LangChain AgentExecutor, AutoGen, CrewAI, LlamaIndex agents, a coding-agent SDK runner, or another high-level agent loop.
- Every core mechanism must be injectable and testable with mock/fake dependencies, without network access or a real LLM.
- Objective feedback classification, not LLM self-report, controls completion and retry behavior.
- Interactive runs have no low fixed five-turn cap; support per-agent turns, total calls, wall time, and provider-cost budgets. The mock demo may use five turns explicitly.
- Hard path, credential, Docker socket, and destructive-command rules cannot be bypassed by permission mode or memory.
- Workers run as non-root in temporary containers with read-only root filesystems, dropped capabilities, default-deny network, resource limits, and cleanup.
- SQLite is the source of truth; LanceDB stores redacted vectors linked to authoritative SQLite records.
- API keys never enter Git, databases, logs, prompts, subprocess arguments, or worker containers.
- `AGENT_LOG.md`, `PLAN.md`, `SPEC_PROCESS.md`, and `DELIVERY_STATUS.md` are updated with fresh evidence after each significant task.
- No redesign implementation code is written until the three 2026-08-09 redesign plans are
  reviewed and the user selects an execution workflow.

## Plan Registry And Dependencies

| Plan | Scope | Depends on | Status |
| --- | --- | --- | --- |
| `docs/superpowers/plans/2026-08-08-613-coding-core.md` | Domain contracts, tools, feedback, memory, credentials, agent loop | Cold-start gate | complete after final-review repair at `9af4f03` |
| `docs/superpowers/plans/2026-08-08-613-coding-sandbox.md` | Task workspaces and Docker runtime isolation | Core ports and artifacts | complete through `fb1c222` |
| `docs/superpowers/plans/2026-08-08-613-coding-multi-agent.md` | Task graph, workers, Supervisor, artifact integration | Core loop, sandbox | complete through `376fd41` |
| `docs/superpowers/plans/2026-08-08-613-coding-delivery.md` | CLI, FastAPI/WebUI, CI, package, Docker demo, records | Core services; sandbox for demo | complete through Docker smoke repair `774c07a`; real provider remains injectable |
| `docs/superpowers/plans/2026-08-09-613-coding-package-rename.md` | Strict distribution/import/runtime/documentation rename | completed Tasks 1-3 | complete through reviewed CI and SSH deployment at `eefee2d` |
| `docs/superpowers/plans/2026-08-09-safe-repository-mutations.md` | Schema-validated apply_patch and descriptor-relative delete | existing provider/context repair branch | committed in `9ee205d`; pending execution approval |
| `docs/superpowers/plans/2026-08-09-613-coding-tui-distribution.md` | Streaming sessions, Textual TUI, Web removal, PyInstaller, Docker artifacts, CI/CD | safe repository mutations | TUI-01 through TUI-09 integrated and recorded on `main` at `043077a`; remote CI publication remains operator-triggered |
| `docs/superpowers/plans/2026-08-09-cube-solver-recovery.md` | Recover and complete Cube Task 3 through the new TUI | safe mutations and TUI/distribution | committed in `9ee205d`; pending execution approval |
| `docs/superpowers/plans/2026-08-09-cube-solver.md` Tasks 4-9 | Validation, real solver, jobs, 3D editor, playback, local Compose, final audit | Cube Task 3 recovery | approved existing plan; pending prerequisite |
| `docs/superpowers/plans/2026-08-10-openai-sdk-llm.md` | Replace chat/tool HTTP and SSE with the official OpenAI SDK | approved SDK design `b4b5a94` | implemented and integrated into `main` at `8e708e2` (implementation `f7f2301`, repair `0fcd2af`, evidence `581402b`/`8e708e2`) |
| `docs/superpowers/plans/2026-08-11-responses-api-llm.md` | Add selectable OpenAI Responses API request/tool/stream adapter | user request supersedes the Chat-only migration scope | implemented in the current worktree; offline evidence below |
| `docs/superpowers/plans/2026-08-10-613-coding-claude-code-parity.md` | Shared Claude-Code-like TUI/CLI conversation, permissions, context, resume, and output contracts | approved parity design `3a07f09` | Tasks 1-7 complete through `fd8871e`; delivery evidence recorded in `f27dba6` |

The completed historical critical path was `CORE → SANDBOX → MULTI_AGENT → DELIVERY`. The current
critical path is `SAFE_MUTATION → TUI_DISTRIBUTION → CUBE_RECOVERY → CUBE Tasks 4-9`. Do not start
Cube recovery with the old whole-file editing boundary.

## Harness Prompt And Loop Enhancement Evidence (2026-08-11)

- Status: implemented in the existing working tree; no commit was created and no Superpowers skill
  was invoked, per the user's explicit instruction.
- Scope: strengthened the worker prompt with inspect/implement/review task classification,
  evidence-first tool use, scoped mutation guidance, validation feedback discipline, and an explicit
  concurrent-read/ordered-write contract. The context assembler now loads bounded, redacted
  `AGENTS.override.md`/`AGENTS.md`/`CLAUDE.local.md`/`CLAUDE.md` guidance from the selected repository
  root, emits a deterministic run ledger, bounds event evidence, and compacts old dynamic messages
  while retaining the task, ledger, and newest evidence. The loop preflights and concurrently
  dispatches independent read-only batches, then records their results in model order; policy,
  approval, writes, and validation remain on the ordered path.
- TDD: new context tests for repository guidance, ledger, bounded compaction, and newest evidence,
  plus a loop regression proving two independent reads overlap and preserve persisted result order.
  The focused tests were RED before implementation and GREEN afterward.
- Verification: `uv run pytest -q --ignore=tmp` passed 537 tests; `uv run ruff check .`,
  `uv run mypy src`, and `git diff --check` passed. No provider request, credential access,
  remote push, deployment, or target `tmp/cube` source edit was performed.
- References used for behavior only: OpenAI's public agent-loop/context-compaction description and
  Claude Code's public agent-loop/context-management documentation. The harness still owns its
  loop, policy, tool schemas, and deterministic validation; no high-level SDK runner was added.

## User-scoped Configuration Evidence (2026-08-12)

- Status: implemented and offline verified in the current dirty worktree; responsible actor `/root`.
- Scope: keep repository `harness.toml` policy-only; move provider profiles, context-window options,
  and budgets to a user-wide TOML file with atomic writes, keyring-only credentials, CLI profile
  management, and TUI switching.
- TDD/verification: legacy project-`[llm]`/`[budgets]` tests were observed failing at the new
  boundary, then rewritten with user-config and provider-service regressions. Full offline suite
  `uv run pytest -q --ignore=tmp` passed 562 tests with 325 warnings; Ruff, mypy, `uv lock --check`,
  and diff checks passed. The editable CLI was refreshed and provider listing plus the `tmp/cube`
  policy-only config check passed at 2026-08-12 00:18 Asia/Shanghai.
- Files: `src/coding613/config.py`, `application/user_configuration.py`, `cli/providers.py`,
  composition/TUI wiring, project/user config tests, and `tmp/cube/harness.toml`. API keys remain
  outside files; the migrated user file contains only the existing `ai2` credential reference.

## Phase Gates

- [x] Brainstorming design approved and committed.
- [x] Root specification and process records created for review.
- [x] Specification, root plan, four subsystem plans, and initial evidence records committed as `a2909c7`.
- [x] User reviewed `SPEC.md` and `PLAN.md` without requested changes and selected Subagent-Driven execution on 2026-08-08.
- [x] A different agent type cold-started `CORE-01` and `CORE-02` with only `SPEC.md` and `PLAN.md`, recorded the dependency-bootstrap ambiguity, and produced a report referenced by `SPEC_PROCESS.md`.
- [x] The cold-start findings were incorporated: standard-library package baseline, explicit dependency provisioning, air-gapped cache/wheelhouse requirement, and a `DEPENDENCY_PROVISIONING_BLOCKED` stop condition.
- [x] Bootstrap revision committed as `fc7bf53`.
- [x] TUI/mutation/Cube recovery brainstorming approved and committed as `e7f7ece` with evidence
  follow-up `f9d7f47`.
- [x] Root `SPEC.md`, `AGENTS.md`, `SPEC_PROCESS.md`, and delivery status updated for the local TUI
  and artifact-only deployment direction.
- [x] User approved the parity design and detailed plan and selected Inline Execution on
  2026-08-10.
- [x] Each task receives local spec-compliance/code-quality review, fresh verification, a commit, and record updates; independent review agents were unavailable after repeated stream disconnects and that limitation is recorded.

## Task Index

Detailed task steps, file paths, interfaces, failing tests, and commit commands live in the four linked plans. The following IDs are the cross-plan tracking keys:

- `CORE-01` through `CORE-11`: package, domain, providers, storage, tools/policy, validation/feedback, memory, agent loop, credentials, and deterministic demo.
- `SANDBOX-01` through `SANDBOX-05`: sandbox contracts, workspace/artifacts, Docker lifecycle, security/resource policy, and integration evidence.
- `MULTI-01` through `MULTI-05`: task graph, worker runtime, Supervisor scheduling, artifact integration, and orchestration demo.
- `DELIVERY-01` through `DELIVERY-07`: CLI, API, WebUI, distribution, CI, documentation, and delivery-record automation.
- `MUTATION-01` through `MUTATION-04`: descriptor delete, strict diff preflight, descriptor patch
  commit, and tool/policy integration.
- `TUI-01` through `TUI-09`: sessions, streaming, pause, interactive application service, Textual
  shell/workflow, Web removal, artifact builder, CI/CD, and documentation.
- `CUBE-RECOVERY-01` through `CUBE-RECOVERY-04`: baseline, state/move repair,
  orientation/notation/replay, and handoff to original Cube Tasks 4-9.

## DELIVERY-01 Task Evidence

- Status: complete; implementation commit `2a53a73`; evidence commit `37d9841`.
- Verification: focused configuration/credential suite passed 7 tests; full suite passed 201 tests; scoped Ruff and mypy passed; `git diff --check` passed.
- Boundaries: TOML paths are canonicalized, validation commands are argv-only, unattended runs require a finite budget, and credential CLI output is metadata-only with hidden input.

## DELIVERY-02 Task Evidence

- Status: complete; commit `bae307b`; report `.superpowers/sdd/2026-08-08-613-coding-delivery/task-2-report.md`.
- Verification: focused CLI/config/credential suite passed 11 tests; full suite passed 205 tests; Ruff and mypy passed; Typer root help smoke passed.
- Boundaries: commands are thin adapters over injected services and demo functions; JSON/table output and nonzero failures are covered.

## DELIVERY-03 Task Evidence

- Status: complete; commit `a8b1f63`; report `.superpowers/sdd/2026-08-08-613-coding-delivery/task-3-report.md`.
- Verification: API suite passed 5 tests; full suite passed 210 tests; Ruff and mypy passed.
- Boundaries: FastAPI routes are dependency-injected adapters with generic safe errors, ordered events, and lifecycle/approval endpoints.

## DELIVERY-04 Task Evidence

- Status: complete; commit `8403520`; report `.superpowers/sdd/2026-08-08-613-coding-delivery/task-4-report.md`.
- Verification: WebUI/API suite passed 7 tests; full suite passed 212 tests; Ruff and mypy passed; `/`, CSS, and JS smoke returned 200.
- Boundaries: the responsive console consumes API routes only and exposes no credential material; Open Design MCP was unavailable and was not installed.

## DELIVERY-05 Task Evidence

- Status: complete for package artifacts; commit `a0f55b4`; report `.superpowers/sdd/2026-08-08-613-coding-delivery/task-5-report.md`.
- Verification: distribution suite passed 4 tests; full suite passed 216 tests; `uv build`, Ruff, and mypy passed. Docker build was attempted and blocked by Docker Hub token network reset.
- Boundaries: installed `coding-harness` entrypoint and `web` command are present; Docker image runs non-root with healthcheck and no socket mount.

## DELIVERY-06 Task Evidence

- Status: complete; commit `511fdd9`; report `.superpowers/sdd/2026-08-08-613-coding-delivery/task-6-report.md`.
- Verification: recorder suite passed 3 tests; full suite passed 219 tests; Ruff and mypy passed.
- Boundaries: evidence records validate Git commits, retain failures, and suppress duplicate task/commit records; CI stages are explicit.

## DELIVERY-07 Task Evidence

- Status: complete; commit `773bc2a`; report `.superpowers/sdd/2026-08-08-613-coding-delivery/task-7-report.md`.
- Verification: documentation suite passed 3 tests; final full suite passed 222 tests; Ruff, mypy, `uv lock --check`, and `git diff --check` passed.
- Boundaries: README/deployment docs state package, Docker, keyring, `.env`, public-demo, CI, SQLite/LanceDB, and runtime limitations; deployed URL remains explicitly unverified; `REFLECTION.md` contains no AI-written student narrative.
- Final delivery index cleanup: `63c3646` records all DELIVERY statuses as complete and links the final verification evidence.

## SANDBOX-03 Timeout Hardening Evidence

- Status: complete; Docker runtime timeout termination repaired after audit.
- TDD: the focused timeout test first failed because the container was not killed, then passed after the lifecycle fix.
- Verification: focused timeout pair passed 2 tests; full suite passed 225 tests; Ruff, mypy, `uv lock --check`, and `git diff --check` passed.
- Boundary: timed-out commands now terminate the container and cleanup force-removes it without a redundant stop call.

## Runtime Composition Repair Evidence

- Status: complete; local composition is covered by `tests/application/test_composition.py` and commit `d657369`.
- Verification: real CLI create/cancel and FastAPI create/health/events smoke passed; no provider credential or fabricated model response is used.

## Provider-backed Composition Evidence

- Status: implementation complete in `cf252e0`; configured OpenAI-compatible provider metadata now selects a lazy keyring-backed provider while preserving deferred behavior when `[llm]` is absent.
- TDD: config, adapter, injection, and composition-backed persistence-redaction tests followed RED/GREEN cycles.
- Verification: focused provider/config/composition tests passed 13; full suite passed 231 tests; Ruff, mypy across 81 source files, `uv lock --check`, `git diff --check`, and `uv build` passed.
- Boundary: no real provider request was made; key material exists only inside the ephemeral HTTP client and is never serialized.

## Repository Tool Composition Evidence

- Status: implementation complete in `cf25473`; local composition now registers bounded repository tools and a declared-command validator.
- TDD: the end-to-end `read_file` → validation → `finish` test failed before registration and passed after wiring the toolset.
- Boundary: filesystem paths remain canonical-root constrained, validation commands remain argv-only and exact-match policy checked, and tool/validation failures return deterministic loop feedback.

## Real-provider Worker Reliability Repair Evidence

- Status: review blocked. Context, configured-mode inheritance, and bounded file listings work through `0836308`, but pathname-based `delete_file` remains vulnerable to a parent-symlink TOCTOU race and must not merge.
- Scope: stable goal-directed worker context, configured permission-mode inheritance, bounded repository listings, and a pending descriptor-relative `delete_file` redesign using no-follow directory descriptors.
- Verification: real-provider Cube foundation run `46ec4663-1c43-41e7-95d7-ce31f3b7d489` completed successfully; the latest harness verification passed 266 tests, Ruff, mypy across 82 source files, lock check, and diff check. Independent review reproduced the unresolved delete race.
- Evidence: `AGENT_LOG.md` entry `2026-08-09 22:20:00 Asia/Shanghai`; target operation details remain append-only in `tmp/cube/AGENT_LOG.md`.

## CI and Deployment Manifest Evidence

- Status: repository configuration complete in `0d8d63a`; Docker source-copy order fixed, GitLab/GitHub CI container jobs added, and `render.yaml` declares an operator-controlled Web Service.
- Verification: distribution-focused suite passed 7; Docker build attempt failed at external Docker Hub token retrieval, so no Docker or deployment success is claimed.
- Boundary: remote CI final status and public URL require a configured forge/deployment account.

## Safe Repository Mutations Evidence

- Status: Tasks 1-4 complete and integrated into `main` at merge commit
  `69caa09`; user-owned untracked paths remain outside the merge.
- Task 1 commits: 9255c08, 62c4fe6; descriptor-relative delete holds parent
  directory descriptors, rejects parent symlinks and protected roots, permits
  final symlink deletion without following it, and passed its independent
  review plus one fix round.
- Task 2 commits: 338b363, ad2cd04, 80366e5; strict unidiff parser, immutable
  prepared changes, path/header/hunk preflight, UTF-8 and aggregate limits,
  and stable exceptions. Parser suite reached 23 passing tests after two
  scoped review fix rounds.
- Task 3 commits: 1e6fb22, 890e576; descriptor-relative patch staging, fsync,
  atomic replace, delete reuse, sorted PatchResult, and exact partial
  changed-file reporting. Patch/filesystem suite reached 48 passing tests
  after one scoped review fix round.
- Task 4 local implementation wires the versioned schema
  coding613.tool.apply_patch.v1, executor result/error propagation,
  composition integration, permission-mode tests, credential-path hard
  denial coverage, and exact partial-commit changed-file propagation.
- Task 4 review found and fixed a Critical policy bypass: credential paths in
  apply_patch headers are now hard-denied before execution. A second scoped
  review found and fixed root-path replacement during multi-file commits,
  non-OSError partial-error reporting, and strict-parser trailing/target
  length gaps. Final re-review found and fixed root descriptor close-error
  reporting. No Critical or Important findings remain.
- Fresh verification at 2026-08-10 01:52:00 CST: safe mutation and loop
  integration suite passed 133 tests; full suite passed 313 tests with one
  pre-existing Starlette/httpx deprecation warning; Ruff, mypy (83 source
  files), uv lock --check, and git diff --check passed.
- Task 4 implementation commit: `c6ce018`; final close-boundary fix commit:
  `e80883b`; evidence-record commit follows after this hash is linked.
- Delegation deviation: 613 Coding run
  51a8e02a-3e46-4ed6-93b2-aae093be16b2 exhausted 20 model calls repeating
  git diff --check without writes; earlier Task 2 runs
  9b284a12-6d32-4c34-8c39-db4b1be7877b,
  63b5fe3e-9790-4f5a-95a0-66789d363b74, and
  1d87af44-3373-409d-86de-44c8a1bbe61d showed provider/no-progress
  behavior. Controller takeover and all deviations are recorded in
  AGENT_LOG.md and the SDD ledger.

## TUI-01 Task Evidence

- Status: complete after an independent scoped re-review confirmed both Important findings are
  addressed with no new Critical or Important breakage; Task 2 may start.
- Commits: `66c11d8` (`feat: persist interactive coding sessions`) and `b45bb71`
  (`fix: make session migration atomic`).
- TDD evidence: the original domain/storage collection RED failed because `InteractiveSession`
  was absent. Fix-round RED failed 3 targeted tests: late SQLite index denial left v1 schema
  objects behind, a later UTC Run did not advance an offset-bearing session, and existing offset
  session rows sorted lexically rather than chronologically.
- Fix: schema statements, v1 table/index additions, and `PRAGMA user_version = 1` now run in one
  explicit SQLite transaction. Run and interactive-session timestamps persist in UTC; existing
  relevant rows normalize transactionally on opening, preserving chronological ordering and
  microsecond precision.
- Verification: focused domain/storage suite passed 19 tests; full harness suite passed 322 tests
  with one existing Starlette/httpx deprecation warning. Ruff, mypy for 15 relevant source files,
  `uv lock --check`, and `git diff --check` passed.
- Boundaries: migration remains additive and retains legacy Run/Event data. No WebUI, Cube,
  credentials, deployment, `.claude/`, or course-requirement file changed.
- Review: scoped review of `66c11d8..c23f217` found the atomic migration and chronological
  timestamp findings ADDRESSED, with no new breakage or out-of-scope observations.

Every task must end with a focused test result and commit hash. `DELIVERY_STATUS.md` must link the evidence before a task is marked complete.

## TUI-02 Task Evidence

- Status: complete through `330d4a5` (`feat: stream provider progress through application ports`);
  evidence record follows in the scoped documentation commit.
- Inherited recovery: a prior external implementer left the Task 2 code and tests uncommitted after
  recording valid initial RED/GREEN evidence, but authentication failed before it could record a
  report or commit. Controller baseline verification before recovery was `334 passed` under
  `uv run pytest -vv --ignore=tmp`.
- Fresh RED: the added focused regression command failed as expected with 10 failures: nested
  `RunProgress.payload` mutation was allowed; three non-object normal messages leaked
  `AttributeError`; five malformed SSE tool-call containers/fragments were accepted or leaked
  `AttributeError`; and one credential assertion initially expected empty provider metadata.
- Fix: progress payloads now recursively freeze built-in containers while retaining the specified
  dict-compatible field; normal and streamed provider messages validate container/fragment types
  before parsing; streaming remains optional through a runtime-checkable port; and credentialed
  delegates are lazily built and reused.
- GREEN: the final focused Task 2 suite passed 30 tests. Scoped Ruff passed, mypy passed for 14
  source files, the full offline suite passed 342 tests with one existing Starlette/httpx warning,
  `uv lock --check` and `git diff --check` passed.
- Boundaries: no `tmp/cube`, `.claude/`, course requirement, credential, deployment, Web removal,
  TUI view, or later-task file changed. `RunProgress` remains ephemeral; no progress is persisted.
- Review fix round 1: independent review found streamed tool calls fabricated `call-{index}` when
  the provider omitted an ID. TDD RED failed the new missing-ID regression; the parser now rejects
  incomplete streamed tool calls and uses only provider-supplied IDs. Focused suite passed 31,
  full offline suite passed 343 with the same existing warning, Ruff/mypy/lock/diff checks passed.
- Review status: fix finding addressed by the focused regression and scoped diff verification;
  independent re-review dispatch was unavailable in this turn and remains a process follow-up for
  the broad branch review.

## TUI-03 Task Evidence

- Status: implementation locally verified; independent task review pending.
- TDD RED: the two new progress/cancellation tests failed because `LoopDependencies` had no
  `progress` or `cancellation` fields.
- GREEN: focused loop/composition suite passed 50; loop/composition/CLI regression suite passed 55;
  Ruff and mypy for application code passed.
- Behavior: progress is ephemeral and sink failures are isolated; provider cancellation persists
  `PAUSED` with no stop reason; `RunService.pause()` supports active and idle nonterminal runs.
- Regression repair: non-streaming progress fallback now ignores raw malformed provider values
  until Loop schema validation, preserving the pre-existing invalid-response repair path.

## TUI-04 Task Evidence

- Status: implementation locally complete; independent task review unavailable because the external
  Codex refresh token is invalidated.
- TDD RED: five workflow tests failed on absent `LocalServices.interactive`.
- GREEN: interactive/context/composition suite passed 20; full offline suite passed 352 with the
  existing Web test deprecation warning; Ruff, mypy, lock, and diff checks passed.
- Behavior: sessions and linked Runs restore from SQLite, transcripts use persisted final response
  content only, newest nonterminal Run is active, and history injection is capped at 12 entries and
  12,000 characters with repeat redaction.

## TUI-05 Task Evidence

- Status: root dispatch and Textual shell locally complete; independent review deferred with the
  recorded external authentication blocker.
- RED: CLI/TUI test collection failed on missing `coding613.cli.tui` and `coding613.tui` modules.
- GREEN: focused entrypoint/Pilot suite passed 13; full offline suite passed 365; Ruff, mypy, lock,
  and diff checks passed.
- Behavior: root invocation opens TUI, task words prefill the composer, five management commands
  retain Typer dispatch, and 80x24/60x20 layouts keep stable full-width regions.
- Source record: `.superpowers/sdd/2026-08-09-613-coding-tui-distribution/task-2-report.md`.

## TUI-06 Task Evidence

- Status: complete; commit `048bdbc`; source record `.superpowers/sdd/2026-08-09-613-coding-tui-distribution/task-6-report.md`.
- TDD/Pilot: controller, command, renderer, approval, long-diff, pause, provider-error, and
  narrow-terminal tests passed; the full Task 6 regression command passed 95 tests.
- Behavior: UI-thread progress draining, one streamed assistant Markdown per Run, persisted
  transcript reconciliation, public approval lookup/fingerprint details, explicit approval keys,
  slash commands, provider metadata, redacted bounded details, and idempotent Esc pause.
- Static/reproducibility gates: scoped Ruff and mypy passed; `uv lock --check` and `git diff --check`
  passed. No remote review claim is made because the external Codex token remains invalidated.

## TUI-07 Task Evidence

- Status: complete; commit `4877a7f`; the main FastAPI/WebUI/Render/runtime-container surface and
  positive tests were removed while worker Docker and multi-agent application code remained.
- TDD: absence contracts initially failed on dependencies, root `web`, removed paths, and current
  guidance; after deletion, removal/CLI/application tests passed 143 and the full offline suite
  passed 380 tests.
- Static gates: Ruff, mypy, `uv lock --check`, and `git diff --check` passed. Current README and
  operations guidance describe only local TUI/CLI, keyring, SQLite/LanceDB, worker sandbox, and
  artifact operation; historical records are left outside the current-guidance scan.

## TUI-08 Task Evidence

- Status: complete and merged to `main` through `4528bda`.
- Root-cause fixes: the standalone wheel explicitly declares its direct `click` runtime dependency;
  the pinned Debian slim builder installs `binutils` required by PyInstaller's Linux analysis.
- Verification: focused distribution/CI tests passed 11; local build and smoke passed for binary,
  wheel, sdist, and `SHA256SUMS`; Docker BuildKit `--target artifacts` export succeeded and its
  output passed smoke; Debian Bookworm slim executed the exported binary with `--help`.
- Artifact evidence: Docker output binary is 152M, `file` reports ELF 64-bit LSB x86-64, and
  `sha256sum -c SHA256SUMS` passed. GitHub/GitLab workflows now upload or retain the four artifacts
  and no longer reference the removed runtime container smoke script.
- CI portability follow-up: GitHub installs pinned uv before artifact smoke; GitLab separates the
  Docker export job from a dependent Python/uv `artifact-smoke` job. The updated contract test,
  full 388-test offline suite, Ruff, mypy, lock, and diff checks passed.
- Review fix: GitLab's Docker CLI producer explicitly disables inherited Python setup and contains
  no smoke invocation; the dependent Python/uv job is the sole artifact smoke consumer.
- Final review fixes: session resume reconstructs persisted summaries, continues the same paused
  Run, and restores pending approval actions after restart. Fresh deliverables each passed config
  inspection and the offline core demo; focused 111 and full 392-test suites plus all static gates
  passed.

## TUI-09 Task Evidence

- Status: complete for configured CI/CD and exact-main local verification; no remote pipeline or
  release is claimed without an explicit push/tag action.
- CI/CD: GitHub uploads verified `dist/` on push/PR and tag-only `v*` runs publish the exact
  binary, wheel, sdist, and `SHA256SUMS`; GitLab keeps its required `unit-test`, exports through
  Docker DinD, and verifies in a dependent Python/uv artifact-smoke job.
- Documentation: current README/deployment/development guidance covers the local Textual workflow,
  pause/recovery and approval controls, headless Secret Service boundary, glibc platform limit,
  artifact build/verification, CI locations, and worker-Docker prerequisite without remote server
  operation instructions.
- Exact-main gates: `uv run pytest -q --ignore=tmp` passed 392 tests; Ruff, mypy, lock, diff,
  root CLI help, and removed-import checks passed. BuildKit exported the four files, enhanced smoke
  passed binary/wheel config and core-demo commands, Debian slim executed binary help, and all
  checksums passed. Pilot restart test preserved the paused Run ID and transcript.

## SSH Deployment Follow-up

- Status: complete for loopback deployment; public reverse proxy remains operator-owned.
- Defect repair: fresh persisted runs without a `LoopSession` now return an empty-evidence `RunSummary`; commits `4d1fbad` and `71c281d`.
- Review and verification: independent review found no Critical/Important issue; full suite passed 239 tests; Ruff, mypy, lock, and diff checks passed; branch CI `31295983040` and main CI `31296034199` passed.
- Runtime evidence: image `613-coding:71c281d` runs on `edward@int21` at `127.0.0.1:8613`. Health, WebUI, unchanged security/resource settings, pre-existing SQLite data, immediate run retrieval, and post-restart retrieval were verified.
- Operator boundary: configure the reverse proxy/domain to `http://127.0.0.1:8613`; the deployment task did not modify ports 80/443 or claim a public URL.

## CORE-01 Task Evidence

- Status: complete after task review and bootstrap repair.
- Commit: `4d51108` scaffold; repair commit is recorded in the task ledger and delivery status.
- Verification: focused standard-library unittest and `py_compile` passed; the current 61-package lock passes; full `uv sync --all-extras --frozen` and canonical checks now pass.
- Gate: `uv run python scripts/bootstrap_dev.py` reports `DEPENDENCIES_PROVISIONED`; full LanceDB/PyArrow sync is complete.

## CORE-02 Task Evidence

- Status: complete; implementation commit `59bc4f2`, delivery evidence `2934063`, review-fix commit `69b1c59`; scoped review recorded in the task report.
- Verification: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run --no-sync pytest tests/domain -q` passed with 7 tests; `uv run --no-sync ruff check src/coding_harness/domain tests/domain` passed; `uv run --no-sync mypy src/coding_harness/domain` passed.

## CORE-03 Task Evidence

- Status: complete; commit `e8b938f`; scoped contract review clean.
- Verification: 4 focused port tests and 11 combined domain/port tests passed; Ruff and mypy passed for the same scope.

## CORE-04 Task Evidence

- Status: complete; commit `a97e711`; scoped storage review clean.
- Verification: 5 focused SQLite tests and 16 combined core tests passed; Ruff and mypy passed; temporary concurrent appends completed without loss.

## CORE-05 Task Evidence

- Status: complete; commit `2dcb00e`; scoped adapter review clean.
- Verification: 7 focused LLM-adapter tests and 23 combined core tests passed; Ruff and mypy passed; HTTP tests were fully offline.

## CORE-06 Task Evidence

- Status: complete; commit `44a4a9a`; scoped tool/security review clean.
- Verification: 8 focused repository-tool tests and all 32 project tests passed; Ruff, mypy, and `uv lock --check` passed.

## CORE-07 Task Evidence

- Status: complete; commit `8956821`; scoped governance review clean.
- Verification: 17 focused policy/approval tests and all 49 project tests passed; Ruff and mypy passed.

## CORE-08 Task Evidence

- Status: complete; commit `1e01249`; scoped feedback/budget review clean.
- Verification: 19 focused feedback/budget/runner tests and all 68 project tests passed; Ruff and mypy passed.

## CORE-09 Task Evidence

- Status: complete; commit `86c4633`; scoped memory/privacy review clean.
- Verification: 7 focused real SQLite/LanceDB/context tests and all 75 project tests passed; Ruff, mypy, and `uv lock --check` passed.

## CORE-10 Task Evidence

- Status: complete after persistence/audit hardening and independent scoped re-review.
- Commits: `2dd32f9` (`feat: implement feedback-driven agent loop`), `d705637` (`fix: persist and audit agent loop state`), `06b397e` (`fix: harden persisted agent loop recovery`), `f9394d7` (`docs: record CORE-10 recovery hardening`).
- TDD evidence: focused REDs covered process reconstruction, redacted persistence, atomic approval/session state, policy re-evaluation, dependency failures, unresolved completion feedback, classifier restoration, exact budget accounting, and secret-bearing action denial.
- Verification: `uv run pytest -q` passed with 110 tests; Ruff, mypy, `uv lock --check`, and `git diff --check` passed. The offline demo returned `completed/success`, persisted `runs.state=completed`, observed objective feedback, blocked the guardrail escape, retrieved memory, and corrected `answer.py` to `return 2`.
- Boundaries: SQLite persists serializable loop session, approval, budget, validation, and audit state; runtime dependencies are reconstructed through the factory. The repository owns the loop; objective validation controls `finish`; the offline demo uses a scripted LLM and an explicit five-call demo budget only.
- Review: scoped re-review from `f154bba` through `f9394d7` marked all original findings addressed with no new Critical/Important breakage. A stale concurrent `RunService._persist_status` observation was outside the fix diff and is deferred to final whole-branch review.

## CORE-11 Task Evidence

- Status: complete after independent task review and fix round 1.
- Commits: `552593e` (`feat: secure provider credentials`); `d748a0e` (`fix: harden credential error handling`).
- TDD evidence: the initial focused suite failed during collection because the credentials adapter package did not exist. Fix-round RED reproduced the backend double-fault as a raw `get_password` exception with 1 failed and 5 passed.
- Verification: `uv run pytest tests/adapters/credentials/test_keyring.py -q` passed with 6 tests; `uv run pytest -q` passed with 116 tests; Ruff, mypy, `uv lock --check`, and `git diff --check` passed.
- Boundaries: status and `SecretReference` are metadata-only; OS keyring access is injectable; provider entries are isolated; environment fallback is opt-in; raw-secret provider injection remains a separately governed future integration boundary.
- Review: independent review found two Important issues in backend double-fault handling and source type narrowing. Fix round 1 addressed both; scoped re-review found no new Critical/Important breakage. Two Minor findings remain in the Core ledger for final review.

## Core Final-Review Evidence

- Status: complete after whole-branch review repair.
- Implementation/evidence commit: `9af4f03` (`fix: close core final review findings`).
- Findings repaired: SQLite connections now close after successful and exceptional repository operations; run-state persistence uses atomic full-snapshot compare-and-set; stale races and later terminal entry points return authoritative terminal state and stop reason without re-entering mutating loop paths.
- TDD evidence: initial focused RED produced 6 failed and 42 passed; review-repair RED produced 2 failed and 33 deselected. Final required focused suite passed 50 tests.
- Verification: `uv run pytest -q` passed with 126 tests; `uv run ruff check .`, `uv run mypy src`, `uv lock --check`, and `git diff --check` passed.
- Review: independent reviewer found no Critical/Minor issues and one Important terminal-entry gap; the gap was addressed through a separate RED/GREEN cycle. Full evidence is in `.superpowers/sdd/2026-08-08-613-coding-core/core-final-review-fix-report.md`.

## SANDBOX-01 Task Evidence

- Status: complete after independent task review and fix round 1.
- Commits: `024925a` (`feat: define sandbox runtime contract`); `5d4e787` (`fix: require finite sandbox duration limits`).
- TDD evidence: focused collection failed before implementation because `coding_harness.adapters.sandbox` was absent.
- Verification: focused sandbox contracts passed 5 tests; the full offline suite passed 131 tests; Ruff, mypy across 48 source files, `uv lock --check`, and `git diff --check` passed.
- Boundaries: specs enforce pinned SHA-256 image digests, non-root/read-only/capability-free workers, default-deny network, finite resources, and validated environment names. Handles expose only an opaque UUID and workspace path; the fake runtime records create/execute/export/destroy and rejects destroyed handles.
- Workflow note: the external implementer's nested bwrap test process did not exit after the suite; the controller reproduced the same worktree successfully outside that nested sandbox and recorded the deviation in `AGENT_LOG.md` and the task report.
- Review fix: positive infinity was accepted for CPU and timeout limits. Focused RED produced 2 failed and 7 passed; the finite-value constraint then passed 9 focused and 135 full-suite tests. Ruff, mypy, lock, and diff checks passed. Scoped re-review marked the finding `ADDRESSED` with no new Critical/Important breakage or out-of-scope observations.

## SANDBOX-02 Task Evidence

- Status: complete after independent review and filesystem-root repair.
- Commits: `698863c` (`feat: isolate task workspaces and export artifacts`), `840cc21` (`fix: bind sandbox artifacts to owned workspaces`), `aa3600a` (`fix: reject replaced sandbox workspace roots`).
- TDD evidence: initial focused collection failed with two missing-module errors. Controller hardening reproduced and fixed incomplete temporary-root cleanup, dotfile allowlist corruption, empty-allowlist fail-open behavior, ignored explicit empty baselines, and missing mode-only changes.
- Verification: 17 focused workspace/artifact tests, 26 sandbox tests, and all 152 project tests passed. Ruff, mypy across 50 source files, `uv lock --check`, and `git diff --check` passed.
- Boundaries: complete repository-shaped copies retain ignored/untracked files; manager-issued immutable workspaces reject forged and replaced roots; empty write sets deny changes; deterministic redacted artifacts include text, binary summaries, deletions, and Git mode changes; cleanup removes only complete manager-owned temporary roots.
- Review: initial Critical/Important findings were fixed in `840cc21`; scoped re-review found and `aa3600a` fixed external symlink-root replacement. No Critical/Important finding remains.

## SANDBOX-03 Task Evidence

- Status: complete through implementation and handle-ownership repair; real Docker smoke explicitly skipped because no approved pinned worker image was local.
- Commits: `bf129cd` (`feat: run workers in temporary docker containers`), `3ec6ac1` (`fix: harden docker runtime handle ownership`).
- TDD evidence: focused collection failed before implementation due to the missing Docker adapter. Final focused runtime suite passed 8 tests.
- Verification: 34 sandbox tests and all 160 project tests passed; Ruff, mypy across 52 source files, `uv lock --check`, and `git diff --check` passed.
- Boundaries: only manager-created copied workspaces are mounted; container options pin image/user/read-only/capability/network/memory/PID/CPU settings; command timeouts and output caps map to `CommandResult`; artifacts export through the manager-bound exporter; stop/remove/workspace cleanup runs across failure paths.

### SANDBOX-03 Audit Repairs

- Timeout hardening: commit `f5d62a9`; timed-out commands kill the worker before returning and cleanup force-removes terminated containers. Focused timeout pair and full suite passed.
- Disk quota wiring: commit `287202a` adds `storage_opt={"size": str(ResourceLimits.disk_bytes)}` after a focused RED/GREEN cycle. Docker storage-driver project-quota support remains an explicit runtime prerequisite.

## SANDBOX-04 Task Evidence

- Status: complete; commit `439540f` (`feat: enforce sandbox resource and network policy`).
- TDD evidence: focused collection failed before implementation because `SandboxPolicyConfig` was absent; final focused policy suite passed 8 tests.
- Verification: all 168 project tests passed; Ruff, mypy across 53 source files, `uv lock --check`, and `git diff --check` passed.
- Boundaries: hard rules precede mode, autonomous cannot override root/capability/read-only/image/credential/resource denials, network allowlists are exact and recorded, and resource violations map to deterministic `resource_exhausted` decisions.

## SANDBOX-05 Task Evidence

- Status: complete; commit `fb1c222` (`test: demonstrate container sandbox boundaries`).
- TDD evidence: focused demo collection failed before implementation because `coding_harness.demo.sandbox` was absent; final demo test passed 1.
- Demonstration output: all seven summary boundaries were `true`: two isolated workers, privileged command denial, Docker socket denial, default-deny network, timeout/resource mapping, artifact export, and cleanup.
- Verification: full project suite passed 169 tests; Ruff, mypy across 54 source files, `uv lock --check`, and `git diff --check` passed.
- Real Docker smoke was guarded and skipped without pulling an unapproved image because no pinned worker image was local.

## Delivery Container Smoke Repair Evidence

- Status: complete; commit `774c07a` (`test: smoke container distribution in ci`).
- Root cause: the built image created `/app/.venv/bin/coding-harness` but did not expose that directory on `PATH`; the first local container exited `127` with `coding-harness: not found`.
- TDD evidence: the runtime-path contract and reusable smoke-script behavior both failed before implementation, then passed after adding the image `PATH`, pinned base digest, and `scripts/smoke_container.sh`.
- Verification: the delivery-focused suite passed 9 tests; the full isolated suite passed 237 tests; Ruff, mypy, and `git diff --check` passed. Local `613-coding:smoke-fix` output was `container smoke passed: health=healthy user=coding` with no retained container.
- Remote evidence: main commit `cf7f8a5` passed GitHub Actions run [31288535830](https://github.com/Insouciant21/613-coding/actions/runs/31288535830); package/container job [93181629275](https://github.com/Insouciant21/613-coding/actions/runs/31288535830/job/93181629275) passed both the pinned Docker build and `scripts/smoke_container.sh`.

## Package Rename Task 3 Evidence

- Verification timestamp: `2026-08-09 14:26:25 Asia/Shanghai`.
- Status: current guidance and local artifact verification complete; dedicated commit recorded in `.superpowers/sdd/2026-08-09-613-coding-package-rename/task-3-report.md`.
- TDD evidence: `uv run pytest tests/test_docs.py::test_current_docs_use_613_coding_package_names -q` was RED with one assertion failure because `613-coding web` was absent. After updating only current guidance, the same command was GREEN with `1 passed`.
- Verification: documentation suite passed `4`; full suite passed `241` with the pre-existing deferred Starlette TestClient warning; Ruff, mypy across `82` source files, `uv lock --check`, and `git diff --check` passed.
- Distribution: clean `uv build` produced `613_coding-0.1.0-py3-none-any.whl` and `613_coding-0.1.0.tar.gz`; an isolated venv installed `613-coding`, exposed `613-coding --help`, omitted the old console script, and could import `coding613` without the old import package.
- Container: `docker build --pull=false -t 613-coding:rename-smoke .` built the tagged image and `scripts/smoke_container.sh 613-coding:rename-smoke` returned `container smoke passed: health=healthy user=coding`; the smoke container was removed.

## Package Rename Task 4 Evidence

- Verification timestamp: `2026-08-09 14:49:47 Asia/Shanghai`.
- Release: independent whole-branch review found no Critical or Important findings; commit `eefee2dd2a2f33ea9921fe0ce147e88719d4b14d` was fast-forwarded to `main` only after branch run [31299368456](https://github.com/Insouciant21/613-coding/actions/runs/31299368456) passed all four jobs. Exact-main run [31299431092](https://github.com/Insouciant21/613-coding/actions/runs/31299431092) then passed `unit-test`, `quality`, `demo`, and `package-and-container`.
- Deployment: immutable release `/home/edward/services/613-coding/releases/eefee2d` built image `613-coding:eefee2d` with ID `sha256:61d42ea1397ba878caf0a04592b3b6c1637c9ee9537deb3b2657ab91a913b0b2` on `edward@int21`.
- Runtime: the deployed container exposes `613-coding`, has no `coding-harness`, and returns 200 for `/healthz` and `/`. Existing runs `c0313a2c-7513-4a7b-a594-9afe0d31dc70` and `b9bc83a2-dac2-48c3-a15a-8bae7568118b` remained readable.
- Restart persistence: new run `de1c5292-d40f-4924-8d0d-2d85df1b4731` returned 200 before and after `docker restart 613-coding`; the container returned to healthy.
- Boundary: `127.0.0.1:8613:8000`, the `/app/.613-coding` data bind, read-only root, bounded no-exec tmpfs, dropped capabilities, `no-new-privileges`, 1 GiB/1 CPU/256 PIDs, group 1000, user `coding`, and `unless-stopped` were preserved. Reverse proxy configuration and ports 80/443 were untouched; no public URL is claimed.

## OPENAI-SDK-LLM Task Evidence

- Status: implementation, review repair, evidence, and local integration complete at `8e708e2`;
  unrelated user changes remain uncommitted and preserved.
- TDD RED: the new SDK-boundary suite initially failed 2 tests because the old credential factory
  still expected an HTTP client and the production chat adapter still imported `httpx`/contained
  the direct chat endpoint. The failures were observed before the migration implementation.
- GREEN: initial migration `uv run pytest tests/adapters/llm -q` passed 33 tests; after review
  repair the adapter suite passed 37 tests, application/composition/CLI regressions passed 25,
  the clean feature branch passed 405 tests, and the merged main worktree passed 408 tests.
- Static verification: `uv run ruff check .`, `uv run mypy src`, `uv lock --check`, and
  `git diff --check` passed on the implementation commit. `uv run pytest tests/test_docs.py -q`
  passed 5 tests.
- Boundary: sync and streamed chat/tool calls use injected official-SDK-shaped clients and
  `chat.completions.create`; the production chat adapter has no direct `httpx` or
  `/chat/completions` path. The embedding adapter remains intentionally unchanged. No real
  provider request or credential operation was performed.
- Review: the first independent review found two Important cleanup/secrecy risks; `0fcd2af`
  closes the SDK stream before joining its reader, reports a reader that remains alive, suppresses
  credential exception causes, and closes a returned client on delegate-construction failure.
  Follow-up review found no remaining Critical or Important issues; one Minor observability note
  is retained in `AGENT_LOG.md`.
- Integration: main was fast-forwarded to `8e708e2` after stashing tracked user changes; the
  unrelated context/loop/domain/test paths were restored and verified. The recovery stash
  `stash@{0}` remains intentionally retained, and untracked `.claude/`, course documents, and
  `tmp/` were not staged or modified.

## CLAUDE-CODE-PARITY Task Evidence

- Status: Tasks 1-7 complete in isolated worktree branch `feature/claude-code-parity`; delivery evidence is recorded in `f27dba6`.
- Commits: `d8894d6` conversation boundary; `2f49041` event/output contracts; `e6a0542` root print CLI; `5fe88dc` TUI controls; `b7111cd` invocation permission filters and project rules; `67206b7` context/diagnostics; `fd8871e` shared TUI/CLI follow-up and output-boundary repairs.
- Verification: the final offline gate passed 460 tests; Ruff, mypy across 102 source files, `uv lock --check`, and `git diff --check` passed. CLI help returned 0 and the provider-unconfigured print smoke returned documented code 4.
- TDD evidence: each task recorded a missing-boundary RED before implementation; Task 5 covered missing storage methods, policy-rule application, loop filter injection, and application permission service.
- Boundary: CLI and TUI use the shared conversation/run services; filters and project rules remain subject to hard policy, deterministic validation, and SQLite authority. Main-worktree user edits remain unstaged and untouched.
- Task 6: `67206b7` adds SQLite-authoritative context summaries, deterministic accounting/compaction, injected diagnostics, redacted system prompts, and per-request model overrides. Focused Task 6 passed 43 tests; full offline regression passed 443 tests.

## Claude-Code-Parity Task 7 Evidence

- Verification timestamp: 2026-08-10 14:50:00 Asia/Shanghai.
- Commits: `fd8871e` (`feat: align tui and cli conversation workflow`) and `f27dba6` (delivery evidence and plan status).
- TDD/verification: RED contract failures were observed for missing documentation markers, follow-up-after-resume, lifecycle/diagnostic stream events, escaped slash prompts, invalid resume selectors, active-run duplication, shared-service delegation, and persisted prompt redaction. GREEN focused suites passed; final `uv run pytest -q --ignore=tmp` passed `460`; Ruff, mypy (102 files), lock, and diff checks passed.
- Boundary: `LocalServices.interactive` now delegates the TUI compatibility shape to the same `ConversationService` consumed by print mode; stream JSON is one versioned redacted event per line with session/user/diagnostic lifecycle records and monotonic sequence numbers. Active sessions cannot receive a second Run concurrently, and stored run tasks are redacted.
- Smoke/review: `613-coding --help` returned 0; provider-unconfigured print/verbose-stream smokes returned documented code 4 with safe output. Independent review agents repeatedly disconnected before producing a report; local spec/security/type review found no unresolved Critical issue, and no independent pass is claimed. Main-worktree user changes remained untouched.

### Claude-Code-Parity completion audit evidence

- Verification timestamp: 2026-08-10 15:04:34 Asia/Shanghai.
- RED: the audit tests first exposed absent verbose validation/feedback/approval output, missing
  TUI terminal summary/footer/elapsed/pause behavior, and strict parsing of a JSON-safe validation
  progress payload. The failures were observed before the corresponding implementation changes.
- GREEN: commit `45decdd` (`feat: expose tui and cli run feedback`) adds the bounded/redacted run
  summary, repository/session/model/provider footer, elapsed active-operation state, Ctrl-C pause
  request, verbose CLI evidence, and a real Textual Pilot prompt-to-harness integration test.
- Verification: TUI suite 51 passed; CLI suite 33 passed; full offline suite 468 passed. Ruff,
  mypy across 102 source files, `uv lock --check`, and `git diff --check` passed. The root CLI help
  smoke returned 0 and the provider-unconfigured print smoke returned 4 with a safe terminal state.
- Boundary: no provider request, keyring access, network, Docker, remote CI, merge, or main-worktree
  mutation was performed; unrelated dirty main files remain outside this branch.

## Same-Run Provider Retry Evidence

- Verification timestamp: 2026-08-10 18:05:00 Asia/Shanghai.
- Scope: make the owned `AgentLoop` continue across transient OpenAI-compatible provider timeouts
  without an external controller restart, while retaining explicit model-call and wall-clock limits.
- TDD RED: the focused timeout retry test failed with a terminal provider error before the change.
- GREEN: `RetryableProviderError` is a port-level marker; the SDK adapter marks timeout failures;
  `AgentLoop` persists retryable environment feedback and continues the same run. The focused
  application/adapter tests passed 71, `uv run pytest tests -q` passed 472, Ruff passed, and mypy
  passed for 102 source files.
- Boundary: authentication, policy, tool, context, and other non-retryable dependency failures
  remain terminal; `deepseek-chat` was not used after the explicit user override.

### Claude-Code-Parity local integration evidence

- Verification timestamp: 2026-08-10 16:22:48 Asia/Shanghai.
- User selected option 1; `feature/claude-code-parity` fast-forwarded `main` from `75c6877` to
  `0c37379`.
- The dirty main worktree was preserved through recoverable `stash@{0}`; the one context conflict
  was manually resolved by retaining both the no-progress escalation and `ContextSummaryStore`.
- Merged-main verification passed 471 tests (253 existing pytest-asyncio deprecation warnings),
  Ruff, mypy (102 files), `uv lock --check`, and `git diff HEAD --check`. User-owned tracked and
  untracked files remain uncommitted and unstaged.

## Self-iteration target audit (2026-08-10 21:19:31 Asia/Shanghai)

- Status: the root harness retry slice is implemented; the external `tmp/cube` product run is not
  complete and is intentionally not marked done.
- Evidence: `5bdaef15-c288-429c-b3ac-5cd22d7dd1a6` persisted 16 model calls in one run and briefly
  reached 43/43 web tests, but oscillated on a single lint error. Bounded follow-ups
  `ae7c581b-e52f-4fc2-9d15-30fb7eedf4fb`, `54240807-d35b-4b76-863e-41836f2d3539`, and
  `74a5ee84-f4f3-41b8-9dc4-bd5d8f47f1cc` failed to perform the requested minimal repair and were
  cancelled after repeated read/rewrite behavior.
- Verification: the target `bash scripts/verify.sh` remained RED in the final worker artifacts;
  no controller edit or completion claim is recorded. Root offline verification remains the
  acceptance gate for this harness slice.
- Fresh independent target verification at 21:22 returned 36/43 web tests failing with
  `TypeError: cloneStickers is not a function` from `moves.ts:212`; this is the explicit blocker.

## Root verification refresh (2026-08-10 21:23:17 Asia/Shanghai)

- `uv run pytest tests -q`: 473 passed (253 existing warnings).
- Retry-focused tests passed; Ruff, mypy (102 files), `uv lock --check`, and `git diff --check`
  passed.
- Target boundary: `tmp/cube` remains RED and is not included in the root offline suite.

## Repeated-write guard (2026-08-10 22:18:00 Asia/Shanghai)

- Status: harness boundary complete; target implementation remains in progress.
- TDD: the new exact successful-write replay test was observed RED before implementation and GREEN
  afterward. The guard covers all owned write tools and only blocks a matching prior successful
  mutation with non-empty changed files.
- Verification: `uv run pytest tests -q` passed 481 (253 existing warnings), Ruff passed, mypy
  passed for 102 files, `uv lock --check` passed, and `git diff --check` passed.
- Target evidence: run `559fb873-1725-464c-9289-6e573e2893a9` reached 43/43 web tests but exhausted
  its 30 model-call budget while build/API contracts remained RED. The next target run must restore
  the missing state helpers once, then repair build errors one module at a time.

## Codex patch-format compatibility (2026-08-10 21:37:42 Asia/Shanghai)

- Status: complete for the harness boundary; target implementation remains in progress.
- TDD: the Codex marker-format update test was observed RED before the parser change and GREEN
  afterward.
- Verification: focused patch/application tests passed 81; full `uv run pytest tests -q` passed
  475, Ruff and mypy passed, and lock/diff checks passed.
- Implementation: `prepare_patch` accepts `*** Begin/Update/Add/Delete/End Patch`, normalizes it
  into the existing strict unified-diff path, and retains repository path and hunk safety checks.
- Next task: launch a fresh patch-only, same-process 613 Coding run against `tmp/cube` and verify
  the target's independent `bash scripts/verify.sh`.

## 613 Coding target foundation/domain slice (2026-08-10 23:25:55 Asia/Shanghai)

- Status: foundation/domain slice completed by governed 613 Coding worker runs; the controller did
  not author target product source. The full design acceptance criteria remain open.
- Delivered: flat 2x2–7x7 cube state, move/wide/rotation behavior, undo/redo/reset, storage
  validation, notation compatibility, coordinate helpers, history/random helpers, and the web/API
  foundation. Full 3D UI, solver jobs, rich validation, and browser workflow are not yet claimed.
- Verification: `(cd tmp/cube && bash scripts/verify.sh)` passed 43 web tests, lint, typecheck,
  production build, API pytest, Ruff, and mypy. The sensitive worker temporary file `tmp` was
  removed through governed `delete_file`; target scanning found no credential-like pattern.
- Worker evidence: cleanup run `5f3869d6-e25c-4716-b438-c558c6e9e141`; repair run IDs are in the
  corresponding `AGENT_LOG.md` entry.
- Root gate: `uv run pytest tests -q` passed 481; Ruff, mypy, `uv lock --check`, and
  `git diff --check` also passed.

## 613 Coding target workbench/API vertical slice (2026-08-11 00:14:26 Asia/Shanghai)

- Status: the responsive interactive web workbench and deterministic validation API slice are
  complete through governed 613 Coding runs; the complete cube-solver product remains in progress.
- Delivered: selectable 2x2–7x7 sticker grids, palette painting, revision status, move entry,
  undo/redo/reset controls, and `/api/validate` with structural, color-count, and front/top
  adjacency diagnostics in Chinese.
- Verification: `(cd tmp/cube && bash scripts/verify.sh)` passed 45 web tests, lint, typecheck,
  production build, 5 API tests, Ruff, and mypy. Root verification passed 482 tests, Ruff, mypy,
  `uv lock --check`, and `git diff --check`.
- Open scope: actual Three.js 3D interaction, authoritative reachability validation, solver
  jobs/SSE/cancellation, orientation-aware formula playback, Docker Compose, and Playwright
  acceptance remain unimplemented and are not claimed complete.

## Responses API adapter evidence (2026-08-11 Asia/Shanghai)

- User request: support the OpenAI Responses API in addition to the existing synchronous and
  streamed Chat Completions adapters.
- Design revision: `docs/superpowers/specs/2026-08-11-responses-api-llm-design.md`; plan:
  `docs/superpowers/plans/2026-08-11-responses-api-llm.md`.
- TDD RED: collecting the new adapter test failed with the expected missing
  `coding613.adapters.llm.responses` module. The streaming test then failed with the expected
  missing `complete_stream` method before its implementation.
- GREEN: `uv run pytest tests/adapters/llm/test_responses.py tests/adapters/llm/test_credentialed.py
  tests/application/test_composition.py tests/config/test_config.py -q` passed 60 tests; the
  complete offline suite passed 495 tests with 253 existing pytest-asyncio deprecation warnings.
- Implementation: `[llm].api` selects `chat_completions` (default) or `responses`; Responses maps
  flat function tools, output items, streaming deltas, `finish`, normalized usage, and provider
  IDs while preserving the owned loop and `store=false` state boundary.
- Static verification: Ruff, mypy, `uv lock --check`, and `git diff --check` passed. Independent
  `(cd tmp/cube && bash scripts/verify.sh)` passed 46 Web tests, 5 API tests, lint, typecheck,
  build, Ruff, and mypy.

## Context/tool-use forensic follow-up (2026-08-11 04:02 Asia/Shanghai)

- Status: root harness compatibility repairs are verified; the target Cube product remains in
  progress and is not claimed complete.
- Evidence: direct Responses SDK probing with the configured DeepSeek endpoint produced a tool
  call only after 1,800 reasoning tokens in a short request. The target worker initially used a
  1,536-token default and later generated ordinary Git patches that the executor rejected as
  unsupported metadata. Persisted run events show model actions, invalid patch errors, and
  repeated no-action retries; this rules out a zero-context explanation.
- Root changes: default `llm.max_output_tokens` is now 8192 (RED/GREEN config test); patch parsing
  accepts only the harmless `diff --git`/`index` wrapper metadata and can recover a uniquely
  matching stale hunk offset (both RED/GREEN tested). Existing path, ambiguity, and safety
  checks remain authoritative.
- Verification: `uv run pytest tests -q` passed 500; Ruff, mypy, and `git diff --check` passed.
  Fresh target `bash scripts/verify.sh` passed 61 Web tests, 8 API tests, lint, typecheck, build,
  Ruff, and mypy at 04:01. Target persistence remains a bounded interim implementation; the
  complete Three.js/solver/Compose/Playwright product is still open.

## Context budget and Three.js progress (2026-08-11 04:44 CST)

- The persisted worker trace proved the 8192 output cap was consumed entirely by reasoning on
  complex edits; the model had the task, target reads, and repair prompts. The root config now
  defaults Responses/Chat runs to `max_output_tokens = 32768`, with a focused RED/GREEN config
  test and README update.
- Governed workers installed Three.js and types, recorded the canvas RED test, and delivered a
  dynamic Three.js canvas for 2x2–7x7 with pointer orbit and a transparent SVG semantic fallback.
  One worker regression (`state.faces`, fixed order, missing default export) was caught by target
  validation and repaired by a later worker.
- Fresh `(cd tmp/cube && bash scripts/verify.sh)` at 04:44 passed 62 Web tests, 8 API tests,
  ESLint, TypeScript, Vite build, Ruff, and mypy. This closes only the viewport slice; real
  reachability/solver jobs, formula playback, Compose/Nginx, and Playwright acceptance remain.
- Root post-change gate at 04:45 passed 503 offline tests, Ruff, mypy, and `git diff --check`.

## Working-tree TUI Configuration Repair (2026-08-11)

- Status: complete in the existing uncommitted working tree; no commit was created.
- Scope: actionable undeclared-validation errors, declared-command tool guidance, repository-mode
  inheritance in the TUI entrypoint, and validated `/config` TUI show/set commands with atomic
  `harness.toml` persistence and runtime reload for future runs.
- Verification: `uv run pytest -q --ignore=tmp` passed 517 tests; `uv run ruff check .` and
  `uv run mypy src` passed; installed `613-coding config check --repo tmp/cube` exited 0.
- User intervention/deviation: user explicitly requested no Superpowers skills; implementation
  followed the existing application boundaries without invoking those skills.

## Working-tree TUI Discoverability Hints (2026-08-11 19:09 CST)

- Status: complete in the existing uncommitted working tree; no commit was created.
- Scope: deterministic slash-command prefix matching, Tab/↑/↓ cycling, live candidate hints,
  persistent keyboard/approval guidance, and `/help` discovery text.
- TDD: the initial focused collection failed because the new `CommandHints` widget did not yet
  exist; focused `tests/tui/test_commands.py tests/tui/test_app.py` then passed 47 tests.
- Verification: `uv run pytest -q --ignore=tmp` → 521 passed; `uv run ruff check .`,
  `uv run mypy src`, and `git diff --check` → passed.
- Documentation: README and `docs/development.md` now document `/` filtering, Tab completion,
  arrow cycling, history fallback, `/help`, and `//` literal-slash prompts.
- Boundary: no target `tmp/cube` source was modified by this slice; the product remains in
  progress and is not claimed complete.
- Final 19:11 CST verification after the narrow-terminal hint layout polish remained green:
  521 tests, Ruff, mypy, and `git diff --check`.

## Working-tree TUI Dependency/Startup Repair (2026-08-11 19:23 CST)

- Status: complete in the existing uncommitted working tree; no commit was created.
- Scope: eliminate the Markdown-link `bad marshal data` crash and ensure the installed global
  `613-coding` uses the current Responses-aware configuration model.
- TDD: the focused Markdown-link test was RED under Rich 15; it passed after pinning Rich below
  14.2, which is the first release family that changed style metadata from marshal to pickle.
- Verification: `uv run pytest -q --ignore=tmp` → 522 passed; Ruff, mypy, `uv lock --check`, and
  `git diff --check` → passed. Installed-tool probes confirmed Rich 14.1.0, valid `tmp/cube`
  configuration, and successful Markdown-link rendering.
- Documentation: README and `docs/deployment.md` explain `uv tool install --force .` for stale
  global installations and `uv run 613-coding` for the live checkout.
- Boundary: no `tmp/cube` product source was changed; the product remains in progress.

## Working-tree TUI Tool Output Preview (2026-08-11 19:43 CST)

- Status: complete in the existing uncommitted working tree; no commit was created.
- Scope: collapse large tool-result output to a redacted preview and add `Ctrl+T` to expand or
  collapse the latest expandable result.
- TDD: focused renderer/app tests were RED before `DetailMessage` gained expandable state;
  TUI tests then passed 64 cases.
- Verification: `uv run pytest -q --ignore=tmp` → 524 passed; Ruff, mypy, and
  `git diff --check` → passed.
- Documentation: README and `docs/development.md` document the preview and shortcut.
- Boundary: the model-facing tool result and its existing redaction/output cap are unchanged;
  only the TUI presentation is collapsed.
- Distribution refresh at 19:45 CST verified the global Python 3.12 `613-coding` executable has
  the new binding and preview/expand behavior.

## Working-tree TUI No-action and Composer Display Repair (2026-08-11 19:55 CST)

- Status: verified locally; responsible actor: controller.
- Change: repeated text-only provider responses now receive an explicit action-repair prompt and
  stop after one repair turn with deterministic `no_progress`; assistant drafts are replaced per
  model turn; the composer hover tooltip was removed and bottom-row geometry is covered at
  60x20/80x24 terminal sizes.
- TDD: the new loop test first reproduced `provider_error` after the fake provider ran out of
  responses (the previous budget-loop behavior); the UI test first observed the unwanted tooltip.
- Fresh verification: `uv run pytest -q --ignore=tmp` → 528 passed; Ruff, mypy, `uv lock --check`,
  and `git diff --check` → passed. Global refresh used
  `uv tool install --force --reinstall --no-cache .`; installed config and model-state probes
  passed for `tmp/cube` (final refresh/probe at 20:00 CST).
- Delivery boundary: no target `tmp/cube` source, credentials, provider request, remote push, or
  deployment was used; the complete cube-solver product remains in progress.

## Working-tree Responses Tool Stream Repair (2026-08-11 20:18 CST)

- Status: verified locally; responsible actor: controller.
- Scope: repair DeepSeek Responses streaming function-call assembly and prevent repeated provider
  protocol failures from consuming the entire model-call budget without a useful error.
- Evidence: target SQLite for the reported runs showed 30 provider-boundary response errors and no
  tool action. A direct stream reproduction showed `name` present on `output_item.added` but null
  on `function_call_arguments.done`; the parser now retains the earlier name. The loop tracks a
  persisted provider-error streak and stops after two retryable failures with `provider_error`.
- TDD: the null-name stream case and repeated-provider-error budget test were RED before their
  respective implementations and pass now.
- Fresh verification: `uv run pytest -q --ignore=tmp` → 529 passed; Ruff, mypy, `uv lock --check`,
  and `git diff --check` → passed. The global uv tool was force-reinstalled from this checkout;
  a live provider probe parsed `read_file`, and a bounded CLI smoke run recorded successful tool
  completions before its intentional three-call budget ended.
- Delivery boundary: no target source, credentials, remote push, or deployment was changed; the
  complete cube-solver product remains in progress. Restart an already-running TUI process before
  testing so it loads the refreshed package.

## Working-tree apply_patch Conflict Repair (2026-08-11 20:28 CST)

- Status: verified locally; responsible actor: controller.
- Scope: preserve actionable `PatchConflictError` details in tool results and give the next model
  call deterministic instructions to re-read and regenerate a stale patch.
- TDD: direct repository and context regressions were RED before implementation and pass now.
- Fresh verification: `uv run pytest -q --ignore=tmp` → 531 passed; Ruff, mypy, `uv lock --check`,
  and `git diff --check` → passed. Global `613-coding` was force-reinstalled and its config/CLI
  probes passed.
- Safety boundary: no automatic overwrite or fuzzy application is introduced. The exact conflict
  remains rejected; only a fresh patch based on current file content can proceed.

## Working-tree Tool Output and Validation Repair (2026-08-11 20:46 CST)

- Status: verified locally; responsible actor: controller.
- Scope: preserve large tool results until the TUI preview/`Ctrl+T` boundary, make declared
  validation argv unambiguous, and stop requiring validation for read-only conversations.
- Root cause evidence: the loop previously capped progress text at 8,000 characters; the tool
  description used shell-formatted argv; and `finish` treated every run as requiring validation.
  Automatic validation triggers already exclude read-only tools.
- TDD: regressions for output preservation, JSON argv guidance, and read-only completion were
  added before the implementation and are green.
- Fresh verification: `uv run pytest -q --ignore=tmp` → 533 passed; Ruff, mypy, lock, and diff
  checks passed. Global `613-coding` was force-reinstalled; the `tmp/cube` config check and CLI
  help probes passed.
- Safety boundary: output remains redacted and bounded at 1 MiB; changed repositories still need
  fresh passing validation before `finish`; no target source, credentials, remote push, or deploy
  was changed.

## Working-tree Legacy Validation argv Compatibility (2026-08-11 20:52 CST)

- Status: verified locally; responsible actor: controller.
- Change: a one-element legacy shell-rendered validation argument is accepted only when
  `shlex.split` produces an exact policy-declared argv tuple; subprocess execution remains
  `shell=False`.
- TDD/verification: the focused regression was RED before implementation and GREEN afterward;
  final `uv run pytest -q --ignore=tmp` → 534 passed, with Ruff, mypy, lock, and diff checks green.
  The refreshed global executable passed the `tmp/cube` config check and CLI help probe.
- Boundary: no arbitrary shell parsing, policy bypass, credential access, target source edit,
  remote push, or deployment was performed.

## Working-tree Codex-aligned Provider Retry Window (2026-08-11 21:32 CST)

- Status: implemented and verified in the current dirty worktree; no Superpowers skills were
  invoked, and unrelated user changes remain preserved.
- Scope: align transient provider retry handling with Codex's visible five-retry reconnect
  window while keeping the harness loop, budgets, persistence, and policy authoritative.
- TDD RED: `test_repeated_retryable_provider_errors_stop_before_model_budget` was changed to
  assert the new bounded retry behavior and failed against the previous two-attempt
  implementation.
- Codex parity clarification: the current Codex source sets `DEFAULT_STREAM_MAX_RETRIES = 5`;
  this is five retries after the initial call, so the harness allows six total requests and
  terminates on the sixth failure. `_MAX_PROVIDER_RETRIES = 5` records retry counts in feedback.
  OpenAI SDK 4xx request errors (except authentication and rate limits) map to non-retryable
  `ProviderRequestError` so invalid payloads fail fast.
- Verification evidence: focused loop/adapter tests passed 85; `uv run pytest -q --ignore=tmp`
  passed 538 tests; `uv run ruff check src tests`, `uv run mypy src`, `uv lock --check`, and
  `git diff --check` passed. README and `docs/development.md` document the behavior.
- Delivery boundary: no real provider request, credential access, target `tmp/cube` source edit,
  remote push, deployment, or destructive Git operation was performed. Start a fresh run after
  restarting an installed TUI process to exercise the new code.

## Working-tree Retry Semantics Correction (2026-08-11 21:40 CST)

- Codex source verification: `DEFAULT_STREAM_MAX_RETRIES = 5` is a retry count after the initial
  Responses stream request; Codex displays `1/5` through `5/5`. The implementation therefore uses
  `_MAX_PROVIDER_RETRIES = 5`, allowing six total provider calls and stopping on the sixth failure.
- TDD: the six-call regression was RED against the intermediate five-total implementation and is
  GREEN after the semantic correction.
- Final verification: `uv run pytest -q --ignore=tmp` → 538 passed; Ruff, mypy, `uv lock --check`,
  and `git diff --check` passed. The global uv tool was force-reinstalled from this checkout;
  CLI help and the `tmp/cube` configuration probe passed.

## Working-tree Context/Validation/TUI/Budget Follow-up (2026-08-11 22:10 CST)

- Status: implemented and offline verified in the current dirty worktree; no Superpowers skills
  were invoked and unrelated user changes remain preserved.
- Scope: stabilize the Responses prompt prefix, defer repository validation to an explicit
  task-boundary request, make validation/tool output line-bounded and expandable without large
  `Syntax` backgrounds, and add model-selected resource profiles.
- TDD RED/GREEN: new regressions covered stable task-prefix/cache hash, one validation after a
  multi-write batch, `set_task_budget` propagation to the next provider request, and 240-line
  validation rendering. All focused tests passed after implementation.
- Verification evidence: `uv run pytest -q --ignore=tmp` → 542 passed with 316 existing warnings;
  `uv run ruff check .` and `uv run mypy src` passed. No provider request, credential access,
  target `tmp/cube` source edit, remote push, deployment, or destructive Git operation occurred.

### Final verification (2026-08-11 22:22 CST)

- `uv run pytest -q --ignore=tmp`: 542 passed, 316 existing warnings.
- `uv run ruff check .`, `uv run mypy src`, `uv lock --check`, and `git diff --check`: passed.
- Global package refreshed with `uv tool install --force --reinstall --no-cache .`; CLI help and
  the `tmp/cube` configuration probe passed.

## TUI Preview Limits (2026-08-11 22:24 CST)

- Scope: reduce the default tool-result preview to 200 characters and validation preview to 10
  lines while retaining expandable output and the safety cap.
- Verification: focused renderer tests 8 passed; full offline suite 542 passed with 316 existing
  warnings; Ruff, mypy, lock, and diff checks passed. The global CLI was rebuilt and its help/config
  probes passed.

## Context-Controlled Agent Conversation (2026-08-11 23:09 CST)

- Status: implemented and verified locally; responsible actor: `/root`.
- Scope: remove enforced per-agent-turn stopping, keep context compaction as the conversation
  boundary, prevent repeated `set_task_budget` calls, and return a finish summary when a provider
  supplies no final text content.
- Root cause: a completed historical run stored the user-facing answer only in `FinishAction.summary`
  while the transcript selected the last non-empty planning content; the model also saw the budget
  tool after profile selection and repeatedly invoked it.
- TDD/verification: focused regressions were RED before implementation and GREEN afterward;
  `uv run pytest -q --ignore=tmp` → 543 passed with 316 warnings; Ruff, mypy, and diff checks passed.
  Editable global `613-coding` install and the `tmp/cube` config probe confirm the direct CLI uses
  the updated source.
- Safety boundary: legacy `per_agent_turns` remains accepted for compatibility but is informational;
  finite total model-call, wall-time, and provider-cost limits remain available for unattended safety.
  No target cube source, credentials, provider, remote repository, or deployment was changed.

### Final-answer precedence follow-up (2026-08-11 23:15 CST)

- A RED regression demonstrated that an earlier planning message could still mask a later accepted
  `finish.summary` when the final response content was empty.
- The transcript now selects the summary attached to the completed iteration before considering
  earlier model text. Focused and full verification remain green: 543 tests passed; Ruff, mypy, and
  diff checks passed; the editable CLI config probe reports `per_agent_turns:unbounded`.

## LLM Context Window Configuration (2026-08-11 23:36 CST)

- Status: implemented and verified locally; responsible actor: `/root`.
- Scope: make the dynamic context-compaction window configurable under `[llm]` as
  `context_window_chars`, while preserving the 48,000-character default and live TUI reload.
- TDD/verification: RED configuration tests were observed before implementation; composition and
  configuration-service regressions are green. Full offline suite: 547 passed with 316 warnings;
  Ruff, mypy, lock, and diff checks passed. Direct CLI check reports `context_window_chars=48000`.
- Safety boundary: the value is positive and capped at 4,000,000 characters; no tokenizer or
  provider request is required. No target cube source/config, credentials, remote repository, or
  deployment was changed.

## Provider model catalog, Anthropic SDK, and slash menus (2026-08-12)

- Status: implemented and offline verified in the current worktree; responsible actor: `/root`.
- Scope: add per-provider model aliases with reasoning/output/context/streaming overrides, model
  selection APIs and CLI commands, official Anthropic Messages SDK transport, and selectable TUI
  menus for `/config`, `/provider`, and `/model`.
- Evidence: `ModelConfig.effective`, `UserConfigurationService.models/select_model/upsert_model`,
  `src/coding613/adapters/llm/anthropic.py`, `CredentialedAnthropicLLM`, composition injection,
  `ConfigMenu`, and tests under `tests/adapters/llm/test_anthropic.py`,
  `tests/application/test_user_configuration.py`, `tests/application/test_composition.py`,
  `tests/cli/test_providers.py`, and `tests/tui/test_app.py`.
- Verification: `uv run pytest -q --ignore=tmp` -> 568 passed with 334 warnings; Ruff, mypy,
  `uv lock --check`, and `git diff --check` passed. No remote/provider smoke was run.
- Final installed-CLI gate at 2026-08-12 00:43:06: `uv tool install --force --editable .`, provider
  and model management help, redacted provider listing, and `config check --repo tmp/cube` passed;
  the final suite is 570 passed with 334 warnings plus Ruff, mypy, lock, and diff checks.
- Follow-up at 00:45:33 added explicit low/medium/high reasoning switching for each model alias via
  the service, CLI, and TUI menus; focused service/CLI/TUI tests passed (37 tests). Final full gate
  at 00:46:32 passed 571 tests with 334 warnings plus Ruff, mypy, lock, and diff checks. The final
  00:50:51 gate also verifies Chat Completions forwards non-default reasoning and passes 573 tests.

## Default resource and reasoning-level update (2026-08-12 01:13 Asia/Shanghai)

- Status: implemented and offline verified locally; responsible actor: `/root`.
- Changes: default context compaction window `256000` characters; internal tool-progress cap
  `10000000` characters; resource profiles `standard=16384` and `complex=128000` with `simple`
  removed; provider/model reasoning levels are arbitrary validated non-empty strings, with TUI
  suggestions for common levels and direct CLI/config support for provider-specific values.
- Evidence: `tests/application/test_resources.py`, config defaults and model-catalog tests, loop
  output-cap regression, OpenAI-compatible/Anthropic adapter regressions, and provider CLI tests.
- Verification: `uv run pytest -q --ignore=tmp` -> 582 passed with 334 warnings; Ruff, mypy,
  `uv lock --check`, and `git diff --check` passed. `uv tool install --force --editable .`, CLI
  help, and the `tmp/cube` config probe passed.

## TUI provider management — complete (2026-08-12 01:36 Asia/Shanghai)

- Scope: make `/provider` a user-wide provider manager with add/edit/delete/use operations and
  keyring-backed API-key set/clear actions.
- Evidence: `ProviderEditorScreen` and `ProviderKeyScreen` keep secrets out of the log; the menu
  requires confirmation for profile deletion and key clearing; profile metadata is reloaded into
  the runtime after saves/removals; service removal selects a deterministic replacement without
  implicitly deleting a credential.
- Tests: parser coverage includes add/edit/remove/delete/key/clear-key; TUI coverage includes the
  management menu, hidden-key add form, safe defaults, and delete confirmation; user-service coverage
  verifies active-provider replacement and explicit credential clearing.
- Verification: `uv run pytest -q --ignore=tmp` -> 595 passed with 370 warnings; Ruff, mypy, lock,
  and diff checks passed.
- Commit: `280817f` (`feat: add tui provider management`).

## TUI provider menu worker fix — complete (2026-08-12 01:49 Asia/Shanghai)

- Scope: make provider management actions launched from `ConfigMenu` execute in a Textual worker so
  modal add/edit/key screens can safely await dismissal.
- Root cause/evidence: direct message-pump dispatch caused `push_screen_wait` to raise after pushing
  an unawaited screen; the new menu-selection regression failed to persist a provider before the
  handler was moved to `run_worker(..., group="config-menu")`.
- Verification: `uv run pytest -q --ignore=tmp` -> 596 passed with 379 warnings; Ruff, mypy, and
  diff checks passed.
- Commit: `698e0c0` (`fix: run provider menu actions in worker`).

## OpenAI tools and patch-conflict recovery — complete (2026-08-12 02:16 Asia/Shanghai)

- Scope: add a governed local `run_command` tool, Responses-hosted tool definitions, provider
  configuration/CLI/TUI opt-in, and actionable recovery evidence for stale `apply_patch` hunks.
- TDD: RED focused tests covered the missing tool catalog, missing hosted transport, and missing
  conflict guidance; GREEN tests cover local execution, payload forwarding, metadata, configuration
  persistence, and existing loop/provider behavior.
- Verification: `uv run pytest tests -q` passed 601 tests with 379 warnings; `uv run ruff check src
  tests`, `uv run mypy src`, and `git diff --check` passed. The full repository default includes
  untracked `tmp/cube` tests with separate FastAPI dependencies, so the maintained offline gate is
  the explicit `tests/` path.
- Commit: `de72048` (`feat: add governed shell and responses tools`).

## Repeated patch-conflict recovery — complete (2026-08-12 02:25 Asia/Shanghai)

- Scope: stop identical stale `apply_patch` calls from producing an endless stream of TUI errors;
  preserve actionable guidance for persisted conflict events.
- Behavior: after the first conflict the next model context explicitly requires a fresh read and
  different patch; a second identical conflict terminates the run with deterministic
  `no_progress` feedback. A different patch or an intervening read is still allowed to continue.
- Verification: `uv run pytest tests -q` -> 604 passed with 379 warnings; `uv run ruff check src
  tests`, `uv run mypy src`, and `git diff --check` passed.
- Commit: `45b3ef3` (`fix: bound repeated patch conflicts`).

## Expanded Responses tool catalog and client continuation — complete (2026-08-12 02:58 Asia/Shanghai)

- Status: implemented and offline verified locally; responsible actor: `/root`.
- Scope: expose the current OpenAI Responses tool catalog through provider configuration,
  including web search/preview, file search, code interpreter, image generation, MCP, tool
  search, programmatic calling, shell/local-shell, apply-patch, computer, custom, and namespace.
  Shell and patch calls remain harness-governed: provider items become validated local actions,
  policy/approval is applied, and typed output items are reconstructed for the next stateless
  Responses request. Unsupported interactive adapters return an explicit deterministic failure.
- Additional safety: Responses shell command strings are parsed with `shlex.split` into argv
  without shell interpolation; continuation output is bounded by the configured context window.
- TDD/verification: focused RED tests covered the missing catalog and continuation behavior;
  final `uv run pytest tests -q` -> 618 passed with 379 warnings. `uv run ruff check src tests`,
  `uv run mypy src`, and `git diff --check` passed.
- Commit: `6ed2e58` (`feat: expand responses tool catalog and continuation`).

## Remove unsupported Responses tools — complete (2026-08-12 10:16 Asia/Shanghai)

- Status: implemented and offline verified locally; responsible actor: `/root`.
- Scope: remove `tool_search`, computer tools, custom tools, namespaces, and programmatic tool
  calling because this installation did not provide their complete execution and continuation
  adapters. The configuration catalog, Responses parser, local registry, policy, context logic,
  tests, and documentation now expose only end-to-end supported tools.
- Retained tools: web search/preview, file search, code interpreter, image generation, remote MCP,
  governed shell/local-shell, and governed apply-patch.
- Verification: `uv run pytest tests -q` -> 620 passed with 379 warnings; `uv run ruff check src
  tests`, `uv run mypy src`, and `git diff --check` passed.
- Commit: `16401b1` (`fix: remove unsupported responses tools`).

## TUI nested Static rendering fix — complete (2026-08-12 10:32 Asia/Shanghai)

- Status: implemented and offline verified locally; responsible actor: `/root`.
- Scope: fix the validation-progress rendering crash caused by passing a `Static` widget as the
  content of another `Static`-based `DetailMessage`.
- Regression: `test_tui_validation_started_renders_without_nested_static_content` reproduces the
  `VisualError` before the fix and verifies the mounted detail remains renderable afterward.
- Verification: `uv run pytest tests/tui -q` -> 88 passed; `uv run pytest tests -q` -> 621 passed
  with 388 warnings; Ruff, mypy, and `git diff --check` passed.
- Commit: `34a2986` (`fix: avoid nested static validation content`).

## Stale apply_patch variant recovery — complete (2026-08-12 11:30 Asia/Shanghai)

- Status: implemented and offline verified locally; responsible actor: `/root`.
- Scope: prevent different stale patch variants for one file from repeatedly reaching the patch
  parser, while preserving strict context matching and safe recovery.
- Implementation: affected paths are extracted from unified/Codex/Responses patch shapes; conflict
  evidence is shared per path until all affected paths are successfully re-read or changed by a
  successful write; repair feedback records paths; the repair prompt requires fresh reads; and
  conflict guidance returns bounded current-file content (8,000 characters).
- Regression evidence: tests cover stale variants, exact conflicts, target re-read reset, multi-file
  refresh, and current content beyond the former ten-line guidance window.
- Verification: `uv run pytest tests -q` -> 625 passed with 388 warnings; Ruff, mypy, and
  `git diff --check` passed.
- Commit: `00d9e9e` (`fix: enforce deterministic patch recovery`), together with the persisted
  dispatch barrier and its final review repair.

## TUI session context isolation — complete (2026-08-12 12:05 Asia/Shanghai)

- Status: implemented and offline verified locally; responsible actor: `/root`.
- Scope: `/resume` without an argument opens a selectable session menu; explicit `latest`/UUID
  selectors remain direct. `/clear` now requires an explicit new/switch/cancel choice. Session
  labels include redacted title, short ID, latest run status/task, and update time.
- Isolation: exact-session snapshots remain authoritative; switching/new submissions replace the
  progress and event queues, cancel the previous token, clear TUI transcript/approval/tool caches,
  reject stale run progress, close completed streams after their first drain, and use a generation
  guard against late worker state writes. Context builder regression coverage confirms another
  session's transcript is not added to an LLM prompt.
- Evidence: `docs/superpowers/plans/2026-08-12-tui-session-context-plan.md`,
  `tests/tui/test_commands.py`, `tests/tui/test_controller.py`, `tests/tui/test_app.py`, and
  `tests/application/test_context.py`.
- Verification: `uv run pytest tests -q` -> 632 passed with 442 warnings; TUI suite -> 94 passed;
  Ruff, mypy, and `git diff --check` passed. Existing unrelated worktree changes were preserved.
- Commit: `83f65b0` (`feat: isolate tui conversation sessions`).

## Deterministic apply_patch recovery barrier — complete (2026-08-14 13:02 Asia/Shanghai)

- Status: implemented, review-repaired, and offline verified locally; responsible actor: `/root`.
- Scope: make strict patch conflicts enter an explicit persisted read-repair state. Every affected
  path must be successfully read in a separate response before any write, validation, approval,
  finish, or mixed response can dispatch. The barrier survives `LoopSession` persistence and keeps
  the existing repeated-conflict `no_progress` stop.
- Evidence: design `docs/superpowers/specs/2026-08-12-apply-patch-recovery-design.md`, plan
  `docs/superpowers/plans/2026-08-12-apply-patch-recovery-plan.md`, and regressions in
  `tests/application/test_loop.py`, `tests/application/test_context.py`, and
  `tests/adapters/storage/test_sqlite.py`.
- Review repair: review found that `ContextAssembler._needs_patch_conflict_repair` stripped a
  repository path's leading `a/` twice. A focused RED reproduced `a/value.txt` clearing the
  execution barrier while stale repair guidance remained in context; GREEN now preserves real
  `a/` and `b/` repository directories while normalizing patch headers separately.
- Verification: the final patch-recovery selection passed 129 tests; the maintained offline suite
  passed 681 tests; deterministic demos passed 3 tests; Ruff, mypy across 110 source files,
  `uv lock --check`, documentation tests, and `git diff --check` passed.
- Commit: `00d9e9e` (`fix: enforce deterministic patch recovery`).

## Dangerous bypass permission mode — implementation planned (2026-08-13 09:58 Asia/Shanghai)

- Status: design and detailed plan approved; implementation approach selection is pending.
- Design: `docs/superpowers/specs/2026-08-13-dangerous-bypass-permission-design.md` (`8df9151`).
- Plan: `docs/superpowers/plans/2026-08-13-dangerous-bypass-permission.md` (`e7206d6`).
- Scope: add a first-class `bypass` value and dangerous CLI alias, central `ASK -> ALLOW`
  conversion with every `DENY` preserved, AgentLoop no-approval evidence, persistent/output
  contracts, TUI warnings, offline demo, full verification, and two-stage review.
- Verification: planning-only self-review and `git diff --cached --check` passed; no implementation
  or runtime test result is claimed yet.
## Dangerous bypass permission mode (2026-08-13)

- Approved design: `docs/superpowers/specs/2026-08-13-dangerous-bypass-permission-design.md`.
- Execution plan: `docs/superpowers/plans/2026-08-13-dangerous-bypass-permission.md`.
- Task 1 — complete. Added the canonical mode, config/SQLite persistence, root CLI selectors,
  deterministic conflict rejection, and text/JSON/stream reporting. RED: 8 failed, 74 passed.
  GREEN: 82 passed; scoped Ruff, CLI help, and diff checks passed. Commit: `7c8f333`.
- Task 2 — complete. Centralized bypass conversion of policy `ASK` to `ALLOW` while preserving
  every deterministic `DENY`, invocation filter, pending approval, and sandbox boundary. RED: 6
  failed, 105 passed. GREEN: 111 passed; scoped Ruff, mypy, and diff checks passed. Commit:
  `451fa7e`.
- Task 3 — complete. Added TUI selection, menu integration, and a shared conspicuous warning for
  footer/status/permission/config views. RED: 5 failed, 77 passed. GREEN: 82 passed; scoped Ruff,
  mypy, and diff checks passed. Commit: `5935178`.
- Task 4 — complete. Extended the deterministic demo and current operator/specification docs.
  RED: 2 failed, 6 passed. GREEN: 8 passed; scoped Ruff, mypy, and diff checks passed. Commit:
  `dde5383`.
- Task 5 - complete on the isolated branch. Final bypass selection: 282 passed. Final maintained
  offline suite after lifecycle repair: 655 passed. Ruff, mypy across 110 source files,
  `uv lock --check`, `git diff --check`, and CLI help passed. The restricted sandbox hung in
  `lancedb.connect()`; faulthandler captured the boundary and the same offline tests passed outside
  that restriction without network or credentials. The teardown fix `e54a31c` passed four focused
  lifecycle/restore regressions and a scoped re-review. Final spec-compliance and code-quality
  reviews reported no Critical, Important, or Minor findings. Delivery-record commits: `c946b30`
  and `04d2d49`. The fresh branch gate at `04d2d49` repeated the 655-test offline suite and all
  static/documentation/CLI checks successfully.
- Local integration — complete. The user selected option 1 and `main` fast-forwarded from
  `e7206d6` to `9aac5e5`. Existing uncommitted patch-recovery and TUI-session work was restored via
  a stash-backed three-way merge without staging or committing it. The combined maintained suite
  passed 680 tests; the conflict-sensitive subset passed 176; Ruff, mypy, docs, CLI help, and diff
  checks passed. GitHub push and remote CI remain pending.
- Restored-work completion — complete. Deterministic patch recovery was review-repaired and
  committed as `00d9e9e`; TUI conversation isolation was committed as `83f65b0`. The exact local
  tip passed 681 maintained tests, 129 patch-recovery tests, 99 TUI tests, and 3 deterministic demo
  tests, plus Ruff, mypy, lock, documentation, and diff checks. GitHub push and remote CI remain
  pending.
- GitHub publication — complete for commit `2e8c3c0`. Push run
  [31771935622](https://github.com/Insouciant21/613-coding/actions/runs/31771935622)
  passed `unit-test`, `quality`, `demo`, and `package-and-artifacts`; the artifact
  `613-coding-2e8c3c0268304282e0ea8084785e0f820c8d6064` was uploaded. The tag-only `release` job was
  correctly skipped because no release tag was pushed at that gate.
- GitHub Release — complete. Annotated tag `v0.1.0` points to `60cf272`; the published release is
  [613 Coding v0.1.0](https://github.com/Insouciant21/613-coding/releases/tag/v0.1.0) with the Linux
  executable, wheel, sdist, and checksums. Because the tag target contains `[skip ci]`, no tag
  workflow started; the release recovered by reusing and re-verifying the successful
  `package-and-artifacts` output from run `31771935622`. No tag/history rewrite occurred.
- Submission metadata remains incomplete: the GitHub repository is private and
  `submission.jsonc` still needs the student's real ID and name. The release URL is now available.
