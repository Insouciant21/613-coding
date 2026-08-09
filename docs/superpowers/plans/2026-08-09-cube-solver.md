# 613 Cube Solver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use 613 Coding to build a local Docker Compose application in `tmp/cube` that edits, validates, renders, and solves Rubik's Cubes from 2x2 through 7x7.

**Architecture:** A React/TypeScript/Three.js frontend owns editing and playback state. A `uv`-managed FastAPI service owns authoritative validation, asynchronous jobs, a pinned NxNxN solver subprocess, lookup-table caching, and replay verification. Nginx exposes one same-origin endpoint on `127.0.0.1:6131` and proxies `/api` to the API container.

**Tech Stack:** Node.js 22, npm workspaces, React, TypeScript, Vite, Three.js through `@react-three/fiber`, `cubing.js`, Vitest, Testing Library, Playwright, Python 3.12, uv, FastAPI, Pydantic, pytest, Docker Compose, Nginx, `rubiks-cube-NxNxN-solver`, and Kociemba.

## Global Constraints

- Product implementation must be authored through `613-coding run task` and `613-coding runs resume`; the controller may create only `tmp/cube`, Git metadata, `.gitignore`, and `harness.toml` before the first run.
- Do not create `PLAN.md`, `SPEC.md`, `DELIVERY_STATUS.md`, `SPEC_PROCESS.md`, or a delivery-recording script inside `tmp/cube`.
- `tmp/cube/AGENT_LOG.md` is the sole process file. The controller writes only actual 613 Coding prompts, commands, run IDs, terminal states, event summaries, and independent verification results; 613 Coding workers must not edit it.
- Product-facing `README.md`, third-party notices, tests, screenshots, lockfiles, and ordinary source documentation are allowed.
- Support complete editing, validation, solving, and playback for every order from 2 through 7.
- Use the standard palette: U white, L orange, F green, R red, B blue, D yellow.
- A legal adjacent front/top pair defines one of exactly 24 output orientations.
- Show WCA notation and a Chinese explanation for every move, including wide and multi-layer turns.
- Return success only after replaying the solution from the submitted state to six uniform faces.
- Pin the NxNxN solver to `c776db79314db3d98cc3dd99685ca85766656937` and Kociemba to `64fd123bd9cc21d058b37a66473a2fe1807b6dad`.
- Download lookup tables lazily into the `solver-data` volume using atomic files and pinned-format validation.
- Default to one concurrent solve and a 30-minute timeout controlled by `SOLVER_TIMEOUT_SECONDS`.
- Keep cube states local; do not call a hosted solver or store states in a server-side database.
- Publish only `127.0.0.1:6131`; keep the API behind the same-origin web proxy.
- Preserve the original painted state while solution playback uses a separate state copy.
- Require test-first changes in each 613 Coding batch and independently verify every batch before starting the next one.

## File Map

```text
tmp/cube/
  harness.toml                      613 Coding provider, policy, validation, and budget metadata
  AGENT_LOG.md                      Controller-owned log of actual 613 Coding operations
  package.json                      npm workspace and root verification scripts
  README.md                         Product operation and troubleshooting guide
  THIRD_PARTY_NOTICES.md            Pinned solver source and license notices
  compose.yaml                      Same-origin web/API deployment and solver-data volume
  scripts/verify.sh                 Deterministic local verification entry point
  apps/web/src/cube/state.ts        Canonical editable sticker state and history operations
  apps/web/src/cube/moves.ts        NxN move parsing and sticker permutations
  apps/web/src/cube/orientation.ts  Front/top frame mapping
  apps/web/src/cube/notation.ts     WCA normalization and Chinese descriptions
  apps/web/src/scene/geometry.ts    Pure cubie/sticker geometry descriptors
  apps/web/src/scene/CubeScene.tsx  Three.js scene, picking, orbiting, and animation
  apps/web/src/features/editor/     Workbench controls and state diagnostics
  apps/web/src/features/solver/     Job client, progress, formula, and playback controls
  apps/api/src/cube_api/schemas.py  Stable API request/result/error models
  apps/api/src/cube_api/cube/       Orientation, structural validation, and replay verification
  apps/api/src/cube_api/solver/     Lookup cache, pinned bridge, subprocess, and job queue
  apps/api/src/cube_api/routes.py   Health, solve, SSE, and cancel routes
  docker/solver_bridge.py           JSON-only adapter around the pinned upstream solver
  docker/api.Dockerfile             uv API plus pinned native solver build
  docker/web.Dockerfile             Vite build served by unprivileged Nginx
  docker/nginx.conf                 Static assets and `/api` proxy
  tests/fixtures/                   Legal and invalid states for orders 2 through 7
  tests/e2e/                        Desktop/mobile browser workflows and screenshots
```

