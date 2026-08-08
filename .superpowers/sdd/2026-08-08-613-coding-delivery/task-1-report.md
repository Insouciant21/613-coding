# DELIVERY-01 Report: Configuration And Credential Commands

## Scope

- Added strict `HarnessConfig` TOML loading from `harness.toml`, including canonical repository roots, balanced-mode defaults, argv-only validation commands, policy flags, and `BudgetLimits` validation.
- Added Typer `config check` and `credentials set/status/update/clear` commands.
- Kept credential commands on the existing `CredentialService` and `KeyringCredentialStore` boundary. Secret input is hidden and status output contains only provider/configured/source metadata.
- Added focused tests for TOML parsing, defaults, budgets, path validation, argv validation, hidden credential input, status redaction, and clear behavior.

## TDD Evidence

RED (before implementation):

```text
uv run --no-sync pytest -q tests/config/test_config.py tests/cli/test_credentials.py
2 collection errors: ModuleNotFoundError for coding_harness.config and coding_harness.cli
```

GREEN (after implementation):

```text
uv run --no-sync pytest -q tests/config/test_config.py tests/cli/test_credentials.py
7 passed in 0.09s
```

## Verification

- `uv run --no-sync pytest -q`: 201 passed in 2.13s.
- `uv run --no-sync ruff check src/coding_harness/config.py src/coding_harness/cli tests/config/test_config.py tests/cli/test_credentials.py`: passed.
- `uv run --no-sync mypy src/coding_harness/config.py src/coding_harness/cli`: passed with no issues.
- `git diff --check`: passed before commit.
- CLI smoke: `config check --repo .` exited 0 and printed only canonical path, mode, and budget metadata.

## Commits

- `2a53a73` - `feat: add configuration and credential commands`
- Evidence records are appended in the follow-up documentation commit for this task.

## Concerns

- The default keyring backend remains an operator prerequisite; tests inject a fake credential service and never require a system keyring.
- The root CLI aggregator is intentionally limited to DELIVERY-01 commands; run/demo commands belong to DELIVERY-02.
