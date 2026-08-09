# 613 Cube Solver Design

## Goal

Build a local Rubik's Cube editing and solving application in `tmp/cube` by running the 613 Coding agent harness. The application must render an editable 3D cube from 2x2 through 7x7, diagnose invalid manually entered states, and solve valid states relative to a user-selected front and top face.

The result must show both standard WCA notation and a Chinese explanation for every move. The user can inspect the solution as text or replay it with previous, next, play, pause, and speed controls.

## Scope

The first release supports all of the following for every order from 2 through 7:

- full 3D display and orbit controls;
- direct sticker painting with six standard colors;
- undo, redo, reset, and solved-state restoration;
- structural and reachability validation;
- solving through a proven NxNxN solver;
- solution verification by replay;
- selectable front and adjacent top faces;
- WCA notation, Chinese move explanations, copying, and animated playback;
- responsive desktop and mobile workflows.

The application runs locally with Docker Compose. Cube states remain on the local machine and are never sent to an external solving service.

## Architecture

The repository is a small full-stack application:

```text
tmp/cube/
  apps/web/       React, TypeScript, Vite, and Three.js
  apps/api/       FastAPI application managed with uv
  tests/          Cross-service and solver integration fixtures
  docker/         Pinned solver build and runtime support
  compose.yaml
  harness.toml
  AGENTS.md
```

The browser owns editing state and 3D presentation. The API owns authoritative validation, solver execution, progress reporting, cancellation, and replay verification. The browser may perform fast preliminary checks, but only the API may declare a state valid or return a solution.

The frontend uses `cubing.js` for algorithm parsing and playback semantics, not as the high-order solver. The backend integrates `dwalton76/rubiks-cube-NxNxN-solver` pinned to commit `c776db79314db3d98cc3dd99685ca85766656937`. Its Kociemba dependency is pinned to commit `64fd123bd9cc21d058b37a66473a2fe1807b6dad` and compiled into the solver image. Third-party license notices must include the NxNxN solver's MIT license and Kociemba's GPL-2.0 license.

Docker Compose publishes a single same-origin application endpoint on `127.0.0.1:6131`. The web container proxies `/api` to the API container. Development commands may expose separate Vite and API ports, but production-like local use must not require cross-origin configuration.

## Cube State Model

The canonical state contains:

```text
order: 2..7
stickers: 6 * order * order colors indexed by (face, row, column)
frontFace: one of U, L, F, R, B, D
topFace: a face adjacent to frontFace
revision: monotonically increasing edit revision
```

The standard solved palette is white on U, orange on L, green on F, red on R, blue on B, and yellow on D. White/yellow, green/blue, and red/orange are opposite pairs. A selected front and top define one of the 24 valid cube orientations; the UI disallows non-adjacent pairs.

The state model is the single source of truth. Three.js objects contain stable sticker identifiers but do not own colors independently. Painting a sticker increments the revision, records an undo entry, cancels a running job for an older revision, and invalidates any older diagnosis or solution.

Changing order creates a solved cube of the new order. When the current cube differs from solved state, the UI requires confirmation before replacing it. The browser saves the latest state and orientation for each order in `localStorage`; malformed or version-incompatible saved data is ignored and replaced with solved state.

## 3D Rendering And Editing

The main Three.js scene is full-bleed within the workspace rather than placed in a decorative card. It renders cubies and individually pickable stickers for orders 2 through 7. Stable scene dimensions and camera framing keep every supported cube fully visible on desktop and mobile.

Pointer movement below a small drag threshold counts as a sticker click and applies the active palette color. Movement above that threshold controls orbit rotation and must not paint. Mouse wheel and two-finger gestures zoom within bounded distances. Reset-camera and fit-camera icon controls include tooltips.

Playback rotates the affected outer, inner, or wide layers and then commits the move to a separate playback state. The original painted input remains unchanged. The user may explicitly replace the edit state with the current playback state.

## Validation

Validation is layered so common errors are fast and explainable while solver output remains the final authority.

### Structural Validation

- Exactly six supported colors are present.
- Each color occurs exactly `order * order` times.
- The state length and every sticker coordinate are valid.
- Front and top are adjacent.
- Odd-order fixed centers establish a unique, physically consistent color frame.

### Piece And Orbit Validation

