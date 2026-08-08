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

## Approaches Considered

1. Core state machine with CLI/WebUI adapters: selected because it gives clear injectable boundaries and a deep feedback mechanism.
2. Full event-sourced workflow engine: adopted only for structured events, not full replay infrastructure, to control scope.
3. Plugin-first platform: rejected as the primary structure because it would dilute the feedback-loop contribution.

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
