# Safe Repository Mutations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strict schema-validated unified-diff `apply_patch` tool and make `delete_file` resistant to parent-directory symlink races.

**Architecture:** `FilesystemTools` owns descriptor-relative repository mutation. A focused patch module parses and preflights unified diffs into immutable change plans; the repository tool adapter exposes those plans through the existing schema, policy, event, and `changed_files` boundaries. Semantic errors finish before mutation, while commit-stage failures report the exact files already changed.

**Tech Stack:** Python 3.12, `uv`, Pydantic, JSON Schema Draft 2020-12, `unidiff`, POSIX `dir_fd` APIs, pytest, Ruff, mypy.

## Global Constraints

- Work in the existing `fix/provider-context-history` worktree created for the harness repairs.
- Preserve commits `80f6c85` through `1c7956c`; do not squash or discard their provider, context, listing, redaction, or Cube evidence changes.
- Use TDD for every behavior: observe the focused RED before implementation, then run focused and complete gates.
- Never resolve a mutation target by checking a pathname and later mutating that pathname.
- Reject absolute paths, `..`, NUL, parent symlinks, `.git`, and `.613-coding`.
- `delete_file` may remove a final symlink but must never follow it.
- `apply_patch` version 1 supports UTF-8 regular-file add, update, and delete only.
- No binary patches, renames, copies, mode changes, directory deletion, shell command, or `shell=True`.
- Keep Python dependencies managed only by `uv` and update `uv.lock` in the task that adds `unidiff`.
- Update `AGENT_LOG.md`, `PLAN.md`, and `DELIVERY_STATUS.md` with actual RED/GREEN/review evidence.

---

## File Map

- `src/coding613/adapters/tools/filesystem.py`: root descriptor ownership, no-follow parent traversal, atomic descriptor-relative writes, and deletion.
- `src/coding613/adapters/tools/patch.py`: strict unified-diff parsing, path normalization, hunk preflight, immutable patch plans, and stable patch errors.
- `src/coding613/adapters/tools/repository.py`: versioned tool schema, executor, structured result, and global changed-file accumulation.
- `tests/adapters/tools/test_filesystem.py`: descriptor traversal, symlink, race, atomic-write, and delete regressions.
- `tests/adapters/tools/test_patch.py`: parser, preflight, supported operations, conflicts, limits, and partial-I/O reporting.
- `tests/application/test_composition.py`: real registry-to-filesystem patch workflow.
- `tests/application/test_policy.py`: strict/balanced/autonomous policy and hard-denial behavior.
- `pyproject.toml`, `uv.lock`: locked `unidiff` dependency.
- `PLAN.md`, `AGENT_LOG.md`, `DELIVERY_STATUS.md`: traceable task evidence.

### Task 1: Descriptor-Relative Delete

**Files:**
- Modify: `src/coding613/adapters/tools/filesystem.py`
- Modify: `tests/adapters/tools/test_filesystem.py`

**Interfaces:**
- Consumes: `FilesystemTools(root: str | Path, max_file_bytes: int = 1_000_000)`.
- Produces: `FilesystemTools.delete_file(path: str | Path) -> None` anchored to held directory descriptors.
- Produces: private `_parent_descriptor(path: Path, *, create: bool = False) -> tuple[int, str]`; the caller owns and closes the returned descriptor.

- [ ] **Step 1: Add the deterministic parent-swap RED test**

Add a test that captures the real `os.unlink`, replaces `repo/safe` with a symlink to an outside directory immediately before the adapter's unlink call, and then delegates to the real function with its received `dir_fd`:

```python
def test_delete_file_is_anchored_when_parent_path_is_swapped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    safe = tmp_path / "safe"
    safe.mkdir()
    (safe / "victim.txt").write_text("inside\n", encoding="utf-8")
    outside = tmp_path.parent / f"outside-{tmp_path.name}"
    outside.mkdir()
    outside_victim = outside / "victim.txt"
    outside_victim.write_text("outside\n", encoding="utf-8")
    parked = tmp_path / "parked"
    real_unlink = os.unlink
    raced = False

    def swap_then_unlink(path: str, *, dir_fd: int | None = None) -> None:
        nonlocal raced
        if not raced:
            raced = True
            safe.rename(parked)
            os.symlink(outside, safe)
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", swap_then_unlink)
    FilesystemTools(tmp_path).delete_file("safe/victim.txt")

    assert not (parked / "victim.txt").exists()
    assert outside_victim.read_text(encoding="utf-8") == "outside\n"
```

