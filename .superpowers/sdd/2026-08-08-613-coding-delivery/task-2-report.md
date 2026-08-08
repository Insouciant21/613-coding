# DELIVERY-02 Report: Core CLI Run And Approval Commands

## TDD Evidence

- RED: `uv run pytest tests/cli/test_runs.py -q` failed during collection because `coding_harness.cli.main` was absent.
- GREEN: focused CLI/config/credential suite passed 11 tests; full suite passed 205 tests.

## Verification

- `uv run ruff check src/coding_harness/cli tests/cli/test_runs.py`: passed.
- `uv run mypy src/coding_harness/cli`: passed with no issues.
- Typer root `--help` listed `demo`, `credentials`, `config`, `run`, and `runs`.
- JSON and table serializers preserve model metadata; service errors exit nonzero and are written to stderr.

## Boundary

The CLI owns argument parsing and presentation only. Run state, approvals, cancellation, and demo behavior remain in injected application/demo services. The service factory is explicit so a distribution entrypoint can supply its SQLite-backed runtime without embedding policy in commands.
