# CORE-03 Report

Status: implementation complete; scoped verification clean.

Commit: `e8b938f` (`feat: define harness dependency ports`).

TDD RED: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run --no-sync pytest tests/ports -q` failed during collection because `coding_harness.ports.embeddings` was missing.

GREEN: 4 focused port tests passed. Combined CORE-02/CORE-03 regression: 11 tests passed. Ruff and mypy passed for domain and ports.

Scope: typed LLM, embedding, tool, event-store, and policy Protocols plus strict `ModelContext`, `ModelMessage`, `ToolDefinition`, `LLMResponse`, `ToolContext`, `ToolResult`, and `PolicyDecision` values.