- [ ] **Step 2: Run the race test and capture RED**

Run:

```bash
uv run pytest tests/adapters/tools/test_filesystem.py::test_delete_file_is_anchored_when_parent_path_is_swapped -q
```

Expected: FAIL because the current implementation calls `Path.unlink()` without a held `dir_fd`, so the monkeypatched `os.unlink` contract or safety assertion exposes pathname-based deletion.

- [ ] **Step 3: Replace parent pathname traversal with held descriptors**

Implement a small context-managed descriptor traversal using these flags where available:

```python
directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
root_fd = os.open(self.root, directory_flags)
next_fd = os.open(component, directory_flags, dir_fd=current_fd)
metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
os.unlink(name, dir_fd=parent_fd)
```

Validate path components before opening. Close every superseded descriptor and the final
descriptor in `finally`. Use `stat.S_ISDIR(metadata.st_mode)` to reject real directories while
allowing a final symlink.

- [ ] **Step 4: Run delete and filesystem tests**

Run:

```bash
uv run pytest tests/adapters/tools/test_filesystem.py -q
```

Expected: all filesystem tests PASS, including inside/outside final symlink deletion and parent
symlink rejection.

- [ ] **Step 5: Run static checks and commit**

Run:

```bash
uv run ruff check src/coding613/adapters/tools/filesystem.py tests/adapters/tools/test_filesystem.py
uv run mypy src/coding613/adapters/tools/filesystem.py
git diff --check
git add src/coding613/adapters/tools/filesystem.py tests/adapters/tools/test_filesystem.py
git commit -m "fix: anchor repository deletion to directory descriptors"
```

### Task 2: Strict Unified-Diff Parser And Preflight

