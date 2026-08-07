# AGENTS.md

## Project

This repository builds **613 Coding**, a Python Coding Agent Harness for local Git repositories. The product owns its agent loop, tool dispatch, governance, objective feedback, memory, container sandbox, and multi-agent orchestration.

The main engineering contribution is the deterministic feedback loop. Container isolation and multi-agent orchestration are required, complete supporting subsystems, but they must not dilute the feedback-loop depth.

## Sources Of Truth

Use this precedence when instructions conflict:

1. The current user request.
2. `AI4SE_Final_Project_通用要求.md` and `AI4SE_Final_Project_A_Coding_Agent_Harness(1).md`.
3. Approved `SPEC.md`.
4. Approved `PLAN.md`.
5. This `AGENTS.md`.
6. Existing code conventions and local documentation.

Record any justified deviation from the course workflow in `AGENT_LOG.md` with the reason and resulting evidence.

## Current Phase Gate

The approved brainstorming design is stored at:

`docs/superpowers/specs/2026-08-07-613-coding-design.md`

Do not write implementation code until all of the following are complete:

- `SPEC.md` is approved.
- `PLAN.md` is approved.
- `SPEC_PROCESS.md` records the required brainstorming iterations.
- A different agent type has cold-started 1-2 plan tasks using only `SPEC.md` and `PLAN.md`.
- Defects found by the cold-start trial are incorporated into the spec and plan.

Documentation and planning changes are allowed during this phase.

## Required Superpowers Workflow

Follow the workflow in this order:

1. `brainstorming`
2. `writing-plans`
3. `using-git-worktrees`
4. `subagent-driven-development` or `executing-plans`
5. `test-driven-development`
6. `requesting-code-review`
7. `finishing-a-development-branch`

Use `verification-before-completion` before claiming a task is complete or passing. Use `systematic-debugging` before proposing fixes for bugs or failing tests.

If a relevant skill exists, load and follow it before acting. Keep skill use, key prompts, subagent outputs, commit hashes, human interventions, and lessons in `AGENT_LOG.md`.

## Product Invariants

- Implement the agent loop in this repository. Do not use LangChain `AgentExecutor`, AutoGen, CrewAI, LlamaIndex agents, a coding-agent SDK runner, or another high-level agent loop.
- LLM integrations may use only lower-level single-call or tool-call APIs behind `LLMProvider`.
- Every core dependency must be injectable so it can be replaced by a mock or fake.
- A real LLM is never required for unit tests.
- Tool calls use versioned, validated schemas.
- The LLM cannot bypass policy, declare validation success, or decide that a dangerous action is safe.
- Objective validators and deterministic classifiers control feedback and completion.
- `finish` succeeds only after required validation is fresh and passing.
- SQLite is the source of truth for structured state and memory text.
- LanceDB is a rebuildable vector index, never the source of truth.
- API keys never enter Git, SQLite, LanceDB, logs, events, prompts, subprocess arguments, or worker containers.

## Architecture Boundaries

Keep these responsibilities separate:

- `domain`: value objects, states, events, policies, and interfaces with no infrastructure imports.
- `application`: `AgentLoop`, `RunService`, `Supervisor`, context assembly, artifact integration, and use cases.
- `ports`: LLM, embedding, tools, policy, validators, memory, events, sandbox, and artifact interfaces.
- `adapters`: OpenAI-compatible APIs, mock providers, filesystem, subprocess, SQLite, LanceDB, keyring, Docker, CLI, and FastAPI.

Do not let CLI or WebUI contain business rules. Both must call the same application services.

Prefer focused modules with explicit interfaces over large manager classes. Do not add an abstraction unless it protects a real boundary or removes meaningful duplication.

## Agent Loop Rules

The loop must make every state transition explicit and persist an `IterationRecord` containing:

- input context summary;
- model response and tool calls;
- schema validation result;
- policy decision;
- tool result;
- validation output;
- feedback classification;
- state transition and stop reason.

Supported runtime states include `RUNNING`, `WAITING_MODEL`, `WAITING_APPROVAL`, `COMPLETED`, `PAUSED`, `FAILED`, and `CANCELLED`.

Read-only independent tool calls may run concurrently. Writes, commands, approvals, artifact integration, and overlapping file changes must remain ordered.

