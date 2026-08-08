# CORE-04 Report

Status: implementation complete; scoped verification clean.

Commit: `a97e711` (`feat: persist runs and events in sqlite`).

TDD RED: the focused SQLite test failed during collection because `coding_harness.adapters.storage` did not exist.

GREEN: 5 SQLite tests passed for schema creation, run/event round trips, append ordering, store-boundary redaction, foreign-key rollback, and concurrent writes. Combined CORE-02 through CORE-04 regression: 16 tests passed. Ruff and mypy passed.

Scope: SQLite schema for projects, runs, iterations, events, approvals, task graphs, artifacts, memory, and embedding status; transactional run/event/iteration storage; ordered event reads; redaction before persistence.
