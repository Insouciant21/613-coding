# AGENT_LOG.md

Chronological evidence log for the 613 Coding project. Entries are appended after significant work; no entry is based only on model self-report.

## 2026-08-07

### Brainstorming and approved design

- Task: design 613 Coding.
- Skills: `using-superpowers`, `brainstorming`.
- Key context: course requirements in `docs/AI4SE_Final_Project_通用要求.md` and `docs/AI4SE_Final_Project_A_Coding_Agent_Harness(1).md`.
- Decisions: local task-driven coding assistant; Python/uv; feedback loop as main contribution; Claude Code-style tool/permission/context interaction; SQLite + LanceDB; Docker worker sandbox; Supervisor plus role-specific workers; package + Docker distribution.
- Human intervention: user selected each direction and expanded the scope to complete container execution and multi-agent orchestration while keeping feedback as the main contribution.
- Evidence: approved design at `docs/superpowers/specs/2026-08-07-613-coding-design.md`.

### Documentation commits

- `6ad0eec`: recorded initial design and `AGENTS.md`.
- `f51b8dd`: normalized the design file ending.
- `c4fd219`: made agent budgets configurable instead of imposing a fixed five-turn product limit.
- `ba03b70`: added automatic delivery-evidence recording requirements.

## 2026-08-08

### Specification and planning preparation

- Task: start the Superpowers implementation-plan phase.
- Skill: `writing-plans`.
- Verification: inspected current repository, approved design, `AGENTS.md`, and course delivery requirements; no implementation code exists yet.
- Human intervention: user explicitly requested beginning implementation planning.
- Current result: root `SPEC.md`, `SPEC_PROCESS.md`, this log, and `DELIVERY_STATUS.md` were created before detailed plans. Four plans were written: core feedback loop, container sandbox, multi-agent orchestration, and delivery interfaces/distribution. Cold-start validation remains pending and must precede implementation.
- Verification: reserved-marker scan returned no matches; plan task index contains 28 task nodes (`CORE-01..11`, `SANDBOX-01..05`, `MULTI-01..05`, `DELIVERY-01..07`); no implementation source files exist.
- Human intervention: the plan was split by subsystem because the approved spec contains three independent runtime areas plus delivery adapters.
- Commit: `a2909c7` (`docs: add 613 Coding implementation plans`).

### Subagent-driven cold-start setup

- Task: prepare the required unfamiliar-agent cold-start trial before implementation.
- Skills: `subagent-driven-development`, `using-git-worktrees`.
- Human intervention: user selected Subagent-Driven execution and requested no changes to the submitted specification or plans.
- Action: added `.worktrees/` to `.gitignore` before creating an isolated worktree, preserving the existing ignored documentation and scratch paths.
- Next evidence: a different-model, no-history agent will receive only `SPEC.md` and `PLAN.md`, attempt selected planned tasks, and stop on ambiguity.

### Cold-start trial and revision

- Agent: fresh different-model agent in `/tmp/613-cold-start.T1D2Hh`; main workspace was not modified.
- Requested tasks: `CORE-01` and `CORE-02` using only `SPEC.md` and linked plan files.
- Result: CORE-01 reached package scaffolding; `uv run pytest` failed because the fresh environment had no pytest, Pydantic, Ruff, or mypy and no network cache. The report also identified an unspecified build-backend bootstrap path.
- Evidence: `/tmp/613-cold-start.T1D2Hh/cold-start-report.md`.
- Human/agent response: revised `SPEC.md`, the approved design, and CORE-01/CORE-02 plan instructions to distinguish dependency provisioning from offline test execution; added a standard-library baseline test and an explicit `DEPENDENCY_PROVISIONING_BLOCKED` stop condition.
- Commit: `fc7bf53` (`docs: clarify offline dependency bootstrap`).

### Worktree fallback

