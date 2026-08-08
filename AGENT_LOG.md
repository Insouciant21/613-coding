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
