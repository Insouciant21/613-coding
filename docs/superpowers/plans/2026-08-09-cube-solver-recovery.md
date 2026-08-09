# Cube Solver Task 3 Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Use the redesigned 613 Coding TUI and safe patch tool to recover the worker-authored Cube domain, complete the original Task 3 contract, and unlock the remaining Cube plan.

**Architecture:** The controller does not hand-edit Cube product code. It preserves the committed foundation and dirty RED artifacts, launches 613 Coding against tmp/cube, supplies narrowly bounded tasks, and independently verifies each Run. TypeScript owns immutable editing and coordinate-based NxN moves; shared JSON vectors keep TypeScript/Python orientation and replay behavior identical.

**Tech Stack:** 613 Coding TUI, apply_patch, React/TypeScript, Vitest, Python 3.12 managed by uv, Pydantic, pytest, Ruff, mypy.

## Global Constraints

- Begin only after both 2026-08-09-safe-repository-mutations.md and 2026-08-09-613-coding-tui-distribution.md are complete, reviewed, integrated, and freshly verified.
- Cube Task 2 remains committed at 8c052ee22165b4def9ceffec229a749eea6a6802.
- Preserve tmp/cube/AGENT_LOG.md and every worker-authored uncommitted Task 3 file as evidence and recovery input.
- The controller may edit only tmp/cube/AGENT_LOG.md; all Cube source, tests, configuration, dependencies, locks, and commits are authored through 613 Coding.
- Do not create PLAN.md, SPEC.md, DELIVERY_STATUS.md, SPEC_PROCESS.md, or an automatic delivery script inside tmp/cube.
- Use the existing ai2 provider metadata. Never display, log, prompt, persist, or pass the API key to a worker or subprocess.
- Use apply_patch for existing Cube files. Do not use whole-file edit_file to repair state.ts, moves.ts, types.ts, or coordinates.ts.
- Treat the existing focused failures as valid RED evidence; do not rewrite tests merely to match an incomplete implementation.
- Support orders 2 through 7, face order U,L,F,R,B,D, and colors white, orange, green, red, blue, yellow.
- Append every actual TUI command, session/Run ID, prompt, terminal state, event summary, intervention, test result, and commit to tmp/cube/AGENT_LOG.md.

---

## File Map

- Recovery inputs: apps/web/src/cube/types.ts, palette.ts, coordinates.ts, state.ts, moves.ts, state.test.ts, and moves.test.ts.
- Create through 613 Coding: apps/web/src/cube/orientation.ts, orientation.test.ts, notation.ts, and notation.test.ts.
- Create through 613 Coding: apps/api/src/cube_api/cube/__init__.py, orientation.py, and replay.py.
- Create through 613 Coding: apps/api/tests/test_orientation_replay.py and tests/fixtures/orientation_vectors.json.
- Controller modifies: AGENT_LOG.md only.

### Task 1: Capture The Recovery Baseline

**Files:**
- Modify manually: tmp/cube/AGENT_LOG.md
- Read only: current tmp/cube/apps/web/src/cube/ files and Git state.

**Interfaces:**
- Consumes: current dirty worker-authored Task 3 state.
- Produces: an exact baseline record without changing Cube product files.

- [ ] **Step 1: Verify credential/config metadata without reading the key**

Run from the main repository:

~~~bash
uv run 613-coding credentials status ai2
uv run 613-coding config check --repo tmp/cube
~~~

Expected: ai2 is configured from keyring and the Cube config is valid with autonomous mode and its finite unattended budget.

- [ ] **Step 2: Capture current Git and focused RED evidence**

~~~bash
git -C tmp/cube status --short --branch
git -C tmp/cube diff --check
npm test --prefix tmp/cube --workspace apps/web -- --run src/cube/state.test.ts src/cube/moves.test.ts
~~~

Expected before recovery: Task 2 at 8c052ee; AGENT_LOG.md modified; apps/web/src/cube untracked; focused failures caused by incompatible state, move, type, and coordinate contracts. Record the fresh count rather than assuming it remains 42.

- [ ] **Step 3: Append baseline evidence to the controller log**

Append timestamp, credential/config status without secret data, HEAD, dirty paths, focused command, exit code/failure count, and the fact that no product file was manually edited. Do not stage or commit the baseline log separately from the eventual Task 3 result.