- Task: establish isolated worktree for Subagent-Driven implementation.
- Result: `.worktrees/` was added to `.gitignore`, but `git worktree add` could not create a branch ref lock because `.git/refs/heads/*.lock` is read-only in this environment.
- Decision: follow the worktree skill fallback and execute in the current sandboxed workspace. The failed worktree has no created branch or linked checkout; `git worktree list` contains only `main`.

### CORE-01 package scaffold

- Task: CORE-01 package and test scaffold.
- Skill: `test-driven-development` (failing import test observed before implementation).
- RED evidence: `PYTHONPATH=src python3 -m unittest tests.test_package.PackageTests.test_package_exposes_version` failed with `ModuleNotFoundError: No module named 'coding_harness'`.
- Implementation: added `pyproject.toml`, package namespace initializers, standard-library package test, bootstrap probe, development bootstrap documentation, and `uv.lock`.
- GREEN evidence: the same focused unittest passed; `python3 -m py_compile` passed for scaffold modules.
- Provisioning evidence: `python3 scripts/bootstrap_dev.py` returned `DEPENDENCY_PROVISIONING_BLOCKED` with missing imports `pydantic, pytest` and commands `ruff, mypy`; online lock retry with `UV_CACHE_DIR=/tmp/613-uv-cache uv lock` failed after DNS retries, and offline lock failed because FastAPI was not cached.
- Human intervention: none. Worktree creation remained blocked by read-only Git ref locks, so changes were made in the current workspace per fallback.

### 2026-08-08 15:11:30 Asia/Shanghai — CORE-01 review repair

- Task: CORE-01 package and test scaffold; triggered skills `subagent-driven-development`, `test-driven-development`, and `verification-before-completion`.
- Review input: task reviewer found an incomplete `uv.lock`, a host-environment bootstrap invocation, and missing post-commit delivery fields.
- Action: generated a complete lock with `uv lock` (54 packages) using approved registry access; changed the documented probe to `uv run python scripts/bootstrap_dev.py`; added bytecode ignores; updated `PLAN.md` and `DELIVERY_STATUS.md` with commit, timestamp, actor, and verification evidence.
- Human intervention: registry access was approved for `uv lock`; no source secrets or unrelated user files were changed.
- Lesson: bootstrap probes must execute inside the provisioned `uv` environment, and delivery records require timestamped evidence after the task commit.

### 2026-08-08 18:05:00 Asia/Shanghai — CORE-01 provisioning gate

- `uv lock --check`: passed against the 54-package lockfile.
- `uv sync --all-extras --frozen --offline`: failed with `lancedb==0.36.0` missing from the local cache.
- Decision: retain `DEPENDENCY_PROVISIONING_BLOCKED`; do not start CORE-02 or claim pytest/Ruff/mypy results until a cache or wheelhouse is supplied.

### 2026-08-08 18:14:08 Asia/Shanghai — CORE-01 repair commit

- Commit: `3b0ea0e` (`fix: close CORE-01 bootstrap review findings`).
- Verification: `uv lock --check` passed; focused unittest passed; `py_compile` passed; third-party provisioning remains blocked by the uncached LanceDB wheel.

### 2026-08-08 21:59:19 Asia/Shanghai — CORE-01 development-tool verification

- Provisioning: installed Pydantic, pytest, Ruff, and mypy into `.venv` with `uv pip install`; full project sync remains blocked by uncached LanceDB/PyArrow wheels.
- Verification: `uv run --no-sync python scripts/bootstrap_dev.py` reported `DEPENDENCIES_PROVISIONED`; `PYTHONPATH=src uv run --no-sync pytest -q` passed (1 test); `uv run --no-sync ruff check .` passed; `uv run --no-sync mypy src` passed.
- Human intervention: none beyond earlier registry access approval; no real LLM or secret was used.

### 2026-08-08 22:07:39 Asia/Shanghai — CORE-02 domain contracts