---

### Task 1: Bootstrap The 613 Coding Runtime

**Files:**
- Create manually: `tmp/cube/.gitignore`
- Create manually: `tmp/cube/harness.toml`
- Create manually: `tmp/cube/AGENT_LOG.md`

**Interfaces:**
- Consumes: local `613-coding` CLI and an OpenAI-compatible credential named `openai`.
- Produces: an otherwise empty target Git repository accepted by `613-coding config check`.

- [ ] **Step 1: Create the empty target repository**

```bash
cd /home/int21/Workspace/ai4se_project
mkdir -p tmp/cube
git -C tmp/cube init -b main
```

- [ ] **Step 2: Create the exact harness configuration**

```toml
[policy]
mode = "autonomous"
validation_commands = [["bash", "scripts/verify.sh"]]
allow_network = true
allow_dependency_install = true
allow_git_writes = true
allow_writes = true

[budgets]
per_agent_turns = 30
total_model_calls = 30
wall_time_seconds = 7200.0
unattended = true

[llm]
provider = "openai-compatible"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
credential = "openai"
timeout_seconds = 120.0
```

`.gitignore` must contain `.613-coding/`, `.env`, `.venv/`, `node_modules/`, `dist/`, `test-results/`, `playwright-report/`, `.pytest_cache/`, and lookup-table files.

Initialize the controller-owned log as:

```markdown
# 613 Coding Operation Log

This file records commands actually run by the controller. Entries are append-only. A failed run remains visible after any later recovery.
```

- [ ] **Step 3: Verify configuration and credential availability**

```bash
uv run 613-coding config check --repo tmp/cube
uv run 613-coding credentials status openai
```

Expected: configuration exits 0; credential status reports configured without displaying secret material. If the Keyring backend or credential is unavailable, stop before creating a run and use the manual handoff commands supplied with execution.

- [ ] **Step 4: Commit only the runtime bootstrap**

```bash
git -C tmp/cube add .gitignore harness.toml AGENT_LOG.md
git -C tmp/cube commit -m "chore: bootstrap 613 coding target"
```

### Task 2: Ask 613 Coding To Scaffold The Tested Web/API Foundation

**Files:**
- Create through 613 Coding: `tmp/cube/package.json`
- Create through 613 Coding: `tmp/cube/apps/web/package.json`
- Create through 613 Coding: `tmp/cube/apps/web/src/App.tsx`
- Create through 613 Coding: `tmp/cube/apps/web/src/App.test.tsx`
- Create through 613 Coding: `tmp/cube/apps/api/pyproject.toml`
- Create through 613 Coding: `tmp/cube/apps/api/src/cube_api/main.py`
- Create through 613 Coding: `tmp/cube/apps/api/tests/test_health.py`
- Create through 613 Coding: `tmp/cube/scripts/verify.sh`

**Interfaces:**
- Produces: `cube_api.main:create_app() -> FastAPI`, `GET /api/health -> {"status":"ok"}`, Vite app heading `613 Cube Solver`, and root verification commands.

- [ ] **Step 1: Start the bounded 613 Coding run with this exact task**

