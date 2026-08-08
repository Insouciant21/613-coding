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
| `docs/superpowers/plans/2026-08-08-613-coding-core.md` | Domain contracts, tools, feedback, memory, credentials, agent loop | Cold-start gate | CORE-01 complete; CORE-02 blocked on provisioning |
| `docs/superpowers/plans/2026-08-08-613-coding-sandbox.md` | Task workspaces and Docker runtime isolation | Core ports and artifacts | pending |
| `docs/superpowers/plans/2026-08-08-613-coding-multi-agent.md` | Task graph, workers, Supervisor, artifact integration | Core loop, sandbox | pending |
| `docs/superpowers/plans/2026-08-08-613-coding-delivery.md` | CLI, FastAPI/WebUI, CI, package, Docker demo, records | Core services; sandbox for demo | pending |

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

- `CORE-01` through `CORE-10`: package, domain, providers, storage, tools/policy, validation/feedback, memory, agent loop, credentials, and deterministic demo.
- `SANDBOX-01` through `SANDBOX-05`: sandbox contracts, workspace/artifacts, Docker lifecycle, security/resource policy, and integration evidence.
- `MULTI-01` through `MULTI-05`: task graph, worker runtime, Supervisor scheduling, artifact integration, and orchestration demo.
- `DELIVERY-01` through `DELIVERY-07`: CLI, API, WebUI, distribution, CI, documentation, and delivery-record automation.

Every task must end with a focused test result and commit hash. `DELIVERY_STATUS.md` must link the evidence before a task is marked complete.

## CORE-01 Task Evidence

- Status: complete after task review and bootstrap repair.
- Commit: `4d51108` scaffold; repair commit is recorded in the task ledger and delivery status.
- Verification: focused standard-library unittest and `py_compile` passed; `uv lock --check` passed for 54 packages; `uv sync --all-extras --frozen --offline` is blocked by the uncached `lancedb==0.36.0` wheel, so canonical third-party checks remain unrun.
- Gate: `uv run --no-sync python scripts/bootstrap_dev.py` now reports `DEPENDENCIES_PROVISIONED`; CORE-02 may start. Full LanceDB/PyArrow sync remains a later memory-task gate.
