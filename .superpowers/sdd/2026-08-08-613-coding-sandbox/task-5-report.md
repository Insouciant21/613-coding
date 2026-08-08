# SANDBOX-05 Demonstration Report

Status: DONE

## Scope

`run_sandbox_demo(runtime)` demonstrates two isolated workers, hard-denied privileged and Docker-socket actions, default-deny network, deterministic timeout/resource mapping, artifact export, and terminal cleanup using the injectable runtime port.

## Verification

```text
UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest tests/demo/test_sandbox.py -q
1 passed

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run python -c '...run_sandbox_demo(FakeSandboxRuntime())...'
{"isolated_workers":true,"dangerous_mount_blocked":true,"docker_socket_blocked":true,"network_denied":true,"resource_timeout_mapped":true,"artifact_exported":true,"cleanup_completed":true}

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run pytest -q
169 passed

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run ruff check .
All checks passed!

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv run mypy src
Success: no issues found in 54 source files

UV_CACHE_DIR=/tmp/613-controller-uv-cache uv lock --check
Resolved 61 packages

git diff --check
passed
```

Real Docker smoke remains guarded: the daemon is available, but no approved pinned worker image is local, so the demo does not pull or execute an unapproved image.

## Commit

- `fb1c222` — `test: demonstrate container sandbox boundaries`