```text
Create the tested foundation for 613 Cube Solver. Use npm workspaces with a React TypeScript Vite app in apps/web and a Python 3.12 FastAPI package managed only by uv in apps/api. Use TDD: first add failing tests for a visible heading named "613 Cube Solver" and GET /api/health returning exactly {"status":"ok"}, run them to observe failure, then implement the minimum foundation. Add scripts/verify.sh using set -euo pipefail to run frontend tests, lint, typecheck, build and API pytest, Ruff, and mypy. Do not create planning or delivery files and do not edit the controller-owned AGENT_LOG.md. Do not implement cube behavior yet. Run focused tests and commit the result.
```

- [ ] **Step 2: Resume the run and inspect its terminal state**

```bash
RUN_ID="$(uv run 613-coding run task "Create the tested foundation for 613 Cube Solver. Use npm workspaces with a React TypeScript Vite app in apps/web and a Python 3.12 FastAPI package managed only by uv in apps/api. Use TDD: first add failing tests for a visible heading named 613 Cube Solver and GET /api/health returning exactly status ok, run them to observe failure, then implement the minimum foundation. Add scripts/verify.sh using set -euo pipefail to run frontend tests, lint, typecheck, build and API pytest, Ruff, and mypy. Do not create planning or delivery files and do not edit AGENT_LOG.md. Do not implement cube behavior yet. Run focused tests and commit the result." --repo tmp/cube --json | jq -r '.id')"
uv run 613-coding runs resume "$RUN_ID" --repo tmp/cube --json
uv run 613-coding runs events "$RUN_ID" --repo tmp/cube --json
```

- [ ] **Step 3: Independently verify the batch**

```bash
cd tmp/cube
npm test --workspace apps/web -- --run src/App.test.tsx
uv run --project apps/api pytest apps/api/tests/test_health.py -q
npm run typecheck --workspace apps/web
uv run --project apps/api ruff check apps/api
uv run --project apps/api mypy apps/api/src
```

Expected: all commands pass, no forbidden planning/delivery file exists, and the worker did not edit `AGENT_LOG.md`.

### Task 3: Ask 613 Coding To Implement Cube State, Moves, And Orientation

**Files:**
- Create through 613 Coding: `tmp/cube/apps/web/src/cube/types.ts`
- Create through 613 Coding: `tmp/cube/apps/web/src/cube/palette.ts`
- Create through 613 Coding: `tmp/cube/apps/web/src/cube/state.ts`
- Create through 613 Coding: `tmp/cube/apps/web/src/cube/moves.ts`
- Create through 613 Coding: `tmp/cube/apps/web/src/cube/orientation.ts`
- Create through 613 Coding: `tmp/cube/apps/web/src/cube/notation.ts`
- Create through 613 Coding: `tmp/cube/apps/api/src/cube_api/cube/orientation.py`
- Create through 613 Coding: `tmp/cube/apps/api/src/cube_api/cube/replay.py`
- Create through 613 Coding: `tmp/cube/tests/fixtures/orientation_vectors.json`

**Interfaces:**
- Produces: immutable `CubeState`; `createSolvedCube`, `paintSticker`, undo/redo/reset/persistence; 24 orientations; WCA move parsing/application; Chinese descriptions; Python `replay(...) -> ReplayResult`.

- [ ] **Step 1: Start a 613 Coding run with this exact task**

```text
Implement the cube domain using TDD. Support orders 2 through 7 with canonical face order U,L,F,R,B,D and colors white,orange,green,red,blue,yellow. Add immutable editing state with revision, 200-entry undo/redo history, reset, per-order localStorage validation, and no mutation of prior snapshots. Implement all 24 adjacent front/top orientations. Implement coordinate-based NxN sticker permutations and parse outer, wide, numeric multi-layer, inverse, half-turn, and x/y/z notation. Generate Chinese descriptions; 3Rw' must mean 右侧三层逆时针旋转 90 度. Implement equivalent Python orientation and replay behavior. Both languages must consume one JSON vector file covering all 24 frames and representative moves. Write failing tests first, then implementation, run focused tests/typechecks, and commit. Do not create planning or delivery files and do not edit AGENT_LOG.md.
```

