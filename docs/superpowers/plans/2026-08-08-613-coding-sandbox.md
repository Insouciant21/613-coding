# 613 Coding Container Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Run every product worker in a temporary, resource-limited Docker container with an isolated task workspace and versioned artifact export.

**Architecture:** `SandboxRuntime` is a port consumed by the agent loop and Supervisor. A local workspace copier creates a task-specific repository copy; `DockerSandboxRuntime` creates and monitors a container without exposing Docker credentials or the host repository. `FakeSandboxRuntime` makes lifecycle and policy tests deterministic.

**Tech Stack:** Python 3.12+, Docker Engine API client, Pydantic models from the core plan, pytest, temporary Git repositories.

## Global Constraints

- Workers run non-root with read-only root filesystems, dropped capabilities, default-deny network, pinned image digests, resource limits, output caps, and automatic cleanup.
- Docker socket, SSH agent, host home, credential directories, and writable original repository are never mounted into workers.
- The sandbox mitigates ordinary tool mistakes and untrusted-code impact; it does not guarantee protection from kernel/runtime vulnerabilities.
- Every lifecycle and resource decision is an event and is tested with a fake runtime without a Docker daemon.
- Before each task commit, append actual task evidence to `AGENT_LOG.md` and `DELIVERY_STATUS.md`; after the commit, update `PLAN.md` with the hash.

### Task SANDBOX-01: Sandbox Models And Runtime Port

**Files:**
- Create: `src/coding_harness/domain/sandbox.py`
- Create: `src/coding_harness/ports/sandbox.py`
- Create: `src/coding_harness/adapters/sandbox/fake.py`
- Test: `tests/sandbox/test_contracts.py`

**Interfaces:**

```python
class SandboxRuntime(Protocol):
    def create(self, spec: SandboxSpec) -> SandboxHandle: ...
    def execute(self, handle: SandboxHandle, command: Sequence[str]) -> CommandResult: ...
    def export(self, handle: SandboxHandle) -> WorkArtifact: ...
    def destroy(self, handle: SandboxHandle) -> None: ...
```

`SandboxSpec` contains image digest, workspace path, network policy, resource limits, environment allowlist, and worker ID. `SandboxHandle` contains only opaque IDs and paths. `FakeSandboxRuntime` records calls and returns scripted results.

- [ ] **Step 1: Write failing tests** for spec validation, non-root/default-deny defaults, opaque handles, lifecycle order, and fake artifact export.
- [ ] **Step 2: Run `uv run pytest tests/sandbox/test_contracts.py -q`; expect missing model/port failures.**
- [ ] **Step 3: Implement strict Pydantic models, the Protocol, and the fake runtime with cleanup assertions.**
- [ ] **Step 4: Run tests and type-check the sandbox port.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/domain/sandbox.py src/coding_harness/ports/sandbox.py src/coding_harness/adapters/sandbox/fake.py tests/sandbox && git commit -m "feat: define sandbox runtime contract"`.

### Task SANDBOX-02: Task Workspace Copy And Artifact Export

**Files:**
- Create: `src/coding_harness/adapters/sandbox/workspace.py`
- Create: `src/coding_harness/adapters/sandbox/artifacts.py`
- Test: `tests/sandbox/test_workspace.py`
- Test: `tests/sandbox/test_artifacts.py`

**Interfaces:** `WorkspaceManager.create(source_repo, run_id, worker_id) -> Workspace`; `.cleanup(workspace)`; `ArtifactExporter.collect(workspace, baseline) -> WorkArtifact`.

- [ ] **Step 1: Write failing tests** for Git copy, ignored/untracked file handling, canonical paths, changed-file allowlists, patch generation, binary-file summary, redacted logs, and cleanup after success/failure.
- [ ] **Step 2: Run focused tests; expect missing workspace/artifact failures.**
- [ ] **Step 3: Implement copy using a temporary directory and Git baseline, export unified diff plus metadata, and reject files outside declared write sets.**
- [ ] **Step 4: Run tests on temporary repositories with symlinks and untracked files.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/adapters/sandbox/workspace.py src/coding_harness/adapters/sandbox/artifacts.py tests/sandbox && git commit -m "feat: isolate task workspaces and export artifacts"`.

