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
| `docs/superpowers/plans/2026-08-08-613-coding-delivery.md` | CLI, FastAPI/WebUI, CI, package, Docker demo, records | Core services; sandbox for demo | complete through Docker smoke repair `774c07a`; real provider remains injectable |
| `docs/superpowers/plans/2026-08-09-613-coding-package-rename.md` | Strict distribution/import/runtime/documentation rename | completed Tasks 1-3 | complete through reviewed CI and SSH deployment at `eefee2d` |

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

- Status: implementation and review repair complete through `80f6c85` and `da9cda5`; scoped re-review pending.
- Scope: stable goal-directed worker context, configured permission-mode inheritance, repository file deletion, policy/role/progress integration, and symlink-safe unlink semantics.
- Verification: real-provider Cube foundation run `46ec4663-1c43-41e7-95d7-ce31f3b7d489` completed successfully; fresh harness verification passed 258 tests, Ruff, mypy across 82 source files, lock check, and diff check.
- Evidence: `AGENT_LOG.md` entry `2026-08-09 22:20:00 Asia/Shanghai`; target operation details remain append-only in `tmp/cube/AGENT_LOG.md`.

## CI and Deployment Manifest Evidence

- Status: repository configuration complete in `0d8d63a`; Docker source-copy order fixed, GitLab/GitHub CI container jobs added, and `render.yaml` declares an operator-controlled Web Service.
- Verification: distribution-focused suite passed 7; Docker build attempt failed at external Docker Hub token retrieval, so no Docker or deployment success is claimed.
- Boundary: remote CI final status and public URL require a configured forge/deployment account.

Every task must end with a focused test result and commit hash. `DELIVERY_STATUS.md` must link the evidence before a task is marked complete.

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
