# 613 Coding Product And Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Expose the shared Harness services through a usable CLI and WebUI, secure credentials and configuration, build reproducible distributions, and keep course delivery evidence current.

**Architecture:** Typer commands and FastAPI routes are thin adapters over `RunService`, `Supervisor`, `MemoryRepository`, and `CredentialService`. The WebUI displays event streams and approvals without implementing policy. Packaging, Docker, GitLab CI, and evidence files are verified as separate deliverables.

**Tech Stack:** Typer, FastAPI, Uvicorn, Jinja2/static HTML or a small typed frontend, Open Design for UI workflow, `uv`, Docker, GitLab CI, keyring, pytest HTTP client.

## Global Constraints

- CLI and WebUI share application services and contain no agent-loop or governance logic.
- Public WebUI runs only an example repository or isolated upload, never an arbitrary host path.
- Credential commands hide input and never display key material.
- CI includes a job named `unit-test`, runs offline tests and deterministic demos, and builds the distribution artifact.
- Every delivery change updates `AGENT_LOG.md`, `PLAN.md`, and `DELIVERY_STATUS.md` with fresh evidence.
- Before each task commit, append actual task evidence to `AGENT_LOG.md` and `DELIVERY_STATUS.md`; after the commit, update `PLAN.md` with the hash.

### Task 1: DELIVERY-01: Configuration And Credential Commands

**Files:**
- Create: `src/coding_harness/config.py`
- Create: `src/coding_harness/cli/credentials.py`
- Create: `src/coding_harness/cli/config.py`
- Test: `tests/cli/test_credentials.py`
- Test: `tests/config/test_config.py`

**Interfaces:** `load_config(repo_root) -> HarnessConfig`; `validate_config(config) -> None`; Typer commands `credentials set/status/update/clear` and `config check`.

- [ ] **Step 1: Write failing tests** for TOML parsing, argv validation, default mode, budget fields, path canonicalization, hidden key input, status redaction, and invalid configuration rejection.
- [ ] **Step 2: Run focused tests; expect missing CLI/config behavior.**
- [ ] **Step 3: Implement Pydantic/TOML configuration and keyring-backed commands using the core credential service.**
- [ ] **Step 4: Run tests while capturing output and assert no secret appears.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/config.py src/coding_harness/cli tests/cli tests/config && git commit -m "feat: add configuration and credential commands"`.

### Task 2: DELIVERY-02: Core CLI Run And Approval Commands

**Files:**
- Create: `src/coding_harness/cli/main.py`
- Create: `src/coding_harness/cli/runs.py`
- Test: `tests/cli/test_runs.py`

**Interfaces:** Commands `run task --repo PATH`, `runs status RUN_ID`, `runs events RUN_ID`, `runs approve APPROVAL_ID`, `runs reject APPROVAL_ID`, `runs resume RUN_ID`, `runs cancel RUN_ID`, and `demo core|sandbox|multi-agent`.

- [ ] **Step 1: Write failing Typer runner tests** with fake `RunService` for argument validation, JSON/table output, nonzero exit status, approval/resume, and demo dispatch.
- [ ] **Step 2: Run tests; expect missing command behavior.**
- [ ] **Step 3: Implement thin commands that serialize application results and never decide policy or completion.**
- [ ] **Step 4: Run CLI tests and manual `--help`; record exact output.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/cli tests/cli && git commit -m "feat: expose harness runs through cli"`.

### Task 3: DELIVERY-03: FastAPI API And Event Streaming

**Files:**
- Create: `src/coding_harness/api/app.py`
- Create: `src/coding_harness/api/schemas.py`
- Create: `src/coding_harness/api/routes/runs.py`
- Create: `src/coding_harness/api/routes/events.py`
- Test: `tests/api/test_runs_api.py`
- Test: `tests/api/test_events_api.py`

**Interfaces:** `create_app(services) -> FastAPI`; `POST /api/runs`; `GET /api/runs/{run_id}`; `GET /api/runs/{run_id}/events`; `POST /api/approvals/{approval_id}`; `POST /api/runs/{run_id}/resume`; `POST /api/runs/{run_id}/cancel`; `GET /healthz`.