Do not hard-code a five-turn product limit. Interactive runs continue until an objective terminal condition, user action, or configured safety budget. Support separate limits for per-agent turns, total model calls, wall-clock time, and provider cost. Unattended and CI runs must configure at least one finite model-call or cost budget. Deterministic tests may use a five-turn budget to exercise exhaustion behavior.

## Feedback Loop Rules

Treat feedback classification as the primary contribution. At minimum support:

- `pass`
- `test_failure`
- `lint_failure`
- `type_failure`
- `environment_failure`
- `timeout`
- `resource_exhausted`
- `policy_blocked`
- `tool_error`
- `invalid_action`
- `merge_conflict`
- `no_progress`

Classifiers must be deterministic code using command type, exit code, resource status, and parsed output. Do not ask an LLM to classify correctness.

Test repeated failures, stale validation, invalid actions, no file changes, retry exhaustion, approval rejection, and successful recovery.

## Governance Rules

Policy precedence is:

1. Hard safety rules.
2. Validated `harness.toml` policy.
3. `strict`, `balanced`, or `autonomous` mode.
4. One-time user approval for the exact action.

Hard rules cannot be bypassed by autonomous mode or user-provided memory. Reject repository escape through absolute paths, `..`, symlinks, or mount tricks.

Use argv arrays for configured validation commands. Avoid `shell=True`. If shell behavior is explicitly required, route it through policy and approval and test the exact boundary.

Set subprocess working directory, timeout, output cap, resource limits, and an environment allowlist. Redact before persistence, not only at display time.

## Sandbox Rules

Each product worker runs in its own short-lived container and task workspace.

- Run as non-root.
- Use a read-only root filesystem.
- Drop all Linux capabilities by default.
- Disable network by default.
- Limit CPU, memory, PIDs, disk, command time, and output size.
- Never mount the Docker socket, SSH agent, user home, credential directories, or the original repository as writable.
- Use pinned base images or image digests.
- Export only versioned `WorkArtifact` data.
- Remove containers and temporary volumes after terminal states.

The Supervisor may access the Docker Engine API, but worker containers may not. Document that the sandbox mitigates ordinary untrusted-code impact and does not guarantee protection from kernel or runtime vulnerabilities.

## Multi-Agent Rules

The product topology is Supervisor plus role-specific workers:

- `planner`: read-only task graph creation.
- `coder`: scoped code changes.
- `tester`: failure reproduction and verification.
- `reviewer`: spec and quality review.
- `security`: dependency, secret, policy, and sandbox checks.

Every worker uses the same owned `AgentLoop` with a role-specific policy and context. Workers do not directly edit the host repository or share hidden mutable state.

Workers return versioned `WorkArtifact` objects containing a patch, changed files, summary, verification evidence, assumptions, and follow-up requests. The Supervisor integrates artifacts in a controlled workspace and reruns validation.

Parallelize only dependency-independent work. Serialize tasks with overlapping write sets. Never silently resolve merge conflicts or overwrite user changes.

Do not confuse product runtime agents with development subagents used by Superpowers. Development subagents follow `PLAN.md`, use isolated worktrees, and produce commits/PR evidence.

## Memory And Data

SQLite stores projects, runs, iterations, events, approvals, task graphs, artifact metadata, memory text, and embedding status.

LanceDB stores redacted vectors linked by `memory_id`. Recover authoritative text and permissions from SQLite after vector search.

Memory categories are `project_convention`, `validation_config`, `governance_decision`, `task_summary`, and `failure_pattern`.

Provide deterministic mock embeddings for tests. If real embeddings fail, fall back to SQLite full-text or keyword retrieval without blocking the basic agent loop.

Never embed secrets, full environment dumps, or unredacted command output.

## Credentials

Use the operating-system keyring as the primary API-key store. Support hidden entry, status, update, and clear operations. Status output must not reveal key material.

`.env` is an explicit development fallback only. It must be ignored by Git, must never be copied into images, and must be documented as plaintext with process-environment exposure risk.

Never put secrets in source, tests, fixtures, prompts, screenshots, CI variables committed to the repository, terminal commands, or logs.

## Python And Tooling

