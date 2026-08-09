# Development Bootstrap

613 Coding uses `uv` for dependency management. Python source can be checked
before third-party dependencies are installed with:

```bash
PYTHONPATH=src python3 -m unittest tests.test_package.PackageTests.test_package_exposes_version
```

For an online environment, provision the locked development environment with:

```bash
uv sync --all-extras --frozen
```

For an air-gapped environment, provide a populated `uv` cache or wheelhouse,
then run:

```bash
uv sync --all-extras --frozen --offline
```

Run `uv run python scripts/bootstrap_dev.py` to verify provisioning. If it reports
`DEPENDENCY_PROVISIONING_BLOCKED`, install dependencies using one of the
commands above before running the canonical checks:

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

## Local TUI And Credentials

Start the local terminal interface with `uv run 613-coding`, prefill a task with
`uv run 613-coding "task"`, and continue a paused session with
`uv run 613-coding --resume latest`. Enter submits, Ctrl+J inserts a newline, Esc pauses a Run,
and `/resume` restores a selected session. The app keeps provider keys outside repository state.

On headless Linux, run a user D-Bus session with a Secret Service-compatible keyring backend before
setting credentials. Verify the backend is reachable before use:

```bash
uv run 613-coding credentials set openai
uv run 613-coding credentials status openai
```

Do not replace the OS keyring with a committed key or plaintext `.env`; `.env` remains an explicit,
process-visible development fallback.

## Release Artifacts

Docker is a build environment, not a product runtime service. It exports a Linux x86_64 glibc
binary, wheel, sdist, and checksums:

```bash
docker build --pull=false --target artifacts --output type=local,dest=dist .
scripts/smoke_artifacts.sh dist
```

GitHub Actions uploads these files on successful push and publishes them for `v*` tags. GitLab CI
retains the same verified `dist/` artifact. Docker Engine is separately required when the agent
starts isolated worker sandboxes.
