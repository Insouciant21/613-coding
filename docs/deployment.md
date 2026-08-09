# Local Distribution And Operations

613 Coding is a local TUI/CLI application. There is no product server process to configure.

## Python Package

Use Python 3.12+ managed by `uv`:

```bash
uv sync --all-extras --frozen
uv run pytest -q --ignore=tmp
uv build
uv tool install .
613-coding --help
```

Run a repository task with `uv run 613-coding --repo PATH "task"`, resume with
`uv run 613-coding --resume latest`, and use the management commands for credentials, config, runs,
and deterministic demos.

## Credentials And Configuration

Configure only non-secret provider metadata in `harness.toml` and store the provider key through
the OS keyring. Status output is metadata-only. `.env` is an explicit development fallback with
plaintext and process-environment exposure risk; it is ignored by Git and never copied into build
layers.

SQLite remains the source of truth for runs, events, approvals, sessions, task graphs, memory text,
and audit state. LanceDB stores redacted, rebuildable vectors linked to SQLite IDs.

## Artifact Verification

The pinned multi-stage Dockerfile is an artifact builder only. It exports a Linux x86_64 executable,
wheel, sdist, and `SHA256SUMS`; it does not start a product service. Verify downloaded files before
installation:

```bash
sha256sum -c SHA256SUMS
uv tool install 613_coding-*.whl
./613-coding
```

Build the same files locally with Docker Engine:

```bash
docker build --pull=false --target artifacts --output type=local,dest=dist .
scripts/smoke_artifacts.sh dist
```

The standalone executable runs without host Python, but requires a compatible Linux x86_64 glibc
runtime. The Python package is the portable option on platforms without a published executable.

## Worker Sandbox

Real repository tool execution requires Docker Engine. Each worker is short-lived and runs as a
non-root user with a read-only root filesystem, dropped Linux capabilities, default-deny network,
bounded CPU/memory/PIDs/disk/time/output, and cleanup after terminal state. The original repository,
host home, credential directories, SSH agents, and Docker socket are never mounted writable. These
limits reduce ordinary untrusted-code impact but do not protect against kernel or runtime
vulnerabilities.

## CI

GitLab CI has a required `unit-test` job and builds the same artifacts as the Docker builder. GitHub
Actions runs the offline suite, deterministic mechanism demo, quality checks, artifact smoke, and
artifact upload. A `v*` GitHub tag releases the exact verified binary, wheel, sdist, and
`SHA256SUMS`; GitLab retains `dist/` after its dependent Python/uv artifact smoke. No network access
or real provider key is needed for unit tests.

## Limitations

The initial standalone release supports Linux x86_64 with a compatible glibc loader. Interactive
model calls require a configured OpenAI-compatible endpoint and keyring entry. Unattended runs
require a finite model-call or cost budget. Docker Engine and a compatible storage driver are
prerequisites for worker sandbox runs.