- All eight corner color combinations exist exactly once.
- Corner orientation sum is valid.
- Edge pieces and each high-order wing orbit have the required color combinations and multiplicities.
- Edge orientation and orbit constraints are valid for the selected order.
- Center pieces in each high-order orbit have the required color counts.
- Applicable corner, wing, center, and reduced-cube permutation parity constraints hold.

The backend reuses the pinned solver's order-specific sanity checks and adds application-level diagnostics where the solver only raises a generic reduction error. A definitive solver error caused by an unreachable arrangement is reported as invalid. A timeout or process failure is operational failure, not proof that a state is invalid.

### Replay Verification

Every returned algorithm is parsed and applied to a fresh copy of the submitted state. The API returns success only when all six faces are solved after replay. A malformed algorithm or failed replay is an internal solver error and is never exposed as a successful solution.

Validation errors have stable codes, Chinese descriptions, and optional sticker coordinates. For example, `EDGE_DUPLICATE` can identify the duplicate and missing edge combinations. Global constraints such as an invalid corner twist sum do not falsely blame an arbitrary sticker.

## Orientation And Notation

Before solving, the orientation module maps the selected front and top faces to the solver's canonical U/L/F/R/B/D frame. After solving, it maps moves back into the user's frame. The same mapping drives displayed notation, Chinese descriptions, copying, and 3D playback.

The primary formula follows WCA-style notation:

- outer faces: `U L R B D F`;
- wide turns: `Uw Lw Rw Bw Dw Fw`;
- three or more layers: a numeric prefix such as `3Rw`;
- counter-clockwise turns: a prime suffix such as `R'`;
- half turns: a `2` suffix such as `Uw2`;
- whole-cube rotations when required: `x y z`.

Each token also has a generated Chinese explanation. For example, `3Rw'` is explained as "右侧三层逆时针旋转 90 度". Move normalization is deterministic so formula text and playback cannot diverge.

## Solver Jobs And API

The API exposes:

```text
GET    /api/health
POST   /api/solve
GET    /api/jobs/{job_id}/events
DELETE /api/jobs/{job_id}
```

`POST /api/solve` accepts the canonical order, facelets, front, top, and edit revision. It returns a job identifier after bounded synchronous schema validation. Server-Sent Events report queued, validating, downloading, reducing, solving, verifying, completed, cancelled, and failed states.

The default maximum solver concurrency is one. Additional requests queue in submission order. Each solver runs in its own process group and isolated temporary directory. Cancellation or timeout terminates the whole process group and removes its temporary data. The default solve timeout is 30 minutes and is configurable through `SOLVER_TIMEOUT_SECONDS`.

The API passes validated arguments directly as a subprocess argument list and never interpolates user input into a shell command. Request size and cube order are bounded. Job state is in memory and intentionally disappears on API restart; no business database is required.

Error responses distinguish `INVALID_STATE`, `TABLE_DOWNLOAD_FAILED`, `SOLVER_TIMEOUT`, `SOLVER_UNAVAILABLE`, `CANCELLED`, and `INTERNAL_ERROR`. Retrying an operational failure never mutates the submitted cube.

## Lookup Tables

The high-order solver uses precomputed pruning and phase lookup tables to avoid exhaustive searches. These are solver data, not AI models, vector data, or user data.

Tables are downloaded on first use for the requested order over HTTPS and stored in the `solver-data` Docker volume. The API streams download and initialization progress to the browser. The pinned upstream does not publish a complete cryptographic checksum manifest, so the wrapper validates successful decompression plus the expected record count and record width declared by the pinned solver. Partial downloads use temporary names and are not treated as cache hits. Final solution replay prevents corrupt table data from producing an accepted result. Later runs reuse the persistent cache.

Deleting `solver-data` is safe but forces the next relevant solve to download tables again. README documentation must state this behavior, expected first-run delay, cache inspection and removal commands, and any upstream table-size information verified during implementation.

## User Interface

The approved desktop layout is a workbench:

- a compact top bar with product name, order menu, undo, redo, and solved-state restoration;
- a large central 3D workspace;
- a fixed right tool panel with labeled color swatches, front/top selectors, reset, diagnostics, and the solve command;
- a bottom result strip with status, formula, copy, previous, next, play/pause, and speed controls.