- [ ] **Step 2: Resume and review the run**

Run `613-coding run task` with the Step 1 text, extract `.id`, then run `613-coding runs resume`, `runs status`, and `runs events` against `tmp/cube`.

- [ ] **Step 3: Verify domain invariants**

```bash
npm test --workspace apps/web -- --run src/cube
uv run --project apps/api pytest apps/api/tests/test_orientation_replay.py -q
npm run typecheck --workspace apps/web
uv run --project apps/api mypy apps/api/src
```

Expected: all six orders and all 24 orientations pass; four quarter-turns restore each tested state.

### Task 4: Ask 613 Coding To Implement Validation And Solver Boundaries

**Files:**
- Create through 613 Coding: `tmp/cube/apps/api/src/cube_api/schemas.py`
- Create through 613 Coding: `tmp/cube/apps/api/src/cube_api/cube/diagnostics.py`
- Create through 613 Coding: `tmp/cube/apps/api/src/cube_api/cube/validation.py`
- Create through 613 Coding: `tmp/cube/apps/api/src/cube_api/solver/cache.py`
- Create through 613 Coding: `tmp/cube/apps/api/src/cube_api/solver/process.py`
- Create through 613 Coding: `tmp/cube/docker/solver_bridge.py`
- Create through 613 Coding: `tmp/cube/tests/fixtures/invalid_states.json`

**Interfaces:**
- Produces: bounded `SolveRequest`; stable `Diagnosis`; `ValidationReport`; `SolveResult`; atomic `LookupCache`; cancellable `SolverProcess`; JSON-only pinned solver bridge.

- [ ] **Step 1: Start a 613 Coding run with this exact task**

```text
Implement authoritative validation and the external solver boundary using TDD. SolveRequest accepts only order 2 through 7, exactly 6*N*N ULFRBD facelets, adjacent front/top, and a revision. Diagnostics need stable codes and Chinese messages with sticker coordinates only when exact. Validate color counts, odd fixed centers, unique corners, corner twist, wing/edge orbits, edge orientation, center orbit counts, and applicable parity. Add fake-based tests for every error category and every order. Implement an atomic lookup cache: HTTPS into .part, successful decompression, pinned expected record count/width, rename only after validation, cleanup on interruption. Implement a subprocess adapter using argv, shell=False, new process session, bounded output, temporary task directory, 1800-second default timeout, process-group cancellation, and JSON parsing. docker/solver_bridge.py must wrap NxNxN solver commit c776db79314db3d98cc3dd99685ca85766656937, remove comment markers, replay upstream output, and print one JSON result. Definitive reduction errors are invalid; timeout/download/process errors are operational. Write failing tests first, run pytest/Ruff/mypy, and commit. Do not download real lookup tables in unit tests. Do not create planning or delivery files and do not edit AGENT_LOG.md.
```

- [ ] **Step 2: Resume and review the run**

Run the standard `run task -> runs resume -> runs status -> runs events` sequence with the Step 1 text.

- [ ] **Step 3: Verify validation and process safety**

```bash
uv run --project apps/api pytest apps/api/tests/test_validation.py apps/api/tests/test_solver_cache.py apps/api/tests/test_solver_process.py -q
uv run --project apps/api ruff check apps/api docker/solver_bridge.py
uv run --project apps/api mypy apps/api/src
```

Expected: all fake-based checks pass without network access or a real solver process.

### Task 5: Ask 613 Coding To Implement Jobs And API Streaming

**Files:**
- Create through 613 Coding: `tmp/cube/apps/api/src/cube_api/solver/jobs.py`
- Create through 613 Coding: `tmp/cube/apps/api/src/cube_api/routes.py`
- Modify through 613 Coding: `tmp/cube/apps/api/src/cube_api/main.py`

**Interfaces:**
- Produces: `POST /api/solve`, `GET /api/jobs/{id}/events`, `DELETE /api/jobs/{id}`, FIFO concurrency one, SSE sequence numbers, cancellation, and replay-verified terminal results.

