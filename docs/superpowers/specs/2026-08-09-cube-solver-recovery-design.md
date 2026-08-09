# Cube Solver Recovery And Delivery Design

**Status:** Approved during brainstorming on 2026-08-09.

## Relationship To The Existing Design

This document supplements, and only where stated supersedes,
`2026-08-09-cube-solver-design.md`. The Cube product remains a local React, Three.js, and FastAPI
application for editing, validating, solving, and replaying cubes from order 2 through 7. The
removal of the 613 Coding WebUI does not remove Cube's own browser interface.

## Current State

Cube Task 2 is committed at `8c052ee22165b4def9ceffec229a749eea6a6802` and independently
verified. Task 3 has controller-owned log changes plus worker-authored RED tests and inconsistent
partial TypeScript implementations. The focused state/move suite currently has 42 failures. These
files are evidence and input to recovery; they are not silently discarded or manually replaced.

The repeated blocker was whole-file `edit_file`: narrow model repairs overwrote previously richer
implementations. Cube authoring resumes only after the safe patch tool and TUI design are
implemented and verified.

## Authoring Workflow

All Cube product source, tests, product documentation, locks, and container files continue to be
authored through 613 Coding. The controller may append only actual prompts, commands, session and
Run identifiers, terminal states, event summaries, interventions, and independent verification
results to `tmp/cube/AGENT_LOG.md`. Cube does not gain PLAN, SPEC, DELIVERY_STATUS,
SPEC_PROCESS, or an automatic delivery script.

The normal interactive command becomes:

```bash
uv run 613-coding --repo tmp/cube --resume latest
```

`tmp/cube/harness.toml` already contains the non-secret provider metadata for credential `ai2`,
base URL `https://ai2.1343263.xyz/v1`, and model `gpt-5.6-sol`. The API key remains only in the
host keyring and must never be printed, logged, prompted into a worker, or copied into a container.

## Recovery Sequence

The first resumed batch treats the existing 42 focused failures as its RED evidence. It compares
the tests, coordinate model, state API, and move API, then uses small `apply_patch` changes to
establish one coherent contract. It runs the focused state/move suite and TypeScript checks before
committing Task 3. It must not rewrite unrelated foundation files or edit the operation log.

After Task 3 is green, the approved Cube plan continues in bounded batches: shared orientation and
notation, authoritative validation, pinned solver/cache/process boundaries, jobs and streaming
API, Three.js editor, solving and playback, local Compose packaging, and final verification.
Failed or cancelled Runs remain visible; a new batch begins only after independent evidence shows
the previous batch's exact result.

## Product Scope And Acceptance

The final product preserves all existing requirements:

- complete editing and structural validation for orders 2 through 7;
- exactly 24 legal front/top output orientations;
- WCA notation, including wide and multi-layer turns, with Chinese explanations;
- pinned NxNxN and Kociemba solver revisions and validated lazy lookup-table caching;
- cancellation, bounded subprocesses, one default concurrent job, and a 30-minute default timeout;
- solution success only after replay reaches six uniform faces;
- a full-bleed, editable Three.js cube with separate painted and playback states;
- a same-origin local Compose application bound only to `127.0.0.1:6131`.

Verification includes focused and full offline suites, representative real solver runs for every
order 2 through 7, invalid-state fixtures, all 24 orientations, replay checks, desktop and mobile
Playwright workflows, screenshots, and nonblank canvas-pixel assertions. Real solver evidence is
separate from fake-based unit coverage and cannot be replaced by a mocked success.

## Delivery Boundary

Cube is a local tool, not a remote deployment target. Its Compose setup may run local web and API
containers because that is part of Cube's product architecture. No remote host, reverse proxy,
domain, public URL, or server deployment is required for either Cube or 613 Coding.
