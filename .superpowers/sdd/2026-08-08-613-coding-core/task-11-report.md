# CORE-11 Task Report: Keyring Credentials

## Result

Implemented `CredentialService` and the injected `KeyringCredentialStore` boundary. Provider credentials are written to the OS keyring, status and opaque references are secret-free, provider names are isolated, and `.env` lookup is disabled unless explicitly enabled.

## TDD Evidence

RED (before implementation):

```text
uv run pytest tests/adapters/credentials/test_keyring.py -q
ModuleNotFoundError: No module named 'coding_harness.adapters.credentials'
```

GREEN after implementation:

```text
uv run pytest tests/adapters/credentials/test_keyring.py -q
4 passed in 0.03s
```

Full verification:

```text
uv run pytest -q                    114 passed in 1.23s
uv run ruff check .                 All checks passed!
uv run mypy src/.../credentials.py .../keyring.py
                                    Success: no issues found in 2 source files
```

The focused tests cover hidden-input keyring storage, redacted status/captured output, update/clear, missing keys, provider isolation, and opt-in environment fallback.

## Self-review

- Secret material is accepted only at the write boundary and is not present in `CredentialStatus` or `SecretReference` representations.
- Keyring backend is injectable, so tests remain offline and deterministic.
- Environment fallback uses a provider-derived variable and is opt-in (`allow_env_fallback=False` by default).
- Clearing a missing key is idempotent across keyring backend behaviors.

## Concerns

`SecretReference` intentionally contains metadata only; a future provider integration will need a separately governed secret-resolution operation that injects the value directly into the provider call without persisting or logging it. The task brief did not authorize that broader integration.

## Commit

Pending commit from the prescribed command:

```text
feat: secure provider credentials
```

---

## CORE-11 Fix Round 1

### Root Causes

Important finding 1 (double-fault in clear): `clear()` catches the backend exception raised when deleting a missing entry but then calls `get_password` without any guard. If the backend also raises on that read, the exception escapes unwrapped as a raw keyring error instead of a `CredentialError`. The fix wraps the recovery `get_password` call in a nested try/except, not the same try/except, and maps any exception to `CredentialError`.

Important finding 2 (type-ignore in resolve): `source` on `CredentialStatus` admits the literal `"none"`, but `SecretReference` does not accept `"none"` as a valid source. Rather than branching on the value before constructing `SecretReference`, the original code silenced the mismatch with `# type: ignore[arg-type]`. The fix adds an explicit branch so `source="none"` can never reach the `SecretReference` constructor.

### TDD Evidence

RED (before fix):

```text
uv run pytest tests/adapters/credentials/test_keyring.py -q
FAILED tests/adapters/credentials/test_keyring.py::test_clear_double_fault_raises_credential_error
  Exception: keyring: get_password failed
1 failed, 5 passed in 0.05s
```

### Files Changed

- src/coding_harness/adapters/credentials/keyring.py
- tests/adapters/credentials/test_keyring.py
- .superpowers/sdd/2026-08-08-613-coding-core/task-11-report.md

### GREEN Verification

```text
uv run pytest tests/adapters/credentials/test_keyring.py -q
6 passed in 0.04s

uv run pytest -q
116 passed in 1.72s

uv run ruff check .
All checks passed!

uv run mypy src
Success: no issues found in 44 source files

uv lock --check
Resolved 61 packages in 0.60ms

git diff --check
(exit 0, no output)
```

### Deferred

The two Minor findings (whitespace-only credential values pass validation; `SecretReference.configured` is always true) remain deferred.

### Concerns

None.
