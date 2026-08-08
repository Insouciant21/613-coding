# CORE-10 Report

Status: implementation complete; independent task review pending.

Commit: `2dd32f9` (`feat: implement feedback-driven agent loop`).

TDD RED: initial state-machine tests failed before the loop existed. Review REDs then exposed ignored post-provider cost exhaustion, duplicate dependency-factory construction, rejected approvals waiting indefinitely, and absent expiry termination.

GREEN: 12 focused approval/loop/demo tests passed. The full suite passed with 84 tests; Ruff, mypy, and lock check passed.

Scope: owned injectable AgentLoop, RunService, RunSummary, SQLite run status updates, persisted events and iteration records, policy allow/ask/deny, exact approval resume/reject/expiry, objective validation freshness, feedback-driven repair, cancellation/budget/no-progress terminals, and an offline wrong-edit to repair demo with guardrail and vector-memory checks.

Constraints: no real LLM, API key, network request, or high-level agent framework. The five-call limit is configured only by the deterministic demo.