**Files:**
- Create: `src/coding613/adapters/tools/patch.py`
- Create: `tests/adapters/tools/test_patch.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: `reader(path: str) -> str` for existing UTF-8 repository files.
- Produces: `PatchOperation(StrEnum)` with `ADD`, `UPDATE`, and `DELETE`.
- Produces: `PreparedChange(path: str, operation: PatchOperation, before: str | None, after: str | None)`.
- Produces: `PreparedPatch(changes: tuple[PreparedChange, ...])`.
- Produces: `prepare_patch(patch: str, reader: Callable[[str], str], *, max_patch_bytes: int = 1_000_000) -> PreparedPatch`.
- Produces stable exceptions: `InvalidPatchError`, `PatchConflictError`, `UnsafePatchPathError`, and `PatchLimitError`.

- [ ] **Step 1: Add locked parser dependency and RED contract tests**

Add `"unidiff>=0.7.5,<1"` to runtime dependencies and run `uv lock`. Add tests using this exact
update patch and equivalent add/delete fixtures:

```python
UPDATE = """--- a/src/value.py
+++ b/src/value.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""

def test_prepare_patch_updates_matching_text() -> None:
    plan = prepare_patch(UPDATE, lambda path: "VALUE = 1\n")
    assert plan.changes == (
        PreparedChange(
            path="src/value.py",
            operation=PatchOperation.UPDATE,
            before="VALUE = 1\n",
            after="VALUE = 2\n",
        ),
    )
```

Parameterized rejection tests must cover `/etc/passwd`, `../outside`, `.git/config`,
`.613-coding/state.sqlite`, source/target path mismatch, duplicate targets, binary markers, mode
headers, malformed hunks, NUL, invalid UTF-8 byte accounting, and aggregate size overflow.

- [ ] **Step 2: Run parser tests and capture RED**

Run:

```bash
uv run pytest tests/adapters/tools/test_patch.py -q
```

Expected: collection FAILS because `coding613.adapters.tools.patch` does not exist.

- [ ] **Step 3: Implement immutable patch values and path normalization**

Use frozen dataclasses or frozen Pydantic values. Normalize `a/` and `b/` prefixes, recognize
`/dev/null` only for add/delete, and return POSIX repository-relative paths. Reject empty parts,
`.`/`..`, NUL, absolute paths, protected roots, source/target mismatches, and duplicate targets
before calling the reader.

- [ ] **Step 4: Implement hunk application against in-memory source text**

Parse with `unidiff.PatchSet`. Walk each hunk from its declared source offset, require every
context and removed line to match exactly, copy unchanged gaps, append additions, and require the
final source cursor to remain within the original line array. Raise `PatchConflictError` on the
first mismatch. Require empty source for adds and complete source consumption for deletes.

- [ ] **Step 5: Run parser tests and static checks**

Run:

```bash
uv run pytest tests/adapters/tools/test_patch.py -q
uv run ruff check src/coding613/adapters/tools/patch.py tests/adapters/tools/test_patch.py
uv run mypy src/coding613/adapters/tools/patch.py
uv lock --check
```

Expected: all parser tests and checks PASS.

- [ ] **Step 6: Commit parser and lock**

```bash
git add pyproject.toml uv.lock src/coding613/adapters/tools/patch.py tests/adapters/tools/test_patch.py
git commit -m "feat: preflight strict unified diffs"
```

### Task 3: Descriptor-Relative Patch Commit

**Files:**
- Modify: `src/coding613/adapters/tools/filesystem.py`
- Modify: `src/coding613/adapters/tools/patch.py`
- Modify: `tests/adapters/tools/test_patch.py`
- Modify: `tests/adapters/tools/test_filesystem.py`

**Interfaces:**
- Consumes: `prepare_patch(patch: str, reader: Callable[[str], str], *, max_patch_bytes: int = 1_000_000) -> PreparedPatch` from Task 2.
- Produces: `PatchResult(added: int, updated: int, deleted: int, changed_files: tuple[str, ...])`.
- Produces: `PatchCommitError(message: str, changed_files: tuple[str, ...])`.
- Produces: `FilesystemTools.apply_patch(patch: str) -> PatchResult`.

- [ ] **Step 1: Add RED integration tests for add/update/delete and preflight atomicity**

Create one three-file patch, apply it, and assert exact content, deletion, counts, and sorted file
names. Add a second patch whose first hunk is valid and second hunk conflicts; assert neither file
changes. Add a symlink-parent case and assert the outside target remains unchanged.

- [ ] **Step 2: Run focused tests and capture RED**

Run:

```bash
uv run pytest tests/adapters/tools/test_patch.py -q
```

Expected: FAIL because `FilesystemTools.apply_patch` and `PatchResult` do not exist.

- [ ] **Step 3: Implement descriptor-relative staging helpers**

Add focused helpers that create missing parent directories one component at a time with
`os.mkdir(component, dir_fd=parent_fd)` followed by a no-follow open. For each add/update, create a
random hidden temp name with `O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC`, write all UTF-8 bytes,
flush, `fsync`, close, and commit with:

```python
os.replace(temp_name, target_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
```

Clean an uncommitted temp name descriptor-relatively in `finally`. Never use `Path.resolve()` as a
mutation authorization check.

- [ ] **Step 4: Implement preflight-then-commit orchestration**

Call `prepare_patch` with the existing bounded no-follow reader. Stage and commit changes in plan
order. Use the Task 1 delete primitive for deletes. Append a path only after its replace/unlink
succeeds. If an I/O error occurs, raise `PatchCommitError` with the sorted committed paths. Return
counts and sorted paths on success.

- [ ] **Step 5: Add and pass partial-I/O reporting regression**

Monkeypatch `os.replace` so the second replacement raises `OSError("disk full")`. Assert the
first target changed, the second did not, the exception contains only the first path, and no hidden
temporary file remains.

Run:

```bash
uv run pytest tests/adapters/tools/test_patch.py tests/adapters/tools/test_filesystem.py -q
uv run ruff check src/coding613/adapters/tools tests/adapters/tools
uv run mypy src/coding613/adapters/tools
git diff --check
```

- [ ] **Step 6: Commit the mutation engine**

```bash
git add src/coding613/adapters/tools/filesystem.py src/coding613/adapters/tools/patch.py tests/adapters/tools/test_patch.py tests/adapters/tools/test_filesystem.py
git commit -m "feat: apply patches through repository descriptors"
```

### Task 4: Tool Registry, Policy, Composition, And Evidence

**Files:**
- Modify: `src/coding613/adapters/tools/repository.py`
- Modify: `tests/application/test_composition.py`
- Modify: `tests/application/test_policy.py`
- Modify: `tests/application/test_tool_registry.py`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `DELIVERY_STATUS.md`

**Interfaces:**
- Consumes: `FilesystemTools.apply_patch(patch: str) -> PatchResult`.
- Produces: model-visible tool `apply_patch` with schema ID `coding613.tool.apply_patch.v1`.
- Produces: `_ApplyPatchExecutor.execute(call: ToolCall, context: ToolContext) -> ToolResult`.

- [ ] **Step 1: Write registry/composition RED tests**

Assert the registered definition has this schema shape and no extra fields:

```python
{
    "$id": "coding613.tool.apply_patch.v1",
    "type": "object",
    "properties": {
        "patch": {"type": "string", "minLength": 1, "maxLength": 1_000_000}
    },
    "required": ["patch"],
    "additionalProperties": False,
}
```

Dispatch an update patch through `build_repository_tools`, assert the target content, executor
output counts, per-call `changed_files`, and global changed-file list. Assert malformed arguments
fail schema validation before executor invocation. Assert strict mode asks, balanced/autonomous
allow configured writes, and disabled writes deny.

- [ ] **Step 2: Run focused tests and capture RED**

Run:

```bash
uv run pytest tests/application/test_tool_registry.py tests/application/test_policy.py tests/application/test_composition.py -q
```

Expected: FAIL because no `apply_patch` definition or executor is registered.

- [ ] **Step 3: Register executor and preserve accurate failure results**

Add `_ApplyPatchExecutor`. On success serialize add/update/delete counts and merge returned paths
into the shared list without duplicates. On `PatchCommitError`, return `success=False`, the stable
error class name, and the exception's exact `changed_files`; merge those paths globally because
they are real repository changes.

- [ ] **Step 4: Run all safe-mutation and loop integration tests**

Run:

```bash
uv run pytest tests/adapters/tools tests/application/test_tool_registry.py tests/application/test_policy.py tests/application/test_composition.py tests/application/test_loop.py -q
```

Expected: all focused tests PASS.

- [ ] **Step 5: Run complete verification**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
uv lock --check
git diff --check
```

Record exact counts and outputs. Do not copy the earlier 267-test result as fresh evidence.

- [ ] **Step 6: Request security and code-quality reviews**

Review the complete branch diff against
`docs/superpowers/specs/2026-08-09-safe-repository-mutations-design.md`. Require explicit review
of descriptor lifetime, final symlink semantics, parent swaps, temporary cleanup, preflight
coverage, partial-I/O reporting, schema limits, and redaction. Repair every Critical or Important
finding with its own RED/GREEN cycle.

- [ ] **Step 7: Update delivery records and commit**

Record Task 1-4 commit hashes, RED observations, fresh verification, reviewers, repairs, and the
Cube blocker now unlocked. Then run:

```bash
git add PLAN.md AGENT_LOG.md DELIVERY_STATUS.md
git commit -m "docs: record safe mutation verification"
```

- [ ] **Step 8: Integrate without losing user changes**

Inspect both worktrees with `git status --short`, merge the reviewed branch non-destructively into
main, rerun the complete verification on main, and record the merge/equivalent fast-forward hash.
Do not stage `.claude/`, the user-owned requirement documents, or `tmp/cube` in the harness merge.