### Task 2: Reconcile State, Coordinates, And Move Permutations

**Files:**
- Modify through 613 Coding: apps/web/src/cube/types.ts
- Modify through 613 Coding: apps/web/src/cube/palette.ts
- Modify through 613 Coding: apps/web/src/cube/coordinates.ts
- Modify through 613 Coding: apps/web/src/cube/state.ts
- Modify through 613 Coding: apps/web/src/cube/moves.ts
- Modify through 613 Coding only to strengthen the approved contract: state.test.ts and moves.test.ts

**Interfaces:**
- Produces: CubeOrder = 2 | 3 | 4 | 5 | 6 | 7.
- Produces: CubeState with order, flat face arrays in stickers, revision, history capped at 200, and future.
- Produces: createCubeState, paintSticker, undo, redo, resetCube, and validateStoredCubeState.
- Produces: stickerToCoordinate(order, face, index), coordinateToSticker(order, coordinate), and rotateCoordinate(order, coordinate, axis, quarterTurns).
- Produces: parseMove(token, order) -> Move and applyMove(state, token) -> CubeState.

- [ ] **Step 1: Launch the TUI in the Cube repository**

Run in a PTY:

~~~bash
uv run 613-coding --repo tmp/cube --resume latest
~~~

If no resumable session exists, start one and record its session ID. Confirm the status footer shows gpt-5.6-sol, autonomous mode, and the Cube repository path without showing a credential.

- [ ] **Step 2: Submit this exact recovery task**

~~~text
Recover only the existing TypeScript cube state, coordinate, and move domain. Inspection and RED evidence already exist: keep the approved tests and use apply_patch, never whole-file edit_file, for existing source. Establish one contract: CubeState has order 2..7, flat ULFRBD face arrays, revision, history capped at 200, and future; createCubeState, paintSticker, undo, redo, resetCube, and validateStoredCubeState are immutable. Keep coordinate signatures order-first. parseMove validates the current order; applyMove accepts a WCA token and performs coordinate-based outer, inverse, half, wide, numeric multi-layer, and x/y/z permutations. Add only missing contract tests, including paint immutability, invalid order/layer tokens, flat sticker counts, four-turn identity, move-plus-inverse identity, and no mutation of prior snapshots. First run the focused tests to preserve RED, then patch the minimum coherent implementation. Run focused Vitest, frontend lint, and typecheck. Do not touch AGENT_LOG.md, planning files, API files, or unrelated foundation files. Commit only when focused tests, lint, and typecheck pass; do not claim full Task 3 complete yet.
~~~

- [ ] **Step 3: Handle only exact approvals**

For every apply_patch approval, inspect the diff and paths. Approve only the scoped cube files/tests. Reject whole-file replacement, dependency installation, outside paths, log edits, or unrelated foundation edits. Pause only after three unchanged objective-feedback turns and record the reason.

- [ ] **Step 4: Independently verify**

~~~bash
npm test --prefix tmp/cube --workspace apps/web -- --run src/cube/state.test.ts src/cube/moves.test.ts
npm run --prefix tmp/cube lint:web
npm run --prefix tmp/cube typecheck:web
git -C tmp/cube diff --check
git -C tmp/cube status --short
~~~

Expected: state/move tests, lint, and typecheck pass; only scoped Task 3 paths plus controller AGENT_LOG.md differ from HEAD.

- [ ] **Step 5: Append Run evidence**

Append prompt, session/Run ID, terminal state, model-call/turn usage, changed files, approval decisions, worker commit if created, independent results, and any discrepancy between worker claims and controller evidence.

### Task 3: Complete Shared Orientation, Notation, And Python Replay

**Files:**
- Create through 613 Coding: apps/web/src/cube/orientation.ts and orientation.test.ts
- Create through 613 Coding: apps/web/src/cube/notation.ts and notation.test.ts
- Create through 613 Coding: apps/api/src/cube_api/cube/__init__.py, orientation.py, and replay.py
- Create through 613 Coding: apps/api/tests/test_orientation_replay.py
- Create through 613 Coding: tests/fixtures/orientation_vectors.json

**Interfaces:**
- Produces: exactly 24 adjacent (front, top) frames and canonical/local move mappings in both languages.
- Produces: TypeScript describeMoveZh(token: string, order: CubeOrder) -> string.
- Produces: Python replay(order: int, facelets: str, moves: Sequence[str], front: Face, top: Face) -> ReplayResult.
- Produces: one JSON fixture consumed by both TypeScript and Python tests.

