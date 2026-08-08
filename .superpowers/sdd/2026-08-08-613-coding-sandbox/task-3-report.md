# SANDBOX-03 Implementation Report

Status: DONE

## Scope

- Added `DockerSandboxRuntime` with manager-owned workspace creation, container create/start/exec/export/destroy lifecycle, opaque handle identity checks, timeout mapping, output caps, and finally-safe cleanup.
- Added `container_options` with pinned image, non-root user, read-only root, dropped capabilities, no-new-privileges, disabled networking, bounded memory/PIDs/CPU, and only the copied workspace mount.
- Added fake Docker client tests for lifecycle order, hardened options, non-zero results, output truncation, execution timeouts, daemon/start failures, artifact export, cleanup, and forged handles.

## TDD Evidence

RED was observed before implementation:

```text
UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest tests/sandbox/test_docker_runtime.py -q
ModuleNotFoundError: No module named 'coding_harness.adapters.sandbox.docker_runtime'
```

GREEN after the initial implementation passed 5 tests. Additional TDD hardening covered runtime-enforced timeout, start-failure cleanup, and same-UUID forged handles; the final focused runtime suite passed 8 tests.

## Final Verification

```text
UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest tests/sandbox -q
34 passed

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest -q
160 passed

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run ruff check .
All checks passed!

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run mypy src
Success: no issues found in 52 source files

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv lock --check
Resolved 61 packages

git diff --check
passed
```

Docker daemon availability was checked with `docker info` (`29.6.2`), but the local daemon had no pinned worker image; guarded real-container smoke was therefore skipped rather than pulling an unapproved image. Fake-client coverage remains the authoritative offline gate.

## Security Boundary

- The original repository is never mounted; `WorkspaceManager` copies it to a temporary task workspace and only that copy is mounted at `/workspace`.
- Docker socket, SSH agent, home, and credential paths are absent from the options. ALLOWLIST specs remain network-disabled until SANDBOX-04 supplies an exact approved network.
- Runtime records are keyed by the identity of the returned frozen `SandboxHandle`; forged handles with the same UUID cannot access or destroy a live container.
- Timeout and output limits are mapped to `CommandResult` without persisting raw Docker exceptions as event data.

## Commits

- `bf129cd` — `feat: run workers in temporary docker containers`
- `3ec6ac1` — `fix: harden docker runtime handle ownership`
