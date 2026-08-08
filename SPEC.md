# 613 Coding Specification

## 1. Problem Statement

613 Coding is a local Coding Agent Harness for developers who want a language-model-driven coding assistant without surrendering objective verification, permission control, auditability, or execution isolation. The user supplies a natural-language task and a local Git repository. The system reads repository context, calls an LLM through a controlled tool protocol, edits a task workspace, runs declared validation commands, classifies objective feedback, and continues or stops according to explicit state and budget rules.

The central engineering contribution is a deterministic feedback loop that remains testable after replacing the real LLM with a mock. Container isolation and multi-agent orchestration are complete supporting subsystems.

## 2. User Stories

1. As a developer, I can submit a task and a local repository path through the CLI.
2. As a developer, I can see tests, lint, and type-check results classified into actionable feedback.
3. As a safety-conscious developer, I can choose strict, balanced, or autonomous permissions.
4. As a developer, I can approve or reject a concrete risky action and resume the run.
5. As a developer, I can run worker agents in isolated containers with resource and network limits.
6. As a developer, I can ask a Supervisor to split work among planner, coder, tester, reviewer, and security workers.
7. As a returning user, I can retrieve project conventions, validation settings, decisions, task summaries, and failure patterns from SQLite and LanceDB.
8. As an evaluator, I can reproduce the feedback repair, guardrail, sandbox, multi-agent, and vector-memory demonstrations offline with a mock LLM.

## 3. Functional Specification

### 3.1 Run Lifecycle

Input: a task string, canonical local Git repository path, configuration, and permission mode.

Behavior: create a run, load repository instructions and relevant memory, enter the owned agent loop, persist every state transition, and expose pause/resume/cancel operations.

Output: terminal status, stop reason, changed-file summary, validation evidence, approvals, resource usage, and unresolved risks.

Errors: invalid repository, invalid configuration, cancelled run, unavailable provider, budget exhaustion, environment failure, or unrecoverable policy failure become explicit domain states rather than uncaught model messages.

### 3.2 Agent Loop And Tools

The loop accepts a versioned LLM response containing text and zero or more tool calls. Tool schemas cover `list_files`, `search_files`, `read_file`, `edit_file`, `git_diff`, `run_validation`, `request_approval`, and `finish`.

Every call is schema-validated, policy-checked, executed or rejected, persisted as events, and returned to the model. Independent read-only calls may run concurrently; writes and commands remain ordered. `finish` is accepted only after fresh required validation passes and no approval is pending.

### 3.3 Objective Feedback

Validators capture exit code, stdout, stderr, duration, resource exhaustion, and changed files. Deterministic classification produces `pass`, `test_failure`, `lint_failure`, `type_failure`, `environment_failure`, `timeout`, `resource_exhausted`, `policy_blocked`, `tool_error`, `invalid_action`, `merge_conflict`, or `no_progress`.

Interactive runs do not impose a low fixed five-turn limit. Configurable per-agent turns, total model calls, wall time, and provider cost budgets protect unattended operation. CI runs must set a finite call or cost budget. The mock demonstration explicitly uses five turns to test budget exhaustion and feedback repair.

### 3.4 Governance

Policy precedence is hard safety rules, validated repository configuration, permission mode, and one-time approval for the exact action. `strict` asks before writes/commands/external access; `balanced` permits repository edits and declared validation while asking for installs, network, repository-outside paths, and Git writes; `autonomous` permits declared in-scope actions but never bypasses hard denial rules.

Hard denial covers repository escape, symlink escape, destructive system/database/disk commands, Docker socket access, credential directories, privileged container changes, and unredacted secret transfer.

### 3.5 Memory

SQLite is authoritative for projects, runs, iterations, events, approvals, task graphs, artifacts, memory text, and embedding status. LanceDB stores redacted vectors linked by `memory_id`. Memory types are project conventions, validation configuration, governance decisions, task summaries, and failure patterns.

Retrieval embeds a query, filters LanceDB by project/type/permissions, retrieves top-k IDs, loads authoritative text from SQLite, applies a final permission filter, and injects a bounded result set. Real embedding failure falls back to SQLite full-text/keyword retrieval.

### 3.6 Container Sandbox

Each worker receives a temporary task workspace and a separate Docker container. Containers run non-root with read-only root filesystems, dropped capabilities, no network by default, pinned images, resource limits, output limits, and automatic cleanup. Workers never receive the Docker socket, host home, credentials, SSH agent, or writable original repository.

Only versioned work artifacts leave the container: patches, changed-file summaries, validation evidence, redacted logs, assumptions, and follow-up requests. The security claim is containment against ordinary tool mistakes and untrusted code impact, not protection against host kernel/runtime vulnerabilities.

### 3.7 Multi-Agent Orchestration

The Supervisor creates a dependency-aware `TaskGraph` and schedules planner, coder, tester, reviewer, and optional security workers. Each worker runs the same owned loop with role-specific policies, context, and sandbox. Workers return artifacts and never modify the host repository directly.

Independent read-only nodes may run concurrently. Overlapping write sets are serialized. The Supervisor applies artifacts in an integration workspace, retries one conflict replay, then emits `merge_conflict` and pauses if conflict remains.

### 3.8 Interfaces

The CLI is the complete local interface: run, status, events, approve, reject, resume, cancel, memory, credentials, demo, and WebUI startup. FastAPI exposes the same `RunService` for task creation, run events, task graph status, feedback, approvals, artifacts, and summaries.

