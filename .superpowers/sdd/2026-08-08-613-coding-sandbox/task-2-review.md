# SANDBOX-02 Independent Review

Base: `5302fed3231d12784d0def4b35b233679f25e882`
Head: `1afe5697ce481581cc71030920661a09fbf42673`

## Spec Compliance

**Verdict: Needs fixes**

The copy, snapshot, allowlist, patch, binary-summary, redaction, and normal cleanup paths are covered by focused tests (`12 passed`). The implementation does not yet establish a trustworthy workspace capability boundary.

### Critical

- **C1: Artifact collection accepts fabricated workspaces and can export arbitrary host files.** `ArtifactExporter.collect` trusts `workspace.path` and snapshots it directly (`src/coding_harness/adapters/sandbox/artifacts.py:105-111`), while `Workspace` is a public, constructible dataclass with no manager-issued ownership token (`src/coding_harness/adapters/sandbox/workspace.py:37-44`). A focused probe constructed a `Workspace` for an unrelated directory and exported its file contents. This defeats workspace isolation and can disclose host/repository data. Bind workspaces to an opaque manager capability and have collection validate ownership before reading.

### Important

- **I1: Cleanup ownership is path-only and remains forgeable.** The manager records `_owned` by canonical workspace path (`src/coding_harness/adapters/sandbox/workspace.py:123-124`), then accepts any object whose `path` matches that entry (`src/coding_harness/adapters/sandbox/workspace.py:150-166`). A fabricated `Workspace` with a known managed path successfully deleted the managed temporary root in a focused probe. Require an unforgeable manager-issued token/object identity in addition to the path.

- **I2: Mutable workspace/baseline state can bypass write-set and change detection.** `WorkspaceBaseline` is frozen only shallowly around a mutable `dict`, and `Workspace` itself is mutable (`src/coding_harness/adapters/sandbox/workspace.py:32-44`). `collect` reads both `workspace.baseline` and `workspace.declared_write_set` at export time (`src/coding_harness/adapters/sandbox/artifacts.py:110-117`). A caller can replace a baseline snapshot with the post-change bytes to hide a modification, or assign a broad write set before export. Use immutable/copy-on-ingress manifests and manager-owned immutable workspace metadata.

### Minor

- **M1: Redaction does not cover every artifact field/value shape.** Patch, summary, assumptions, and follow-ups are redacted, but `changed_files` is passed through unchanged (`src/coding_harness/adapters/sandbox/artifacts.py:125-131`), and `_redact` leaves mapping keys and byte values untouched (`src/coding_harness/adapters/sandbox/artifacts.py:24-31`). Secret-bearing filenames or non-string verification payloads can therefore bypass the intended redaction boundary.

## Code Quality

**Verdict: Needs fixes**

### Critical

- C1 is a security-critical trust-boundary failure: the exporter has no way to distinguish a manager-created workspace from an arbitrary path-bearing dataclass.

### Important

- I1 and I2 are lifecycle and integrity failures, respectively. The existing tests cover foreign paths but not forged objects with an owned path, nor mutation of the frozen baseline's underlying mapping or workspace metadata.

### Minor

- M1 leaves the redaction helper dependent on the caller supplying only string-valued metadata; the `WorkArtifact` model permits arbitrary evidence values.

## Verification

- Focused tests: `UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest tests/sandbox/test_workspace.py tests/sandbox/test_artifacts.py -q` -> `12 passed`.
- Focused probes reproduced C1, I1, and I2 without modifying repository files.
- No implementation, test, index, or branch files were changed by this review.

## Assessment

**Task quality: Needs fixes.** C1 must be addressed before SANDBOX-03; I1 and I2 must be fixed in the same task because they undermine cleanup and artifact integrity.

---

## Scoped Re-Review: `698863c..840cc21`

The review also includes the pre-existing evidence commit `1afe569`. Scope was limited to the remediation for C1, I1, I2, and M1.

### Spec Compliance

**Verdict: Needs fixes**

### Critical

- **C1: ADDRESSED.** `ArtifactExporter` now requires a `WorkspaceManager` and calls `validate` before reading (`src/coding_harness/adapters/sandbox/artifacts.py:95-119`). A focused probe with a fabricated `Workspace` for a foreign directory now raises `WorkspaceIntegrityError` before any files are exported.

- **C2: OPEN (new). A managed workspace can be replaced with an external symlink after creation, then exported.** `WorkspaceManager.validate` verifies only Python object identity (`src/coding_harness/adapters/sandbox/workspace.py:178-183`). `snapshot_tree` canonicalizes the supplied root before symlink validation (`src/coding_harness/adapters/sandbox/workspace.py:89-93`), so if an attacker removes the manager-created `repo` directory and substitutes a symlink to an external directory, the symlink is resolved first and no longer appears in the tree scan. A focused probe exported an external `host-secret` file through the genuine manager-issued workspace. Bind validation to the recorded canonical destination (and reject a changed/replaced root) before snapshotting.

### Important

- **I1: ADDRESSED.** Ownership is now bound to the exact manager-issued object (`src/coding_harness/adapters/sandbox/workspace.py:131-176`). A fabricated `Workspace` carrying a real managed path is rejected by `cleanup`, while the original remains removable.

- **I2: ADDRESSED.** `Workspace` is frozen, and `WorkspaceBaseline` copies its manifest into a `MappingProxyType` (`src/coding_harness/adapters/sandbox/workspace.py:37-52`). Export accepts only the workspace's own baseline object (`src/coding_harness/adapters/sandbox/artifacts.py:115-119`). Focused mutations of the baseline mapping and declared write set now raise `TypeError` and `FrozenInstanceError`.

### Minor

- **M1: ADDRESSED.** Changed paths are redacted, and metadata redaction now covers mapping keys and byte values (`src/coding_harness/adapters/sandbox/artifacts.py:25-34`, `src/coding_harness/adapters/sandbox/artifacts.py:133-139`). The new regression test confirms those values do not reach the serialized artifact.

### Code Quality

**Verdict: Needs fixes**

### Critical

- C2 is a new security-critical TOCTOU/path-integrity failure. The manager capability protects a fabricated Python object but not the filesystem object it authorizes, so the artifact trust boundary remains bypassable.

### Important

- No new Important issue found in the remediation scope.

### Minor

- No new Minor issue found in the remediation scope.

### Verification

- `UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest tests/sandbox/test_workspace.py tests/sandbox/test_artifacts.py -q` -> `16 passed`.
- Focused probes confirmed C1, I1, I2, and M1 are addressed.
- A focused directory-replacement probe reproduced C2: after replacing the genuine workspace root with an external symlink, `ArtifactExporter(manager).collect(workspace, workspace.baseline)` exported `host-secret`.

### Re-Review Assessment

**Task quality: Needs fixes.** The requested C1/I1/I2/M1 repairs are effective, but C2 is Critical and must be fixed and regression-tested before SANDBOX-02 can pass its task gate.