- Task: CORE-02; triggered `test-driven-development` and `verification-before-completion`.
- TDD RED: domain test collection failed with missing `coding_harness.domain.events` and `coding_harness.domain.actions` before implementation.
- GREEN: 7 domain tests passed; Ruff and mypy passed for the domain scope.
- Implementation: added strict Pydantic enums/models, discriminated actions, terminal-state rules, timezone validation, versioned events, and recursive sensitive-key redaction.
- Workflow deviation: the prior implementation agent had terminated and the collaboration namespace was unavailable in this continuation, so the controller implemented the task and recorded that deviation explicitly.

### 2026-08-08 22:08:51 Asia/Shanghai — CORE-02 commit

- Commit: `59bc4f2` (`feat: define harness domain contracts`).
- Fresh verification after commit: 7 domain tests passed; Ruff and mypy passed; unrelated user files remain untouched.

### 2026-08-08 22:14:24 Asia/Shanghai — CORE-02 review fix

- Finding: sensitive-key redaction used substring matching and incorrectly redacted the ordinary key `monkey`.
- TDD RED: the focused event test failed with `[REDACTED] != banana`.
- Fix: tokenize snake/camel/hyphenated keys and redact only explicit secret parts or qualified key names; require the explicit event timestamp specified by CORE-02.
- GREEN: 7 domain tests passed; Ruff and mypy passed.

### 2026-08-08 22:17:38 Asia/Shanghai — CORE-03 dependency ports

- Task: CORE-03; triggered `test-driven-development` and `verification-before-completion`.
- TDD RED: port tests failed during collection because the embedding port module was absent.
- Implementation: added typed Protocol boundaries for LLMs, embeddings, tools, event storage, and policy; added strict immutable-shaped context/result models.
- GREEN: 4 focused port tests and 11 combined domain/port tests passed; Ruff and mypy passed.
- Human intervention: none; tests use fakes only and no provider/network calls.

### 2026-08-08 22:21:23 Asia/Shanghai — CORE-04 SQLite storage

- Task: CORE-04; triggered `test-driven-development` and `verification-before-completion`.
- TDD RED: storage tests failed during collection because the SQLite adapter package was absent.
- Implementation: added the complete initial schema, Run model, transactional run/event/iteration writes, ordered event reads, and mandatory persistence-boundary redaction.
- GREEN: 5 focused storage tests and 16 combined core tests passed; Ruff and mypy passed; a 20-event, 4-thread temporary-database check passed.
- Human intervention: none; all storage tests use temporary SQLite databases.

### 2026-08-08 22:25:19 Asia/Shanghai — CORE-05 LLM adapters

- Task: CORE-05; triggered `test-driven-development` and `verification-before-completion`.
- TDD RED: adapter tests failed during collection because the LLM adapter package was absent.
- Implementation: added deterministic scripted responses with deep snapshots and a single-call OpenAI-compatible HTTP adapter with typed failures.
- GREEN: 7 focused adapter tests and 23 combined core tests passed; Ruff and mypy passed.
- Human intervention: none; HTTP tests use MockTransport, no API key, real LLM, retry, or external request.

### 2026-08-08 22:31:15 Asia/Shanghai — CORE-06 repository tools

- Task: CORE-06; triggered `test-driven-development` and `verification-before-completion`.
- TDD RED: tests failed during collection because tool adapters and the registry were absent.
- Implementation: canonical-root filesystem reads/edits/search, bounded UTF-8 handling, pure-Python Git diff, and JSON Schema validated dispatch.
- Dependencies: added and uv-locked Dulwich, jsonschema, and types-jsonschema to implement the specified low-level boundaries without shell Git or ad hoc schema parsing.
- GREEN: 8 focused tests and all 32 project tests passed; Ruff, mypy, and lock check passed.

### 2026-08-08 22:37:12 Asia/Shanghai — CORE-07 policy and approvals