- [ ] **Step 1: Start a 613 Coding run with this exact task**

```text
Implement asynchronous solve jobs and FastAPI routes using TDD. POST /api/solve performs bounded schema validation and returns a job id. GET /api/jobs/{id}/events streams SSE states queued, validating, downloading, reducing, solving, verifying, completed, cancelled, or failed with monotonic sequence numbers and Chinese status. DELETE cancels the entire solver process group. Default concurrency is one with FIFO queueing. Keep at most 100 completed in-memory jobs and never persist facelets. Validate before invoking solver; orientation-map output, normalize WCA moves, generate per-token Chinese explanations, replay from the exact request, and only then return verified=true, move_count, elapsed_seconds, front, top, revision, moves, and explanations. Distinguish INVALID_STATE, TABLE_DOWNLOAD_FAILED, SOLVER_TIMEOUT, SOLVER_UNAVAILABLE, CANCELLED, and INTERNAL_ERROR. Test queue order, invalid bypass, SSE, disconnect, cancellation, timeout, stale revision echo, and replay failure. Run pytest/Ruff/mypy and commit. Do not create planning or delivery files and do not edit AGENT_LOG.md.
```

- [ ] **Step 2: Resume and review the run**

Run the standard 613 Coding sequence with the Step 1 text.

- [ ] **Step 3: Verify job and API contracts**

```bash
uv run --project apps/api pytest apps/api/tests/test_jobs.py apps/api/tests/test_routes.py -q
uv run --project apps/api ruff check apps/api
uv run --project apps/api mypy apps/api/src
```

Expected: lifecycle, progress, cancellation, and error tests pass.

### Task 6: Ask 613 Coding To Build The Three.js Editing Workbench

**Files:**
- Create through 613 Coding: `tmp/cube/apps/web/src/scene/geometry.ts`
- Create through 613 Coding: `tmp/cube/apps/web/src/scene/CubeScene.tsx`
- Create through 613 Coding: `tmp/cube/apps/web/src/features/editor/EditorWorkbench.tsx`
- Create through 613 Coding: `tmp/cube/apps/web/src/features/editor/Palette.tsx`
- Create through 613 Coding: `tmp/cube/apps/web/src/features/editor/OrientationControls.tsx`
- Create through 613 Coding: `tmp/cube/apps/web/src/features/editor/Diagnostics.tsx`
- Modify through 613 Coding: `tmp/cube/apps/web/src/App.tsx`
- Create through 613 Coding: `tmp/cube/apps/web/src/styles.css`

**Interfaces:**
- Produces: full-bleed pickable cube for orders 2 through 7, drag/orbit/zoom, paint threshold, animated layer groups, approved desktop layout A, and mobile tool drawer.

- [ ] **Step 1: Start a 613 Coding run with this exact task**

```text
Build the editable Three.js workbench using TDD. Use React, TypeScript, @react-three/fiber, drei orbit controls, and Lucide icons. Pure geometry tests must prove exactly 6*N*N stable sticker ids and no duplicate surface positions for orders 2-7. The full-bleed scene must fit every order, bound zoom, reset camera, reuse/dispose resources, paint only when pointer movement stays below 5 CSS pixels, and rotate a temporary layer group for playback. Implement approved layout A: compact top bar, large unframed 3D scene, fixed right editor, stable bottom result strip; on mobile use a bottom drawer without covering playback. Add six color+letter/name swatches, undo/redo, solved reset, edited-order confirmation, front/top selectors restricted to adjacent faces, diagnostics linked to exact stickers, tooltips and accessible labels. Avoid nested cards, decorative gradients, overlaps, and color-only meaning. Write failing geometry/component tests first, run tests/typecheck/lint/build, and commit. Do not create planning or delivery files and do not edit AGENT_LOG.md.
```

- [ ] **Step 2: Resume and review the run**

Run the standard 613 Coding sequence with the Step 1 text.

- [ ] **Step 3: Verify the frontend batch**