The six swatches use color plus a letter or name so color is not the only identifier. Invalid-state diagnostics and identifiable stickers highlight each other. Formula tokens are individually selectable, and the active playback token remains visible. Editing after a solution clears that result immediately.

On narrow screens, the right tool panel becomes a bottom drawer while compact playback controls remain reachable above it. The 3D scene retains most of the viewport. Controls have stable dimensions, text cannot overlap adjacent content, and the mobile drawer must not cover the active formula line incoherently.

Solver and table progress appears in the result area with a cancel command. Infrastructure errors offer retry while preserving the current input. The interface contains no marketing landing page or instructional feature prose; labels, status, tooltips, and diagnostics provide the necessary operational context.

## Testing

### Unit And Property Tests

- Sticker indexing, painting, undo, redo, reset, persistence, and revision invalidation for orders 2 through 7.
- All 24 valid front/top orientations and rejection of invalid pairs.
- Move mapping round trips for outer, wide, inner-layer, inverse, half-turn, and cube-rotation notation.
- Known legal states and crafted invalid states for color counts, duplicate pieces, orientation sums, orbit counts, and parity.
- Formula parsing, Chinese explanations, and replay-to-solved verification.

### API And Solver Integration Tests

- Schema rejection, job lifecycle, SSE progress, cancellation, timeout, and process cleanup.
- Fixed legal fixtures for every order from 2 through 7 solved by the real pinned backend and replayed to solved state.
- Fixed invalid fixtures for every order rejected with stable diagnostic categories.
- Interrupted lookup-table downloads never become valid cache entries.
- Slow high-order integration tests are marked separately so ordinary frontend tests do not repeatedly fetch solver data.

### Browser Tests

Playwright covers desktop and mobile viewports. It verifies nonblank canvas pixels, complete camera framing, sticker picking, drag-versus-click behavior, diagnostics, order switching, responsive drawers, formula copying, step navigation, autoplay, speed control, and cancellation. Key desktop and mobile screenshots are inspected for overlap, clipping, blank canvases, and unintended layout movement.

## 613 Coding Delivery Workflow

Implementation is performed through the local 613 Coding CLI against `tmp/cube`. The target repository contains a `harness.toml` defining its LLM provider, write policy, command policy, budgets, and test commands, plus an `AGENTS.md` that records the approved design, delivery requirements, and automatic delivery-evidence log behavior.

Provider credentials are stored through the 613 Coding credential command and system Keyring, never in `harness.toml`. The workflow is:

```bash
uv run 613-coding config check --repo tmp/cube
RUN_ID="$(uv run 613-coding run task \
  "Implement the approved 613 Cube Solver plan and record verification evidence" \
  --repo tmp/cube --json | jq -r '.id')"
uv run 613-coding runs resume "$RUN_ID" --repo tmp/cube --json
```

The implementation plan may split work into multiple bounded 613 Coding runs, but each run is reviewed and verified before the next one starts. Manual commands or configuration changes are documented only when local credential or provider state prevents autonomous execution.

## Acceptance Criteria

1. `docker compose up --build` starts the application and `http://127.0.0.1:6131` becomes healthy.
2. Orders 2 through 7 render fully and permit accurate individual sticker painting.
3. Valid fixed fixtures for every supported order produce a replay-verified solution.
4. Invalid fixed fixtures for every supported order produce useful Chinese diagnostics rather than a formula.
5. Formulas use the selected front/top frame and show both WCA notation and per-move Chinese explanations.
6. Previous, next, autoplay, pause, speed, copy, cancel, undo, redo, reset, and solved-state restoration work as designed.
7. First-use table acquisition reports progress and later runs reuse the Docker volume.
8. Solver timeout, download failure, cancellation, and unavailable backend are not mislabeled as invalid cube states.
9. Unit, API, solver integration, and Playwright suites pass, including desktop/mobile canvas and layout checks.
10. README and AGENTS.md contain complete local operation, configuration, cache, test, and delivery-evidence instructions.

## Non-Goals

- Solving orders below 2 or above 7.
- Calling a hosted third-party solving API.
- Accounts, cloud synchronization, or server-side cube history.
- Optimal or competition-minimal solutions; the requirement is a correct replay-verified solution.
- Physical camera scanning, image recognition, or smart-cube Bluetooth input.
- Editing or generating arbitrary color palettes beyond the standard six-color scheme.