- Task: CORE-07; triggered `test-driven-development`, `systematic-debugging`, and `verification-before-completion`.
- TDD RED: modules were absent; a focused review RED later exposed shell-wrapped destructive commands and missing approval run ownership.
- Implementation: deterministic hard-rule/config/mode policy precedence plus exact, expiring, one-time approval state.
- Security coverage: repository/symlink/credential escape, Docker socket, privileged containers, destructive argv/shell commands, memory override attempts, install/network/Git writes, stale/rejected approvals.
- GREEN: 17 focused tests and all 49 project tests passed; Ruff and mypy passed.

### 2026-08-08 22:44:36 Asia/Shanghai — CORE-08 feedback and budgets

- Task: CORE-08; triggered `test-driven-development`, `systematic-debugging`, and `verification-before-completion`.
- TDD RED: missing modules, then focused REDs for combined stdout/stderr cap overflow and retryable repeated failure.
- Implementation: objective feedback classifier, repeated fingerprints, validation freshness, four independent budgets, and bounded argv-only subprocess runner.
- Safety: no `shell=True`; allowlisted environment; timeout kills the process group; stdout/stderr share one cap; optional memory/process limits use `prlimit` without unsafe `preexec_fn`.
- GREEN: 19 focused tests and all 68 project tests passed; Ruff and mypy passed.

### 2026-08-08 22:56:36 Asia/Shanghai — CORE-09 structured/vector memory

- Task: CORE-09; triggered `test-driven-development`, `systematic-debugging`, and `verification-before-completion`.
- Provisioning: hash-verified LanceDB/PyArrow wheels; full frozen uv sync completed with 61 locked packages.
- TDD RED: missing memory modules; later focused REDs for absent permission query tags and first-word-only fallback.
- Implementation: SQLite-authoritative redacted text, rebuildable LanceDB ID/vector index, deterministic and HTTP embedding adapters, permission-filtered bounded context, multi-term fallback, and deletion cleanup.
- GREEN: 7 focused real SQLite/LanceDB tests and all 75 project tests passed; Ruff, mypy, and lock check passed.

### 2026-08-08 23:14:22 Asia/Shanghai — CORE-10 feedback-driven AgentLoop

- Task: CORE-10; triggered `subagent-driven-development`, `test-driven-development`, `systematic-debugging`, and `verification-before-completion`.
- Workflow context: resumed a controller-owned, uncommitted CORE-10 implementation after context compaction; preserved the existing SDD ledger and user-owned untracked files. The controller completed the in-progress implementation because no fresh implementer had produced this partial working tree; an independent task reviewer remains required before completion.
- TDD RED: the initial focused suite exposed ignored provider-cost exhaustion and eager `dict.setdefault` dependency creation. The next focused RED exposed rejected approvals remaining in `WAITING_APPROVAL`; an added expiry test proved stale requests also waited forever.
- Implementation: added the owned state machine, injectable dependencies, run service, persisted summaries/events/iterations, exact approval resume/reject/expiry handling, post-call budget enforcement, SQLite run updates, and the deterministic wrong-edit/feedback/repair/pass demo with memory and hard-guardrail checks.
- Commit: `2dd32f9` (`feat: implement feedback-driven agent loop`).
- Verification: 12 focused tests passed; all 84 project tests passed; Ruff, mypy, and `uv lock --check` passed. No real LLM, network request, API key, or high-level agent framework was used.
- Human intervention: the user confirmed continuing the approved CORE-10 review criteria. Lesson: budget checks must gate actions after provider accounting, and approval resumption must inspect request state rather than infer it from token consumption alone.

### 2026-08-09 00:28:57 Asia/Shanghai — CORE-10 persistence and audit fix round

