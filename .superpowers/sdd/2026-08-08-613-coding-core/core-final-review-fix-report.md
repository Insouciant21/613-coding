# Core Final-Review Fix Report

Date: 2026-08-09 (Asia/Shanghai)
Actor: `/root/core_final_fix`
Base: `b26833f31336d75166dda3b6e0be6f8b9780d01b`
Scope source: `core-final-review-findings.md`

## Status

Implementation, review repair, and verification are complete. The implementation
commit is pending and will be recorded in the delivery-record follow-up.

The authorized current-workspace fallback was used because Git ref locks prevented
worktree creation. The user-owned untracked `.claude/` directory and the two untracked
source requirement documents under `docs/` were not read, altered, or staged.

## Root-Cause Confirmation

### Finding 1: SQLite connections were not closed

`SqliteEventStore` and `MemoryRepository` opened a fresh connection for each operation
with `with self._connect() as connection`. `sqlite3.Connection.__exit__` commits or
rolls back a transaction but does not close the connection, so both successful and
exceptional operations retained usable connection objects until garbage collection.

The focused tests exercise real repository operations through tracking subclasses and
then execute `SELECT 1` on every captured connection. Before the fix those queries
succeeded instead of raising `sqlite3.ProgrammingError`, deterministically proving the
connections remained open without relying on `/proc` or garbage collection.

### Finding 2: stale status writes were unconditional

`RunService._persist_status()` built a replacement from the `Run` loaded before the
loop and called unconditional `update_run()`. A deterministic racing store persisted a
newer `COMPLETED/SUCCESS` row immediately before that write; both `resume()` and
`cancel()` then replaced it and returned their stale summaries.

The storage contract now uses `compare_and_set_run(expected, replacement)`. SQLite
implements it as one `UPDATE` whose `WHERE` clause compares every persisted field from
the expected snapshot. A lost race returns `False`; `RunService` reloads the
authoritative row and returns a summary with its state and stop reason.

## TDD Evidence

### RED

Command:

```bash
uv run pytest tests/adapters/storage/test_sqlite.py tests/adapters/storage/test_memory.py tests/application/test_loop.py -q
```

Observed output before production edits:

```text
.FFF.......F...........FF.......................                         [100%]
6 failed, 42 passed in 1.59s
```

Expected failures:

- SQLite success-path connection remained usable.
- SQLite exception-path connection remained usable.
- `SqliteEventStore.compare_and_set_run` did not exist.
- `MemoryRepository` connection remained usable.
- `RunService.resume()` overwrote the competing terminal row.
- `RunService.cancel()` overwrote the competing terminal row.

### GREEN

Command after the minimum implementation:

```bash
uv run pytest tests/adapters/storage/test_sqlite.py tests/adapters/storage/test_memory.py tests/application/test_loop.py -q
```

Output:

```text
................................................                         [100%]
48 passed in 1.45s
```

After the Ruff-only transaction-context refactor, the same command produced:

```text
................................................                         [100%]
48 passed in 0.94s
```

### Review RED/GREEN

Independent review found that an already-terminal run could still be resumed into a
nonterminal state, and that terminal `cancel()` could return a stale loop-session
summary. The finding was confirmed with a second test-first cycle.

RED command:

```bash
uv run pytest tests/application/test_loop.py -q -k 'terminal_operations_return_authoritative_state_without_reentry'
```

RED output:

```text
FF                                                                       [100%]
2 failed, 33 deselected in 0.22s
```

GREEN output after adding terminal entry-point short-circuits and authoritative
summary reconciliation:

```text
..                                                                       [100%]
2 passed, 33 deselected in 0.10s
```

## Implementation

- Added transaction context managers that retain SQLite commit/rollback behavior and
  close each connection in an outer `closing()` context.
- Replaced unconditional run updates with an atomic full-snapshot CAS contract in the
  service port, SQLite adapter, and in-scope test store.
- Made `resume()` and `cancel()` return the authoritative persisted state and stop
  reason after a CAS conflict.
- Made both operations short-circuit already-terminal runs without re-entering the
  mutating loop path, and reconcile stale loop-session summaries to the run row.
- Added deterministic real-connection closure tests, SQLite CAS adapter coverage,
  service race coverage for both entry points, and unknown-run regression coverage.

## Changed Files

- `src/coding_harness/adapters/storage/sqlite.py`
- `src/coding_harness/adapters/storage/memory.py`
- `src/coding_harness/application/run_service.py`
- `tests/adapters/storage/test_sqlite.py`
- `tests/adapters/storage/test_memory.py`
- `tests/application/test_loop.py`
- `AGENT_LOG.md`
- `DELIVERY_STATUS.md`
- `.superpowers/sdd/2026-08-08-613-coding-core/core-final-review-fix-report.md`

`PLAN.md` will be updated with the implementation hash in the required separate
delivery-record commit.

## Verification

Focused tests:

```text
uv run pytest tests/adapters/storage/test_sqlite.py tests/adapters/storage/test_memory.py tests/application/test_loop.py -q
50 passed in 1.45s
```

Full suite:

```text
uv run pytest -q
126 passed in 1.68s
```

Static and repository gates:

```text
uv run ruff check .
All checks passed!

uv run mypy src
Success: no issues found in 44 source files

uv lock --check
Resolved 61 packages in 0.93ms

git diff --check
exit 0, no output
```

An intermediate scoped Ruff run reported only two `SIM117` context-combination fixes
and one import-order fix. Those mechanical refactors were applied, followed by the
fresh focused and full verification above.

## Self-Review

- Scope is limited to connection lifecycle, run CAS, service conflict reconciliation,
  focused tests, and required evidence.
- The CAS is a single SQLite statement; there is no read-then-unconditional-write gap.
- The comparison covers all persisted fields, not only status, so any intervening run
  change invalidates the expected snapshot.
- The transaction wrapper closes after normal exit and after an exception while the
  inner connection context preserves commit/rollback semantics.
- The tests use real SQLite connections and observable closed-connection behavior.
- Unknown-run behavior remains `KeyError` for both `resume()` and `cancel()`.
- Already-terminal `resume()` and `cancel()` return persisted terminal status/reason,
  do not enter the loop's run/cancel paths, and leave the row unchanged even if loop
  session state is stale.
- Mutation check: removing `closing()` breaks the closure tests; removing any CAS
  comparison that permits the tested stale snapshot breaks the adapter test; restoring
  unconditional service persistence breaks both race variants.

## Review And Concerns

Independent review found one Important terminal-entry gap and no Critical or Minor
issues. The separate RED/GREEN cycle above addresses the finding, and fresh full gates
pass. No implementation concern is known at this point. The three unrelated
user-owned untracked paths remain present and untouched.
