# 613 Coding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build 613 Coding as a self-owned Python Coding Agent Harness with an objective feedback loop, container-isolated workers, Supervisor orchestration, secure memory, and CLI/WebUI distribution.

**Architecture:** A domain/application core owns the agent loop, tool protocol, governance, feedback classification, and run state. SQLite is authoritative for structured state and memory text; LanceDB is a rebuildable vector index. Sandbox and multi-agent adapters consume explicit ports, while CLI, FastAPI, and the demonstration WebUI call the same application services.

**Tech Stack:** Python 3.12+, `uv`, Pydantic, pytest, Ruff, mypy, FastAPI/Uvicorn, Typer, SQLite, LanceDB, `keyring`, Docker Engine API, HTTPX for OpenAI-compatible providers.

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
- No implementation code is written until SPEC/PLAN review and the different-agent cold-start gate pass.

## Plan Registry And Dependencies

| Plan | Scope | Depends on | Status |
| --- | --- | --- | --- |
| `docs/superpowers/plans/2026-08-08-613-coding-core.md` | Domain contracts, tools, feedback, memory, credentials, agent loop | Cold-start gate | complete after final-review repair at `9af4f03` |
| `docs/superpowers/plans/2026-08-08-613-coding-sandbox.md` | Task workspaces and Docker runtime isolation | Core ports and artifacts | complete through `fb1c222` |
| `docs/superpowers/plans/2026-08-08-613-coding-multi-agent.md` | Task graph, workers, Supervisor, artifact integration | Core loop, sandbox | complete through `376fd41` |
| `docs/superpowers/plans/2026-08-08-613-coding-delivery.md` | CLI, FastAPI/WebUI, CI, package, Docker demo, records | Core services; sandbox for demo | complete through runtime-composition repair; local bundle is wired, real provider remains injectable |

The implementation critical path is `CORE → SANDBOX → MULTI_AGENT → DELIVERY`. Core storage and domain work can proceed before sandbox; delivery documentation and test harness scaffolding can proceed after core interfaces are stable.

## Phase Gates

- [x] Brainstorming design approved and committed.
- [x] Root specification and process records created for review.
- [x] Specification, root plan, four subsystem plans, and initial evidence records committed as `a2909c7`.
- [x] User reviewed `SPEC.md` and `PLAN.md` without requested changes and selected Subagent-Driven execution on 2026-08-08.
- [x] A different agent type cold-started `CORE-01` and `CORE-02` with only `SPEC.md` and `PLAN.md`, recorded the dependency-bootstrap ambiguity, and produced a report referenced by `SPEC_PROCESS.md`.
- [x] The cold-start findings were incorporated: standard-library package baseline, explicit dependency provisioning, air-gapped cache/wheelhouse requirement, and a `DEPENDENCY_PROVISIONING_BLOCKED` stop condition.
- [x] Bootstrap revision committed as `fc7bf53`.
- [ ] Each task receives spec-compliance review, code-quality review, fresh verification, a commit, and record updates.

## Task Index

Detailed task steps, file paths, interfaces, failing tests, and commit commands live in the four linked plans. The following IDs are the cross-plan tracking keys:

- `CORE-01` through `CORE-11`: package, domain, providers, storage, tools/policy, validation/feedback, memory, agent loop, credentials, and deterministic demo.
- `SANDBOX-01` through `SANDBOX-05`: sandbox contracts, workspace/artifacts, Docker lifecycle, security/resource policy, and integration evidence.
- `MULTI-01` through `MULTI-05`: task graph, worker runtime, Supervisor scheduling, artifact integration, and orchestration demo.
- `DELIVERY-01` through `DELIVERY-07`: CLI, API, WebUI, distribution, CI, documentation, and delivery-record automation.

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

Every task must end with a focused test result and commit hash. `DELIVERY_STATUS.md` must link the evidence before a task is marked complete.

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
