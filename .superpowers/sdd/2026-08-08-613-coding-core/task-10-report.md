# CORE-10 Report

Status: implementation complete; independent task review pending.

Commit: `2dd32f9` (`feat: implement feedback-driven agent loop`).

TDD RED: initial state-machine tests failed before the loop existed. Review REDs then exposed ignored post-provider cost exhaustion, duplicate dependency-factory construction, rejected approvals waiting indefinitely, and absent expiry termination.

GREEN: 12 focused approval/loop/demo tests passed. The full suite passed with 84 tests; Ruff, mypy, and lock check passed.

Scope: owned injectable AgentLoop, RunService, RunSummary, SQLite run status updates, persisted events and iteration records, policy allow/ask/deny, exact approval resume/reject/expiry, objective validation freshness, feedback-driven repair, cancellation/budget/no-progress terminals, and an offline wrong-edit to repair demo with guardrail and vector-memory checks.

Constraints: no real LLM, API key, network request, or high-level agent framework. The five-call limit is configured only by the deterministic demo.

## CORE-10 Fix Round 1

Review base: `f154bba`.

Findings addressed: SQLite-authoritative loop sessions and approvals; cross-process exact-action resume/reject/summary; real transition/schema/policy iteration evidence; terminal iterations for budgets, cancellation, no-progress, rejection/expiry, and dependency failures; provider/dependency exception states; completion blockers; terminal immutability; persisted demo terminal state; visible resource usage; assembled-context summaries.

TDD RED: 14 new loop/storage/demo behaviors initially failed because session and approval persistence ports did not exist, terminal records lacked required evidence, dependency exceptions escaped, terminal cancellation mutated state, and the demo left the SQLite run row at `RUNNING`.

GREEN: `uv run pytest tests/application/test_loop.py tests/application/test_approvals.py tests/demo/test_core_feedback.py tests/domain/test_models.py tests/adapters/storage/test_sqlite.py -q` passed with 36 tests. `uv run pytest -q` passed with 98 tests. `uv run ruff check .`, `uv run mypy src`, and `uv lock --check` passed.

Workflow concern: the fix implementer encountered a transient 503, resumed once, then stopped responding after reaching a green working tree without writing its report or commit. The controller preserved its changes, independently reran focused/full/static gates, audited the diff, and completed the report and commit. No unrelated user files were staged.

## CORE-10 Fix Round 1 - Recovery Hardening

Review base: `aceee71`.

Findings addressed: redaction for iteration/session/approval payloads; atomic approval claims and iteration/session/approval completion; current-policy re-evaluation before approved execution; execution-uncertainty pause behavior; cancellation invalidation; persisted classifier and budget-limit state; unresolved policy blockers; validated dependency return values; and exact model-call accounting.

TDD RED: `uv run pytest tests/application/test_approvals.py tests/application/test_loop.py tests/adapters/storage/test_sqlite.py -q` failed with 11 failures and 28 passes, covering non-atomic claims, leaked payloads, stale approvals, policy bypass, cleared policy risk, malformed dependency returns, and rejected budget usage. Additional focused RED tests for atomic loop-state rollback, classifier restoration, and secret-bearing action denial failed 3 of 3 before implementation.

GREEN: `uv run pytest tests/application/test_approvals.py tests/application/test_feedback.py tests/application/test_policy.py tests/application/test_loop.py tests/adapters/storage/test_sqlite.py -q` passed with 66 tests. `uv run pytest -q` passed with 110 tests. `uv run ruff check .`, `uv run mypy src`, `uv lock --check`, and `git diff --check` passed.

Implementation commit: `06b397e` (`fix: harden persisted agent loop recovery`). Unrelated untracked user and course files were not staged.
