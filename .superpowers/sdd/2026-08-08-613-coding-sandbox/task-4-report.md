# SANDBOX-04 Implementation Report

Status: DONE

## Scope

- Added `SandboxPolicyConfig` for approved resource bounds, network allowlists, environment names, and image digests.
- Added deterministic `SandboxPolicy.validate` and `evaluate_result` composition. Hard worker constraints and credential environment rules precede mode decisions; autonomous mode cannot override them.
- Resource overages, command timeout, explicit resource exhaustion, and output truncation become `SandboxDecision(resource_exhausted=True)` with stable rule IDs.

## TDD Evidence

RED was observed before implementation:

```text
UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest tests/sandbox/test_security_policy.py -q
ImportError: cannot import name 'SandboxPolicyConfig' from coding_harness.application.policy
```

Final focused policy suite: 8 passed.

## Verification

```text
UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest tests/sandbox/test_security_policy.py -q
8 passed

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest -q
168 passed

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run ruff check .
All checks passed!

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run mypy src
Success: no issues found in 53 source files

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv lock --check
Resolved 61 packages

git diff --check
passed
```

## Boundaries

- Default network is deny; ALLOWLIST requires `allow_network=True` and a non-empty exact tuple, which is returned in the decision for audit. The runtime remains network-disabled until an exact Docker network is supplied by policy integration.
- Approved image sets are optional but, when configured, require exact digest membership. Digest syntax is always pinned `sha256:<64 hex>`.
- Environment names are checked against both credential hard names and the configured allowlist. Resource fields are compared independently against finite configured maxima.
- Result handling is deterministic and does not delegate policy classification to an LLM.
