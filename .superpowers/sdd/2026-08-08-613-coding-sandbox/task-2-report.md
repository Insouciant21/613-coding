# SANDBOX-02 Implementation Report

Status: DONE

## Scope

- Added `WorkspaceManager` and repository-shaped temporary `Workspace` values.
- Added deterministic `ArtifactExporter` output as the existing version-1 `WorkArtifact` contract.
- Added focused workspace and artifact tests for copy semantics, path safety, write-set enforcement, diffs, binary summaries, redaction, and cleanup.

## TDD Evidence

RED was observed before either production module existed:

```text
UV_CACHE_DIR=/tmp/613-sandbox-02-uv-cache uv run pytest tests/sandbox/test_workspace.py tests/sandbox/test_artifacts.py -q
2 collection errors: ModuleNotFoundError for coding_harness.adapters.sandbox.workspace and
coding_harness.adapters.sandbox.artifacts
```

The first implementation run reached 6 passed and 1 failed because the symlink path error was not yet a `ValueError` subtype. The focused test and traceback identified that boundary mismatch; `WorkspacePathError` was changed to inherit `ValueError`, then the focused suite passed.

A later ownership regression RED reproduced unsafe foreign-workspace cleanup: the new test failed because no exception was raised. `WorkspaceManager` now tracks owned and cleaned paths; the regression passed after that minimal change.

Controller hardening added five more RED/GREEN boundaries: cleanup initially left the `613-sandbox-*` parent behind, dotfile allowlist entries lost their leading dot, an empty allowlist permitted every change, an explicit empty baseline was ignored, and mode-only changes were absent from artifacts. The final implementation removes the owned temporary root, preserves canonical dotfile names, treats an empty allowlist as deny-all, honors explicit baselines, and records Git file modes.

Final controller verification, run 2026-08-09 04:10 Asia/Shanghai:

```text
UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest tests/sandbox -q
21 passed in 0.21s

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest -q
147 passed in 1.84s

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run ruff check .
All checks passed!

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run mypy src
Success: no issues found in 50 source files

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv lock --check
Resolved 61 packages

git diff --check
passed
```

## Design Decisions

- `WorkspaceManager.create` canonicalizes the source, requires a Git working tree, validates every source symlink, and copies the complete tree with `shutil.copytree(..., symlinks=True)`. This intentionally retains `.git`, ignored files, and untracked files instead of using a Git archive or clone that would omit working-tree data.
- A workspace captures a `WorkspaceBaseline` manifest of non-`.git` files, including file bytes, Git modes, and symlink targets. `capture_baseline` is also exposed for callers that need a fresh explicit baseline.
- Every later snapshot canonicalizes paths and rejects symlinks resolving outside the workspace. Cleanup deletes the complete manager-owned temporary root, refuses foreign/root deletion, tolerates repeated cleanup, and removes partially created directories on copy/snapshot failure.
- Declared write sets are normalized to repository-relative POSIX paths and enforced against the complete changed-file set, including ignored/untracked additions and deletions. Exact paths, directory prefixes, and glob patterns are supported.
- Export uses sorted manifest paths and Python unified diffs, so identical workspace state produces identical patches. Mode-only changes produce Git-compatible mode metadata. Binary or symlink changes emit only a deterministic `Binary files ... differ` marker and a metadata summary; binary bytes are never placed in the artifact patch.
- Patch text, verification evidence, assumptions, and follow-up requests are redacted through the existing deterministic redactor before entering `WorkArtifact`.

## Changed Files

- `src/coding_harness/adapters/sandbox/workspace.py`
- `src/coding_harness/adapters/sandbox/artifacts.py`
- `tests/sandbox/test_workspace.py`
- `tests/sandbox/test_artifacts.py`

## Self-Review

- Checked ignored and untracked files survive copy.
- Checked canonical workspace paths and source/new symlink escape rejection.
- Checked cleanup after successful collection, failed collection, failed source preparation, and repeated cleanup.
- Checked declared write-set rejection before artifact construction, including deny-all empty sets and dotfile paths.
- Checked deterministic repeated collection, explicit empty baselines, text additions/edits, mode-only changes, binary summaries, and redaction of patch and metadata.
- Checked full pytest, Ruff, mypy, lock, and whitespace gates.

## Concerns

- None before independent task review. The implementation intentionally uses a manifest rather than only Git's tracked diff so ignored and untracked task outputs remain exportable.