### Task SANDBOX-03: Docker Container Lifecycle

**Files:**
- Create: `src/coding_harness/adapters/sandbox/docker_runtime.py`
- Create: `src/coding_harness/adapters/sandbox/docker_config.py`
- Test: `tests/sandbox/test_docker_runtime.py`

**Interfaces:** `DockerSandboxRuntime(docker_client, workspace_manager, artifact_exporter).create(spec)`, `.execute(handle, command)`, `.export(handle)`, and `.destroy(handle)`.

- [ ] **Step 1: Write failing tests** with a fake Docker client for container create options, start/exec/stop/remove order, non-zero exit mapping, missing daemon, timeout, and cleanup in a `finally` path.
- [ ] **Step 2: Run tests; expect missing Docker adapter behavior.**
- [ ] **Step 3: Implement Docker API calls with pinned image, read-only root, dropped capabilities, temporary workspace mount, no socket mounts, and opaque IDs in events.**
- [ ] **Step 4: Run fake-client tests and a guarded local smoke test only when Docker is available.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/adapters/sandbox/docker_runtime.py src/coding_harness/adapters/sandbox/docker_config.py tests/sandbox && git commit -m "feat: run workers in temporary docker containers"`.

### Task SANDBOX-04: Network, Resource, And Image Policy

**Files:**
- Modify: `src/coding_harness/application/policy.py`
- Create: `src/coding_harness/application/sandbox_policy.py`
- Test: `tests/sandbox/test_security_policy.py`

**Interfaces:** `SandboxPolicy.validate(spec, mode, config) -> SandboxDecision`; `ResourceBudget.cpu_seconds`, `.memory_bytes`, `.pids`, `.disk_bytes`, `.timeout_seconds`, `.output_bytes`.

- [ ] **Step 1: Write failing tests** for default no-network, approved allowlisted network, root/capability rejection, resource-bound validation, unpinned image rejection, credential/env rejection, and output overflow.
- [ ] **Step 2: Run tests; expect policy failures.**
- [ ] **Step 3: Implement policy composition so autonomous mode cannot override hard sandbox rules, network approvals are exact and recorded, and resource violations become `resource_exhausted` feedback.**
- [ ] **Step 4: Run tests and inspect event payloads for host paths/secrets.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/application/sandbox_policy.py src/coding_harness/application/policy.py tests/sandbox && git commit -m "feat: enforce sandbox resource and network policy"`.

### Task SANDBOX-05: Sandbox Mechanism Demonstration And Verification

**Files:**
- Create: `src/coding_harness/demo/sandbox.py`
- Test: `tests/demo/test_sandbox.py`
- Modify: `DELIVERY_STATUS.md`
- Modify: `AGENT_LOG.md`

**Interfaces:** `run_sandbox_demo(runtime: SandboxRuntime) -> SandboxDemoSummary` must demonstrate isolated workspace, blocked dangerous mount/command, resource timeout mapping, artifact export, and cleanup.

- [ ] **Step 1: Write failing demo assertions** for per-worker isolation, denied network/socket access, exported patch, and destroyed handle.
- [ ] **Step 2: Run `uv run pytest tests/demo/test_sandbox.py -q`; expect failures.**
- [ ] **Step 3: Implement the fake-runtime demo and a Docker smoke path that is skipped with an explicit reason when no daemon exists.**
- [ ] **Step 4: Run the offline demo and optional guarded Docker smoke test; record actual outputs.**
- [ ] **Step 5: Update `DELIVERY_STATUS.md` and `AGENT_LOG.md` with command/result evidence.**
- [ ] **Step 6: Commit.** `git add src/coding_harness/demo/sandbox.py tests/demo/test_sandbox.py DELIVERY_STATUS.md AGENT_LOG.md && git commit -m "test: demonstrate container sandbox boundaries"`.
