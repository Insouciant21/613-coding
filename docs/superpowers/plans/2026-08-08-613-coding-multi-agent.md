# 613 Coding Multi-Agent Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a Supervisor and role-specific workers that communicate through a dependency-aware task graph and versioned work artifacts while reusing the core agent loop and sandbox runtime.

**Architecture:** The Supervisor owns scheduling, retries, aggregation, and integration. Worker sessions are independent instances of `AgentLoop` with role policies and sandbox handles. A worker can only publish a `WorkArtifact`; the Supervisor applies it in an integration workspace and validates it.

**Tech Stack:** Core domain/ports, sandbox runtime, Pydantic, SQLite event store, asyncio task scheduling, pytest, deterministic mock agents.

## Global Constraints

- Planner is read-only; coder has scoped writes; tester, reviewer, and security have role-specific tool permissions.
- Independent read-only nodes may run concurrently; overlapping write sets are serialized.
- Workers communicate only through versioned messages/artifacts and persisted events.
- Merge conflicts are never silently overwritten.
- Multi-agent tests use scripted mock workers and no real LLM or network.
- Before each task commit, append actual task evidence to `AGENT_LOG.md` and `DELIVERY_STATUS.md`; after the commit, update `PLAN.md` with the hash.

### Task MULTI-01: TaskGraph And Worker Contracts

**Files:**
- Create: `src/coding_harness/domain/tasks.py`
- Create: `src/coding_harness/domain/worker.py`
- Create: `src/coding_harness/ports/orchestration.py`
- Test: `tests/multi_agent/test_task_graph.py`
- Test: `tests/multi_agent/test_worker_contracts.py`

**Interfaces:**

```python
class WorkerRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    TESTER = "tester"
    REVIEWER = "reviewer"
    SECURITY = "security"

class Worker(Protocol):
    async def run(self, node: TaskNode, context: WorkerContext) -> WorkArtifact: ...

class TaskScheduler(Protocol):
    async def next_ready(self, graph: TaskGraph) -> list[TaskNode]: ...
```

- [ ] **Step 1: Write failing tests** for graph validation, missing dependencies, cycles, write-set overlap detection, node transitions, artifact schema, and role permission metadata.
- [ ] **Step 2: Run `uv run pytest tests/multi_agent/test_task_graph.py tests/multi_agent/test_worker_contracts.py -q`; expect missing models.**
- [ ] **Step 3: Implement strict graph and artifact models plus ready-node calculation and cycle errors.**
- [ ] **Step 4: Run tests and type-check the orchestration ports.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/domain/tasks.py src/coding_harness/domain/worker.py src/coding_harness/ports/orchestration.py tests/multi_agent && git commit -m "feat: define multi-agent task and worker contracts"`.

### Task MULTI-02: Role Policies And Worker Runtime

**Files:**
- Create: `src/coding_harness/application/worker_runtime.py`
- Create: `src/coding_harness/application/role_policies.py`
- Create: `src/coding_harness/adapters/orchestration/mock_workers.py`
- Test: `tests/multi_agent/test_role_policies.py`
- Test: `tests/multi_agent/test_worker_runtime.py`

**Interfaces:** `WorkerRuntime(loop_factory, sandbox_runtime).run(node, task_context) -> WorkArtifact`; `role_policy(role) -> ToolPolicy`.

- [ ] **Step 1: Write failing tests** for planner read-only behavior, coder scoped edits, tester no-production-write behavior, reviewer/security output contracts, sandbox creation, and artifact export.
- [ ] **Step 2: Run focused tests; expect missing role/runtime failures.**
- [ ] **Step 3: Implement role policies and worker adapter that creates an isolated sandbox, runs the owned loop, exports an artifact, and destroys the sandbox on all exits.**
- [ ] **Step 4: Run fake-loop/fake-sandbox tests and inspect emitted worker events.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/application/worker_runtime.py src/coding_harness/application/role_policies.py src/coding_harness/adapters/orchestration tests/multi_agent && git commit -m "feat: run role-specific coding workers"`.