- Task: CORE-10 fix round 1; triggered `receiving-code-review`, `systematic-debugging`, `test-driven-development`, and `verification-before-completion`.
- Review findings addressed: moved resumable session/approval state from process-local dictionaries to SQLite; restored exact pending actions, budget limits/usage, validation freshness, evidence, blockers, and iteration counters after a new `RunService`; added policy/schema evidence and accurate terminal records; mapped dependency exceptions to terminal states; made terminal cancellation immutable; blocked finish until feedback is resolved; and routed the demo through `RunService`.
- TDD RED/GREEN: 36 focused tests cover persistent approval/resume/reject, terminal records, exception boundaries, completion blocking, terminal immutability, budget configuration reconstruction, and demo run persistence. Full offline suite: 98 passed. Ruff, mypy, and lock check passed.
- Commit: `d705637` (`fix: persist and audit agent loop state`). Direct demo inspection produced `completed/success`, `stored_run_state=completed`, three iterations, one loop-session snapshot, and zero approval records for the balanced-mode scenario.
- Workflow deviation: the assigned fix implementer experienced one transient 503, resumed, then continued writing a valid budget-limit persistence test after the controller's first commit but did not report or commit. The controller preserved that change, re-ran all gates, amended `d705637`, and completed the audit. The scoped re-review dispatch is unavailable in this resumed tool context, so this task remains review-pending rather than complete.
- Lesson: persistence correctness requires keeping both limits and consumption state; restoring only counters lets a restarted dependency factory silently alter a run's budget semantics.

### 2026-08-09 01:11:12 Asia/Shanghai — CORE-10 recovery hardening and scoped re-review