The public WebUI runs only a packaged example repository or isolated uploaded copy and never accepts an arbitrary host path.

## 4. Non-Functional Requirements

- Python 3.12 or newer, dependencies and builds managed by `uv`.
- Core unit tests run offline with no real LLM, embedding service, Docker daemon, or API key after dependencies have been provisioned.
- First-time dependency provisioning is explicit: `uv sync --all-extras --frozen` may use a registry; an air-gapped environment must provide a populated uv cache or documented wheelhouse. `uv sync --all-extras --frozen --offline` fails fast with remediation when neither is available.
- Tool calls, state transitions, feedback, approvals, worker artifacts, and resource use are structured and auditable.
- Persisted output is redacted before storage; API keys never enter source, databases, logs, prompts, subprocess arguments, or containers.
- Subprocesses have explicit working directories, environment allowlists, timeouts, output caps, and resource limits.
- Interactive and unattended budgets are configurable and visible in run summaries.
- CLI and WebUI contain no business rules; both call the same application services.
- Docker images use pinned base-image digests and reproducible build inputs.

## 5. Architecture

The domain layer defines value objects, states, events, policies, task graphs, and interfaces without infrastructure imports. The application layer contains `AgentLoop`, `RunService`, `Supervisor`, context assembly, artifact integration, and credential use cases. Adapters implement OpenAI-compatible providers, mock providers, filesystem/subprocess tools, SQLite, LanceDB, keyring, Docker, CLI, and FastAPI.

The product does not use LangChain AgentExecutor, AutoGen, CrewAI, LlamaIndex agents, or a coding-agent SDK runner. It may use lower-level HTTP, parsing, persistence, and Docker libraries.

## 6. Data Model

Primary entities are `Project`, `Run`, `IterationRecord`, `Event`, `ApprovalRequest`, `TaskGraph`, `TaskNode`, `WorkArtifact`, and `MemoryEntry`.

`Project` identifies a canonical repository and configuration. `Run` belongs to a project and stores task, mode, budgets, status, and stop reason. `IterationRecord` belongs to a run and stores context summary, model response, tool calls, tool results, validation, feedback, and state transition. `TaskNode` belongs to a graph and stores dependencies, role, write set, retry budget, and state. `WorkArtifact` belongs to a node and stores patch, file list, evidence, assumptions, and integration state. `MemoryEntry` stores redacted text, type, project, permission tags, timestamps, and vector-index status.

## 7. Credentials And Distribution

The operating-system keyring is the primary key store. CLI commands hide entry and provide status/update/clear without revealing key material. `.env` is an explicit development fallback, must be ignored, and is documented as plaintext with process-environment exposure.

The project is distributed as a Python package installable through `uv tool install` and as a Docker image that starts the sandboxed demonstration WebUI. README must describe local CLI use, WebUI boundaries, Docker requirements, keyring setup, platform limits, and sandbox limitations. GitLab CI includes a `unit-test` job and builds the selected image.

## 8. Domain And Mechanism Design

Coding-domain feedback is test/lint/type-check output; dangerous actions are path escape, destructive commands, untrusted network/installation, credential access, and privileged container changes; tools are file/search/edit/validation/Git-diff/approval tools; memory is project conventions, validation settings, governance decisions, task summaries, and failure patterns.

Feedback classification is the main contribution because it is objective, deterministic, and directly changes future agent actions. Sandbox and Supervisor are separate ports so their behavior remains independently testable with fake runtimes and mock workers.

## 9. Testing And Mechanism Demonstration

Unit tests cover loop transitions, tool schemas, policy, approvals, classifiers, no-progress detection, budgets, SQLite/LanceDB retrieval, credentials, task scheduling, artifacts, and sandbox lifecycle. Integration tests use temporary Git repositories and controlled subprocess/container fixtures.

The initial package-scaffold test uses only the Python standard-library `unittest` runner so a fresh environment can verify the source layout before third-party development tools are installed. Pydantic, pytest, Ruff, mypy, FastAPI, LanceDB, Docker, and provider adapters begin only after the documented dependency-provisioning check succeeds.

The offline demo must reproduce: planner task graph creation; wrong coder patch; tester `test_failure`; feedback-driven repair; reviewer approval; Supervisor integration; dangerous-action blocking; strict/balanced/autonomous differences; vector-memory retrieval; and worker cleanup. A real LLM run is supplementary evidence only.

## 10. Acceptance Criteria

The project is accepted when the owned loop runs with a mock LLM, objective failure feedback changes the next action, all core mechanisms have deterministic tests, governance and approval are enforced, workers run in isolated containers, Supervisor integrates versioned artifacts, SQLite and LanceDB persistence/retrieval work with fallback, CLI and WebUI share `RunService`, credentials remain out of persisted output, `uv` installation and Docker demo work, GitLab `unit-test` passes, and delivery records trace each completed plan task to a commit and fresh verification output.

## 11. Risks And Scope Boundaries

Model output differences are controlled by schema validation and bounded feedback. Generic command risk is controlled by argv configuration, policies, resource limits, and containers. LanceDB is rebuildable from SQLite. Multi-agent conflict is explicit rather than silently merged. Docker does not guarantee kernel-level isolation.

The first release does not implement GitHub/GitLab PR automation, arbitrary public-host filesystem access, a hierarchy of supervisors, or language-specific AST analyzers for every language.