```bash
npm test --workspace apps/web -- --run src/scene src/features/editor
npm run typecheck --workspace apps/web
npm run lint --workspace apps/web
npm run build --workspace apps/web
```

Expected: geometry, editor workflow, typecheck, lint, and production build pass.

### Task 7: Ask 613 Coding To Connect Solving And Playback

**Files:**
- Create through 613 Coding: `tmp/cube/apps/web/src/api/client.ts`
- Create through 613 Coding: `tmp/cube/apps/web/src/features/solver/useSolveJob.ts`
- Create through 613 Coding: `tmp/cube/apps/web/src/features/solver/SolvePanel.tsx`
- Create through 613 Coding: `tmp/cube/apps/web/src/features/solver/PlaybackControls.tsx`
- Create through 613 Coding: `tmp/cube/apps/web/src/features/solver/playback.ts`

**Interfaces:**
- Produces: solve submission, SSE progress, stale-revision rejection, immutable playback snapshots, clickable formula, copy, previous/next, autoplay/pause, speed, cancellation, retry, and replace-edit-state command.

- [ ] **Step 1: Start a 613 Coding run with this exact task**

```text
Connect the frontend to solve jobs and implement formula playback using TDD. Submit order, facelets, front, top, and revision. Close EventSource on edit, cancellation, unmount, or terminal event and ignore results for a stale revision. Preserve the painted input; build a separate playback state with cached snapshots, current index, playing flag, and speed 0.5/1/1.5/2. Render the complete WCA formula with individually clickable active tokens and Chinese explanations. Implement copy, previous, next, play/pause, speed, cancel, retry, and an explicit command to replace the edit state with settled playback state. Show invalid diagnostics separately from table download, timeout, unavailable, cancellation, and internal errors. Use mocked REST/SSE tests for progress order, stale results, cancellation, copying, seek, back, autoplay, and original-state preservation. Run the full frontend suite/typecheck/build and commit. Do not create planning or delivery files and do not edit AGENT_LOG.md.
```

- [ ] **Step 2: Resume and review the run**

Run the standard 613 Coding sequence with the Step 1 text.

- [ ] **Step 3: Verify solving UI and playback**

```bash
npm test --workspace apps/web -- --run
npm run typecheck --workspace apps/web
npm run build --workspace apps/web
```

Expected: all frontend tests and build pass.

### Task 8: Ask 613 Coding To Containerize And Verify The Complete Product

**Files:**
- Create through 613 Coding: `tmp/cube/docker/api.Dockerfile`
- Create through 613 Coding: `tmp/cube/docker/web.Dockerfile`
- Create through 613 Coding: `tmp/cube/docker/nginx.conf`
- Create through 613 Coding: `tmp/cube/compose.yaml`
- Create through 613 Coding: `tmp/cube/playwright.config.ts`
- Create through 613 Coding: `tmp/cube/tests/e2e/`
- Create through 613 Coding: `tmp/cube/tests/fixtures/legal_states.json`
- Create through 613 Coding: `tmp/cube/apps/api/tests/integration/`
- Create through 613 Coding: `tmp/cube/README.md`
- Create through 613 Coding: `tmp/cube/THIRD_PARTY_NOTICES.md`

**Interfaces:**
- Produces: same-origin non-root Docker stack, persistent cache, real solver integration tests for 2 through 7, desktop/mobile Playwright evidence, and product documentation.

- [ ] **Step 1: Start a 613 Coding run with this exact task**

```text
Containerize and verify the complete product using test-first contracts. Build the uv API plus NxNxN solver commit c776db79314db3d98cc3dd99685ca85766656937 and Kociemba commit 64fd123bd9cc21d058b37a66473a2fe1807b6dad; compile native helpers, run non-root, retain license/source notices, mount solver-data at /data/solver, use SOLVER_TIMEOUT_SECONDS=1800, and keep API unexposed. Build Vite and serve via unprivileged Nginx with /api proxy. Publish only 127.0.0.1:6131:8080. Add health checks. Add deterministic legal scrambles and invalid fixtures for each order 2-7; real slow tests must solve, replay, reject invalid states, and demonstrate second-run cache reuse. Add Playwright desktop 1280x800 and mobile 390x844 tests for nonblank canvas pixels, full framing, accurate paint, drag without paint, diagnostics, orientation, copy, playback, speed, cancellation, drawer layout, and screenshot inspection; mock network only through Playwright routes, never a production test endpoint. Write README for startup, editing, orientation, notation, first-use tables, cache removal, timeout, troubleshooting, and tests. Add MIT and GPL-2.0 notices. Run focused contracts and commit. Do not create planning or delivery files and do not edit AGENT_LOG.md.
```

