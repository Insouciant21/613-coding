# CORE-05 Report

Status: implementation complete; scoped verification clean.

Commit: pending at report creation.

TDD RED: adapter tests failed during collection because `coding_harness.adapters.llm` did not exist.

GREEN: 7 focused adapter tests passed. Combined CORE-02 through CORE-05 regression: 23 tests passed. Ruff and mypy passed.

Scope: deterministic `ScriptedLLM` response order, deep context/tool snapshots, script exhaustion, one-request OpenAI-compatible mapping, validated tool-call parsing, and typed timeout/authentication/rate-limit/HTTP/response errors. Tests use only HTTPX MockTransport and no real provider.