Use Python managed by `uv`. Once the package scaffold exists, the canonical local commands are:

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run mypy src
```

Keep runtime and development dependencies declared in `pyproject.toml` and locked with `uv.lock`. Do not introduce a second Python dependency manager.

Prefer typed models and validated schemas. Keep public interfaces type-checked. Use concise comments only for non-obvious invariants.

## TDD And Testing

TDD is mandatory for every feature and bug fix:

1. Write a focused failing test.
2. Run it and capture the expected failure.
3. Write the minimum implementation to pass.
4. Run the focused test.
5. Refactor while green.
6. Run the relevant suite.

Do not write implementation first and backfill tests.

The test suite must run without network access and without a real LLM. Use mock LLMs, fake tools, deterministic embeddings, temporary Git repositories, temporary databases, and controlled sandbox fixtures.

Required coverage includes the loop, tool dispatch, policy, approval resume, feedback classification, no-progress detection, SQLite/LanceDB behavior, sandbox lifecycle, task graph scheduling, artifact integration, credential mocks, CLI, and API.

The deterministic mechanism demo must reproduce wrong patch, failed validation, feedback-driven repair, successful validation, dangerous-action blocking, permission-mode differences, vector-memory retrieval, and Supervisor/worker handoff.

## Git And Delivery Workflow

- Use one worktree and one PR per independent feature or major module.
- Use one fresh development subagent per `PLAN.md` task where the workflow requires it.
- Perform spec-compliance review before code-quality review.
- Fix Critical issues before moving to the next task.
- Update `PLAN.md` after each task and include the commit hash.
- Identify the subagent and human edits in commit messages or PR descriptions.
- Preserve unrelated user changes and never silently overwrite them.

Do not use destructive Git commands unless the user explicitly requests them.

## Automatic Delivery Evidence

Treat delivery records as part of every task, not as end-of-project paperwork. After each significant action, update the appropriate record file with evidence from the current session:

- `AGENT_LOG.md`: append a timestamp in `Asia/Shanghai`, task ID, triggered skill, important prompt/context configuration, subagent output or commit hash, human intervention, and lesson learned.
- `PLAN.md`: when a task finishes, update its status, verification command and result, and commit hash. Do not mark a task complete from a plan or model report alone.
- `SPEC_PROCESS.md`: after brainstorming, cold-start validation, or a spec revision, record the question, decision, uncertainty exposed, and the meaningful before/after diff.
- `DELIVERY_STATUS.md`: update the delivery checklist, current status, last verification timestamp, responsible actor, and links to source evidence. Include the latest CI/CD pipeline and job result here.

Record failures, pauses, rejected approvals, user edits, and workflow deviations as well as successful actions. Do not fabricate evidence, paraphrase an unrun command as passing, or replace a required source record with `DELIVERY_STATUS.md`; the summary file is an index, not the source of truth.

When a task changes code, documentation, configuration, tests, CI, distribution, credentials, or deployment, update the relevant record in the same task before handing it off for review. A reviewer must be able to trace every completed PLAN task to a commit and fresh verification output.

## CI And Distribution

GitLab CI must include a job named `unit-test`. CI must run the offline unit suite and deterministic mechanism demo. It must also build the selected distribution artifact.

Provide both:

- a Python package installable through the documented `uv tool install` path;
- a Docker image that starts the sandboxed demonstration WebUI.

README must document installation, local CLI use, WebUI use, Docker requirements, keyring setup, `.env` risks, supported platforms, sandbox limits, and public-demo boundaries.

## Required Project Documents

Maintain these files as first-class deliverables:

- `SPEC.md`
- `PLAN.md`
- `SPEC_PROCESS.md`
- `AGENT_LOG.md`
- `DELIVERY_STATUS.md`
- `README.md`
- `REFLECTION.md`
- `.gitlab-ci.yml`

The student's reflection must remain student-authored. AI may assist with editing only when that assistance is disclosed.

## Definition Of Done

A task is not done until:

- its acceptance criteria are met;
- its required failing test was observed before implementation;
- focused and relevant test suites pass;
- deterministic mechanisms remain independent of real LLMs and network access;
- security and credential boundaries are preserved;
- spec-compliance and code-quality reviews have no unresolved Critical issues;
- verification evidence is recorded;
- `PLAN.md` and `AGENT_LOG.md` are updated when applicable.

Never claim completion based only on model output, code inspection, or an unexecuted command.
