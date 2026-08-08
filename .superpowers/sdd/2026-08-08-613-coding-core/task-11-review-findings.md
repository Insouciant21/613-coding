# CORE-11 Task Review Findings

Review range: `a513c95..552593e`

## Important

1. `KeyringCredentialStore.clear()` has no test for a backend that raises while deleting a missing entry. Its recovery call to `get_password` is also unguarded, so a backend double-fault escapes as a raw exception instead of `CredentialError`. Add focused RED tests for missing-delete idempotency and delete/read double-failure, then map the latter to the application error.
2. `resolve()` suppresses a real `CredentialStatus.source` / `SecretReference.source` type mismatch with `# type: ignore[arg-type]`. Narrow or branch on `source` explicitly so `source="none"` cannot reach `SecretReference` after future refactors.

## Minor Deferred

1. Whitespace-only credential values pass validation.
2. `SecretReference.configured` is always true and carries no information.

## Review Verdict

Spec compliance: compliant.

Task quality: needs fixes.