- Task: CORE-10 fix round 2; triggered `receiving-code-review`, `test-driven-development`, `systematic-debugging`, `requesting-code-review`, and `verification-before-completion`.
- Implementation: SQLite iteration/session/approval payloads are redacted before serialization; iteration plus session writes are atomic; approvals use atomic compare-and-set with `EXECUTING` before dispatch and delayed `CONSUMED`; cancellation invalidates pending approvals; recovered approvals recheck current hard/repository policy; malformed dependency values and exceptions become terminal state; classifier state and budget limits survive reconstruction; denied model calls do not inflate usage; secret-bearing actions are hard-denied before persistence.
- TDD RED/GREEN: focused recovery REDs reproduced secret leakage, non-atomic approval claims, stale approval policy bypass, unresolved policy risk clearing, malformed dependency crashes, transaction rollback gaps, classifier restart loss, budget over-counting, and secret-bearing ASK behavior. Focused fix suite passed 66 tests; full suite passed 110 tests.
- Commits: `06b397e` (`fix: harden persisted agent loop recovery`); `f9394d7` (`docs: record CORE-10 recovery hardening`).
- Independent scoped re-review: all original findings plus fix-round boundary checks were `ADDRESSED`; no new Critical/Important breakage. The reviewer recorded stale concurrent `RunService._persist_status` as out-of-scope because that code was unchanged in the fix diff; retain it for the final whole-branch review.
- Controller verification: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy src`, `uv lock --check`, and `git diff --check f154bba..f9394d7` passed. Direct offline demo returned `completed/success`, observed feedback/guardrail/memory, and wrote `answer.py` with `return 2`; SQLite persisted `runs.state=completed` in the regression test.
- Decision: CORE-10 complete; proceed to CORE-11 Keyring Credentials. The demo's `total_model_calls=5` remains configuration-only and is not a product-wide turn cap.

### 2026-08-09 01:21:53 Asia/Shanghai — CORE-11 keyring credentials

- Task: CORE-11; triggered `test-driven-development` and `verification-before-completion`.
- TDD RED: focused credential tests failed during collection with `ModuleNotFoundError: No module named 'coding_harness.adapters.credentials'`.
- Implementation: injected `CredentialStore` boundary, secret-free `CredentialStatus`/`SecretReference`, OS keyring adapter, provider isolation, idempotent clear, and explicit opt-in `CODING_HARNESS_<PROVIDER>_API_KEY` fallback.
- GREEN: focused suite 4 passed; full suite 114 passed; Ruff and mypy passed. Captured-output assertions contain no key-like values.
- Report: `.superpowers/sdd/2026-08-08-613-coding-core/task-11-report.md`.
- Lesson: keep credential references opaque and defer any raw-secret injection to a separately governed provider boundary.

### 2026-08-09 02:02:37 Asia/Shanghai — CORE-11 review and fix round

- Task: CORE-11 review/fix round 1; triggered `requesting-code-review`, `receiving-code-review`, `systematic-debugging`, `test-driven-development`, and `verification-before-completion`.
- Review: an independent read-only Claude Code reviewer found two Important issues: untested backend delete/read double-fault handling and a `type: ignore` that hid the `source="none"` state mismatch. It also recorded two deferred Minor findings.
- TDD: after discarding an unproven production edit, the controller retained the new behavior tests and observed the focused RED: 1 failed, 5 passed, with the raw `get_password` exception. A fresh implementation agent then added the minimal production fix.
- Implementation: nested recovery error mapping preserves missing-delete idempotency and converts double-faults to `CredentialError`; explicit source narrowing prevents `"none"` from reaching `SecretReference` and removes the type suppression.
- Verification: focused credentials 6 passed; full suite 116 passed; Ruff, mypy, `uv lock --check`, and `git diff --check` passed.
- Commit: `d748a0e` (`fix: harden credential error handling`).
- Scoped re-review: both Important findings `ADDRESSED`; no new Critical/Important breakage.
- Workflow deviation: the platform collaboration namespace was unavailable in this continuation. The first CLI fix agent stalled and left unreported changes, so the controller restored the production baseline, observed RED, and used separate read/edit-only Claude Code agents for the production and test-quality steps. User-owned untracked files remained untouched.
- Lesson: a fix report must reproduce exact command evidence; model-generated test names, exception types, or timings are not acceptable substitutes.

### 2026-08-09 02:59:19 Asia/Shanghai — Core final-review fix wave

- Task: Core whole-branch final-review findings; triggered `receiving-code-review`, `systematic-debugging`, `test-driven-development`, `requesting-code-review`, and `verification-before-completion`.
- Root cause: SQLite connection context managers committed or rolled back but never closed; `RunService` persisted a pre-loop snapshot through unconditional `update_run`, allowing a stale service to replace a newer terminal state.
- TDD RED: `uv run pytest tests/adapters/storage/test_sqlite.py tests/adapters/storage/test_memory.py tests/application/test_loop.py -q` produced 6 failed and 42 passed. Failures deterministically showed open connections after success/exception, the missing SQLite run CAS, and stale `resume`/`cancel` overwrites.
- Implementation: added close-owning transaction contexts to both SQLite repositories; replaced run updates with a full-snapshot atomic CAS; reconciled lost service races to the authoritative persisted state and stop reason.
- Review repair RED: independent review found one Important gap: already-terminal `resume()` could re-enter the loop and terminal `cancel()` could return a stale session summary. The focused regression produced 2 failed and 33 deselected before production edits.
- Final GREEN: terminal-entry regression passed 2 tests; required focused suite passed 50 tests; full suite passed 126 tests. `uv run ruff check .`, `uv run mypy src`, `uv lock --check`, and `git diff --check` passed.
- Review: no Critical or Minor issues; the one Important finding was addressed with terminal entry-point short-circuits and authoritative summary reconciliation. Full evidence is in `.superpowers/sdd/2026-08-08-613-coding-core/core-final-review-fix-report.md`.
- Commit: `9af4f03` (`fix: close core final review findings`).
- Workflow context: used the user-authorized current-workspace fallback because Git ref locks prevented worktree creation. Human intervention: prior authorization only. User-owned untracked `.claude/` and both untracked requirement documents remained untouched.
- Lesson: transaction context management and resource ownership are separate SQLite concerns; optimistic concurrency must compare the snapshot atomically at the persistence boundary, surface the winning state to callers, and prevent later terminal entry points from trusting stale loop-session state.

### 2026-08-09 03:33:03 Asia/Shanghai — SANDBOX-01 runtime contracts

- Task: SANDBOX-01; triggered `subagent-driven-development`, `test-driven-development`, `systematic-debugging`, and `verification-before-completion`.
- TDD RED: focused collection failed with `ModuleNotFoundError: No module named 'coding_harness.adapters.sandbox'` and one collection error before implementation.
- Implementation: added strict sandbox/resource/command/artifact models, the injectable `SandboxRuntime` port, and a deterministic fake runtime that records lifecycle calls and rejects destroyed handles.
- Verification: focused sandbox contracts passed 5 tests; the full offline suite passed 131 tests; Ruff, mypy across 48 source files, `uv lock --check`, and `git diff --check` passed.
- Commit: `024925a` (`feat: define sandbox runtime contract`); independent task review remains pending.
- Workflow deviation: the external Codex implementer stalled after more than six minutes while exiting a successful full-suite run inside its nested bwrap sandbox. The controller reproduced the same tree outside that nested sandbox (`131 passed in 1.59s`), interrupted the stalled process, preserved its files, and reconstructed the task report from observed output. No user-owned untracked files were touched.
- Human intervention: the user confirmed continuous execution. Lesson: nested sandbox process shutdown can differ from the product test environment; controller verification and repository evidence remain authoritative.

### 2026-08-09 03:48:49 Asia/Shanghai — SANDBOX-01 finite-limit review fix

- Task: SANDBOX-01 fix round 1; triggered `receiving-code-review`, `systematic-debugging`, `test-driven-development`, and `verification-before-completion`.
- Review: independent task review found one Important issue and no Critical/Minor issues: positive infinity was accepted for CPU and command-time limits despite the finite-resource invariant.
- TDD RED: the focused regression produced 2 failed and 7 passed; `float("inf")` was accepted for `cpu_seconds` and `timeout_seconds`.
- Fix: added `allow_inf_nan=False` to exactly those two Pydantic fields and parameterized coverage for both infinities.
- Controller verification: focused sandbox contracts passed 9 tests; the full offline suite passed 135 tests; Ruff, mypy across 48 source files, `uv lock --check`, and `git diff --check` passed.
- Commit: `5d4e787` (`fix: require finite sandbox duration limits`).
- Workflow note: the isolated fix Agent used a writable `/tmp` uv cache and intentionally skipped its nested full suite; the controller ran the complete suite. Scoped re-review remains pending.

### 2026-08-09 03:52:47 Asia/Shanghai — SANDBOX-01 scoped re-review

- Independent read-only re-review marked finite CPU/time validation and its regression coverage `ADDRESSED`.
- New breakage: none. Out-of-scope observations: none. No Critical/Important finding remains.
- Decision: SANDBOX-01 complete through `9df471d`; proceed to SANDBOX-02 workspace and artifact isolation.

### 2026-08-09 04:01:20 Asia/Shanghai — SANDBOX-02 workspace and artifact export

- Task: SANDBOX-02; triggered `using-superpowers`, `test-driven-development`, `systematic-debugging`, and `verification-before-completion`.
- TDD RED: `UV_CACHE_DIR=/tmp/613-sandbox-02-uv-cache uv run pytest tests/sandbox/test_workspace.py tests/sandbox/test_artifacts.py -q` failed during collection with two expected `ModuleNotFoundError` errors for the absent workspace/artifact modules.
- Implementation: added temporary Git-shaped workspaces that preserve ignored/untracked files, canonical/symlink-safe manifests, scoped cleanup, normalized write sets, deterministic unified patches, binary summaries, and pre-export redaction through `WorkArtifact` metadata.
- GREEN: `UV_CACHE_DIR=/tmp/613-sandbox-02-uv-cache uv run pytest tests/sandbox -q` passed with 16 tests. Scoped Ruff, scoped mypy, and `git diff --check` passed.
- Debugging evidence: the first implementation run had 6 passed and 1 failed because `WorkspacePathError` did not satisfy the focused `ValueError` boundary; the traceback was reproduced, the exception hierarchy was corrected, and the final focused run passed.
- Security regression RED/GREEN: a cleanup ownership test first failed because a fabricated workspace was deleted without error; manager-owned/cleaned path tracking was added, and the final sandbox suite passed 17 tests.
- Changed files: `src/coding_harness/adapters/sandbox/workspace.py`, `src/coding_harness/adapters/sandbox/artifacts.py`, `tests/sandbox/test_workspace.py`, `tests/sandbox/test_artifacts.py`, and the task report.
- Human intervention: none; protected `.claude/` and both untracked requirement documents were untouched. No commit was attempted because Git metadata is not writable in this sandbox.
- Lesson: artifact export must compare the whole working-tree manifest, not only Git's tracked diff, when ignored and untracked worker output is part of the contract.

### 2026-08-09 04:10:07 Asia/Shanghai — SANDBOX-02 controller hardening

- Review-driven TDD found and fixed five artifact/isolation boundary defects: incomplete temporary-root cleanup, dotfile allowlist corruption, empty allowlist fail-open behavior, ignored explicit empty baselines, and missing mode-only changes.
- RED evidence: workspace tests failed 3 cases before the cleanup/write-set fix; artifact tests failed 2 cases before baseline/mode support. GREEN: 12 focused workspace/artifact tests and 21 sandbox tests passed.
- Full controller verification: 147 tests passed; Ruff passed; mypy passed across 50 source files; `uv lock --check` resolved 61 packages; `git diff --check` passed.
- Scope: only SANDBOX-02 source, tests, and evidence were changed. Protected user-owned untracked paths remain untouched.

### 2026-08-09 04:18:00 Asia/Shanghai — SANDBOX-02 independent review and repairs

- Initial review found one Critical fabricated-workspace export path, two Important ownership/integrity issues, and one Minor redaction gap. Fix commit `840cc21` bound exporter access to exact manager-issued objects, froze workspace/baseline state, enforced baseline identity, and redacted all artifact field shapes.
- Scoped re-review closed those findings but exposed a filesystem boundary: replacing a genuine workspace root with an external symlink bypassed snapshot canonicalization. Fix commit `aa3600a` rejects symlink, non-directory, and non-canonical roots before export and adds regression coverage.
- Final verification: `uv run pytest tests/sandbox -q` passed 26 tests; full `uv run pytest -q` passed 152 tests; Ruff, mypy across 50 source files, `uv lock --check`, and `git diff --check` passed.
- Review decision: SANDBOX-02 has no remaining Critical/Important findings and is complete. Next task: SANDBOX-03 Docker lifecycle.

### 2026-08-09 04:30:00 Asia/Shanghai — SANDBOX-03 Docker lifecycle

- Task: SANDBOX-03; TDD RED was the expected missing `docker_runtime` module collection error.
- Implementation: added Docker options and runtime lifecycle with copied workspace mounts, pinned image/user/read-only/capability/network settings, bounded memory/PIDs/CPU, timeout/output mapping, artifact export, and cleanup on create/start failures.
- Hardening: added runtime-enforced timeout, start-failure cleanup, and frozen object-identity handles to prevent same-UUID forgery and container leaks. Commits: `bf129cd`, `3ec6ac1`.
- Verification: focused runtime tests passed 8; sandbox suite passed 34; full suite passed 160; Ruff, mypy across 52 source files, `uv lock --check`, and `git diff --check` passed.
- Docker smoke: daemon `29.6.2` was available, but only an unapproved `postgres:16-alpine` image was local; no real worker image was pulled, so guarded smoke was skipped with that explicit reason.
- Review decision: fake-client lifecycle and security boundary review clean; proceed to SANDBOX-04 policy composition.