- [ ] **Step 1: Submit this exact TDD task in the same TUI session**

~~~text
Complete only the remaining Cube Task 3 orientation, notation, and replay contract using TDD. Create one tests/fixtures/orientation_vectors.json consumed by TypeScript and Python. It must enumerate exactly 24 legal adjacent front/top frames, canonical-to-local and local-to-canonical face mappings, and representative outer, inverse, half, wide, numeric multi-layer, and x/y/z moves. Add failing tests first. TypeScript must expose legalFrames, mapMoveToFrame, mapMoveFromFrame, and describeMoveZh; 3Rw' must produce exactly 右侧三层逆时针旋转 90 度. Python must implement the same frame mapping and replay(order, facelets, moves, front, top) returning a typed ReplayResult that reports solved only when all six canonical faces are uniform after applying mapped moves. Reuse the now-green coordinate/move contract; use apply_patch for existing files and create-file operations only for new files. Run focused frontend Vitest plus API pytest, frontend lint/typecheck, API Ruff/mypy, then bash scripts/verify.sh. Do not edit AGENT_LOG.md or create planning/delivery files. Commit the complete Task 3 only after all checks pass.
~~~

- [ ] **Step 2: Inspect approvals and scope**

Approve only the listed Task 3 files and declared validation. Reject package installs, network access, log edits, solver implementation, UI work, or unrelated rewrites. Confirm both languages read the same vector fixture.

- [ ] **Step 3: Independently verify all Task 3 contracts**

~~~bash
npm test --prefix tmp/cube --workspace apps/web -- --run src/cube
uv run --project tmp/cube/apps/api pytest tmp/cube/apps/api/tests/test_orientation_replay.py -q
npm run --prefix tmp/cube lint:web
npm run --prefix tmp/cube typecheck:web
uv run --project tmp/cube/apps/api ruff check tmp/cube/apps/api
uv run --project tmp/cube/apps/api mypy tmp/cube/apps/api/src
bash tmp/cube/scripts/verify.sh
git -C tmp/cube diff --check
~~~

Expected: every command passes; all six orders and 24 frames are covered; the exact 3Rw' Chinese text passes; replay verifies solutions rather than trusting a solver flag.

- [ ] **Step 4: Audit and commit state**

Verify no forbidden process file exists, AGENT_LOG.md was changed only by the controller, and the product commit contains all worker-authored RED artifacts plus the coherent implementation. If the worker did not commit despite green evidence, submit a final TUI instruction to rerun bash scripts/verify.sh and commit exactly Task 3 product paths. The controller does not create the product commit.

- [ ] **Step 5: Append completion evidence**

Append session/Run ID, prompt, terminal state, tool/approval summary, worker commit hash, fresh focused/full verification, and Task 3 acceptance decision to AGENT_LOG.md.

### Task 4: Hand Off To Remaining Cube Tasks 4-9

**Files:**
- Modify manually: tmp/cube/AGENT_LOG.md
- Read: docs/superpowers/plans/2026-08-09-cube-solver.md

**Interfaces:**
- Consumes: green committed Cube Task 3.
- Produces: an explicit boundary for original Cube Tasks 4-9 without changing their requirements.

- [ ] **Step 1: Confirm remaining-task prerequisites**

Read Tasks 4-9 of the original Cube plan. Confirm their input paths and interfaces exist at the Task 3 commit. Record path-only drift in the log; do not weaken validation, solver, 3D, playback, Compose, or final verification.

- [ ] **Step 2: Record the supersession boundary**

Append that original Task 3 is superseded by this recovery plan, while original Tasks 4-9 remain approved and next. Include the Task 3 commit and fresh full verifier result.

- [ ] **Step 3: Continue original Tasks 4-9 through the TUI**

For each original task, submit its exact task text through:

~~~bash
uv run 613-coding --repo tmp/cube --resume latest
~~~

Run the original focused verification after every batch. Preserve the controller-only log rule and require product commits from 613 Coding. Recovery-plan completion does not mark Cube complete. Final completion requires original Tasks 4-9, representative real solver/replay evidence for every order 2 through 7, Playwright desktop/mobile screenshots, and nonblank Three.js canvas-pixel checks.