- [ ] **Step 1: Write failing API tests** for request validation, shared service calls, event ordering, approval decisions, resume/cancel, health, and safe error responses.
- [ ] **Step 2: Run `uv run pytest tests/api -q`; expect missing app/routes.**
- [ ] **Step 3: Implement dependency-injected FastAPI routes and a bounded event polling/stream response; keep all decisions in application services.**
- [ ] **Step 4: Run API tests with fake services and assert no secrets in JSON.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/api tests/api && git commit -m "feat: expose harness services through api"`.

### Task 4: DELIVERY-04: WebUI With Open Design Workflow

**Files:**
- Create: `src/coding_harness/web/templates/index.html`
- Create: `src/coding_harness/web/static/app.js`
- Create: `src/coding_harness/web/static/styles.css`
- Create: `tests/web/test_web_assets.py`
- Modify: `README.md`

**Interfaces:** The UI consumes the API routes only. It must show task submission, Supervisor/worker states, timeline, feedback classification, approvals, changed files, validation evidence, and terminal stop reason.

- [ ] **Step 1: Write failing asset/API contract tests** for required labels, accessible approval actions, no key rendering, and event-state updates.
- [ ] **Step 2: Run tests; expect missing assets.**
- [ ] **Step 3: Use the Open Design skill to create/refine the information layout, then implement a restrained local operations UI that calls the API and handles loading/error/paused/completed states.**
- [ ] **Step 4: Run asset tests and browser smoke tests at desktop/mobile widths; verify no overlapping text and visible failure/approval states.**
- [ ] **Step 5: Commit.** `git add src/coding_harness/web tests/web README.md && git commit -m "feat: add harness operations webui"`.

### Task 5: DELIVERY-05: Package, Entry Points, And Docker Demonstration

**Files:**
- Modify: `pyproject.toml`
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `docker/entrypoint.sh`
- Create: `tests/test_distribution.py`

**Interfaces:** `uv tool install .` installs `coding-harness`; `coding-harness web --host 0.0.0.0 --port 8000` starts the API/UI; Docker starts the isolated demonstration configuration and documents its Docker Engine requirement.

- [ ] **Step 1: Write failing distribution tests** for package metadata, console entry points, Docker context exclusions, pinned base image, and health endpoint contract.
- [ ] **Step 2: Run tests; expect missing packaging/Docker files.**
- [ ] **Step 3: Implement package entry points, non-secret demo configuration, Dockerfile, non-root image user, and entrypoint. Do not mount a host Docker socket in the image by default; document the runtime requirement for worker containers.**
- [ ] **Step 4: Run `uv build`, `uv tool install .`, and `docker build`; start a local demo when Docker is available and verify `/healthz`.**
- [ ] **Step 5: Commit.** `git add pyproject.toml Dockerfile .dockerignore docker tests/test_distribution.py && git commit -m "build: package and containerize demonstration"`.

### Task 6: DELIVERY-06: GitLab CI And Evidence Automation

**Files:**
- Create: `.gitlab-ci.yml`
- Create: `scripts/record_delivery.py`
- Create: `scripts/__init__.py`
- Test: `tests/scripts/test_record_delivery.py`
- Modify: `AGENT_LOG.md`
- Modify: `DELIVERY_STATUS.md`

**Interfaces:** `python -m scripts.record_delivery --task ID --status STATUS --command COMMAND --result RESULT --commit HASH` appends structured evidence without inventing pass state. CI stages include `unit-test`, `lint`, `typecheck`, `demo`, and `build`.

- [ ] **Step 1: Write failing recorder tests** for append-only updates, Asia/Shanghai timestamps, command/result capture, commit validation, failure visibility, and idempotent status indexing.
- [ ] **Step 2: Run tests; expect missing recorder/CI files.**
- [ ] **Step 3: Implement the recorder as a narrow documentation utility; make `.gitlab-ci.yml` run offline tests, deterministic demos, lint/type checks, and distribution build.**
- [ ] **Step 4: Run the recorder tests, local CI-equivalent commands, and inspect generated records. Never write a pass result without command exit evidence.**
- [ ] **Step 5: Commit.** `git add .gitlab-ci.yml scripts tests/scripts AGENT_LOG.md DELIVERY_STATUS.md && git commit -m "ci: automate delivery evidence and checks"`.

### Task 7: DELIVERY-07: README, Deployment, And Final Evidence

**Files:**
- Modify: `README.md`
- Create: `docs/deployment.md`
- Modify: `DELIVERY_STATUS.md`
- Modify: `AGENT_LOG.md`
- Create: `REFLECTION.md` (student-authored content only)

**Interfaces:** Documentation must provide package/Docker acquisition, CLI/WebUI commands, keyring and `.env` safety, Docker and platform limitations, public-demo boundary, directory layout, CI/CD architecture, and the deployed URL once actually available.

- [ ] **Step 1: Write documentation checks** for required headings, install commands, security boundary, distribution commands, and rejection of an unverified deployment claim.
- [ ] **Step 2: Run checks; expect missing or incomplete documentation.**
- [ ] **Step 3: Write the documentation from verified commands and actual deployment evidence. Keep `REFLECTION.md` student-authored; AI may only help edit text with disclosure.**
- [ ] **Step 4: Run the complete offline suite, distribution checks, Docker smoke test, and final CI pipeline; record the last pipeline as pass only after observing it.**
- [ ] **Step 5: Update `PLAN.md`, `DELIVERY_STATUS.md`, and `AGENT_LOG.md` with every final evidence link.**
- [ ] **Step 6: Commit.** `git add README.md docs/deployment.md REFLECTION.md DELIVERY_STATUS.md AGENT_LOG.md PLAN.md && git commit -m "docs: complete distribution and delivery evidence"`.