### Task MULTI-03: Supervisor Scheduling And Budgets

**Files:**
- Create: `src/coding_harness/application/supervisor.py`
- Create: `src/coding_harness/application/scheduling.py`
- Test: `tests/multi_agent/test_scheduler.py`
- Test: `tests/multi_agent/test_supervisor.py`

**Interfaces:** `Supervisor.create_graph(task) -> TaskGraph`; `Supervisor.run(graph_id) -> SupervisorSummary`; `.pause(graph_id)`, `.resume(graph_id)`, `.cancel(graph_id)`; `Scheduler.select_ready(graph) -> list[TaskNode]`.

- [ ] **Step 1: Write failing tests** for dependency order, parallel read-only nodes, serialized overlapping writes, per-node retry budgets, total-call budget, worker failure propagation, pause/resume, and cancellation.
- [ ] **Step 2: Run tests; expect missing scheduling behavior.**
- [ ] **Step 3: Implement explicit graph state transitions, asyncio task scheduling, semaphore concurrency limits, event persistence, and supervisor-level budget accounting.**
- [ ] **Step 4: Run deterministic tests with scripted workers and assert stable scheduling order.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/application/supervisor.py src/coding_harness/application/scheduling.py tests/multi_agent && git commit -m "feat: schedule multi-agent task graphs"`.

### Task MULTI-04: Artifact Integration And Conflict Feedback

**Files:**
- Create: `src/coding_harness/application/artifact_integrator.py`
- Create: `src/coding_harness/adapters/orchestration/integration_workspace.py`
- Test: `tests/multi_agent/test_artifact_integration.py`

**Interfaces:** `ArtifactIntegrator.apply(artifact, workspace) -> IntegrationResult`; `.replay_conflict(artifact, latest_workspace) -> IntegrationResult`; `.validate(workspace) -> list[Feedback]`.

- [ ] **Step 1: Write failing tests** for clean patch application, file allowlists, one replay attempt, conflict classification, reviewer rejection feedback, and no silent overwrite.
- [ ] **Step 2: Run tests; expect missing integration behavior.**
- [ ] **Step 3: Implement patch application in a controlled integration workspace, conflict detection, one replay limit, and validation handoff to the core classifier.**
- [ ] **Step 4: Run tests with two artifacts touching the same file and assert `merge_conflict`.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/application/artifact_integrator.py src/coding_harness/adapters/orchestration/integration_workspace.py tests/multi_agent && git commit -m "feat: integrate worker artifacts safely"`.

### Task MULTI-05: Deterministic Multi-Agent Demonstration

**Files:**
- Create: `src/coding_harness/demo/multi_agent.py`
- Test: `tests/demo/test_multi_agent.py`
- Modify: `DELIVERY_STATUS.md`
- Modify: `AGENT_LOG.md`

**Interfaces:** `run_multi_agent_demo() -> SupervisorSummary` must use scripted planner/coder/tester/reviewer workers and expose graph events, feedback repair, approval, integration, and final validation.

- [ ] **Step 1: Write failing demo assertions** for graph creation, wrong patch feedback, corrected artifact, reviewer approval, integration, and terminal summary.
- [ ] **Step 2: Run `uv run pytest tests/demo/test_multi_agent.py -q`; expect failures.**
- [ ] **Step 3: Implement the deterministic worker scripts and demo runner using fake sandbox/runtime dependencies.**
- [ ] **Step 4: Run the offline demo and record exact output and commit evidence.**
- [ ] **Step 5: Update `DELIVERY_STATUS.md` and `AGENT_LOG.md`.**
- [ ] **Step 6: Commit.** `git add src/coding_harness/demo/multi_agent.py tests/demo/test_multi_agent.py DELIVERY_STATUS.md AGENT_LOG.md && git commit -m "test: demonstrate supervisor worker feedback"`.