- [ ] **Step 2: Resume and review the run**

Run the standard 613 Coding sequence with the Step 1 text. This batch may require multiple resumes within its 30-call and two-hour configured budget; do not create a new unrelated task until its terminal state and diff are reviewed.

- [ ] **Step 3: Run container and fast browser verification**

```bash
cd tmp/cube
docker compose build
docker compose up -d
curl --fail http://127.0.0.1:6131/api/health
docker compose exec -T api id -u
docker compose exec -T web id -u
npm run test:e2e
```

Expected: health returns `{"status":"ok"}`, both container UIDs are nonzero, and desktop/mobile browser tests pass.

- [ ] **Step 4: Run real solver verification twice**

```bash
uv run --project apps/api pytest -m solver_slow apps/api/tests/integration -q
uv run --project apps/api pytest -m solver_slow apps/api/tests/integration -q
```

Expected: every order 2 through 7 solves and replay-verifies; every invalid fixture is rejected; the second run reuses the lookup cache.

### Task 9: Final Review, Repair Runs, And Local Handoff

**Files:**
- Modify through targeted 613 Coding repair runs: only files implicated by observed failures or review findings.

**Interfaces:**
- Consumes: complete Task 8 worktree and fresh command evidence.
- Produces: passing full verification and a running local service at `http://127.0.0.1:6131`.

- [ ] **Step 1: Run the complete verification script**

```bash
cd /home/int21/Workspace/ai4se_project/tmp/cube
bash scripts/verify.sh
git diff --check
git status --short
```

Expected: verification and diff checks pass; only intentional generated artifacts are ignored.

- [ ] **Step 2: Use targeted 613 Coding repair runs for any proven finding**

Use this prompt shape with the exact observed command and error pasted into the task; never ask for broad refactoring:

```text
Diagnose and fix the verified Cube Solver failure using TDD. The failing command and complete error are included below. Reproduce the failure, identify the root cause, add the narrowest regression test, implement the fix, rerun the focused and full relevant checks, and commit. Preserve the approved architecture. Do not create planning or delivery files and do not edit AGENT_LOG.md.
```

- [ ] **Step 3: Start the final local stack and keep it running**

```bash
docker compose up -d --build
curl --fail http://127.0.0.1:6131/api/health
```

Expected: the service remains available at `http://127.0.0.1:6131` for user testing.

## Standard 613 Coding Invocation

Every implementation batch after Task 1 uses the batch's exact prompt:

```bash
cd /home/int21/Workspace/ai4se_project
RUN_ID="$(uv run 613-coding run task "$TASK_PROMPT" --repo tmp/cube --json | jq -r '.id')"
uv run 613-coding runs resume "$RUN_ID" --repo tmp/cube --json
uv run 613-coding runs status "$RUN_ID" --repo tmp/cube --json
uv run 613-coding runs events "$RUN_ID" --repo tmp/cube --json
```

`TASK_PROMPT` is a shell variable containing the exact text from the selected task's Step 1. Review the diff and independent verification before starting the next batch.

After every `runs events` call and independent verification, append one real entry to `tmp/cube/AGENT_LOG.md` using `apply_patch` with:

```text
timestamp in Asia/Shanghai
batch name and exact prompt summary
run ID
commands actually executed
terminal status and stop reason
event summary
independent verification commands and observed results
controller review decision
```

Do not pre-create future entries and do not rewrite failed entries after a recovery run.
