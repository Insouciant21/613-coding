# 613 Coding

613 Coding is a local Python coding-agent harness. Its Textual terminal interface drives an
objective feedback loop, SQLite-authoritative run history, LanceDB retrieval, Docker worker
sandboxes, and Supervisor/multi-agent orchestration.

## Install And Run

Python 3.12+ is managed with `uv`:

```bash
uv sync --all-extras
uv run pytest
uv run 613-coding
uv run 613-coding "repair the failing tests"
uv run 613-coding --resume latest
```

The root command opens the local TUI. `--repo PATH` selects a repository. Management commands
remain scriptable: `credentials`, `config`, `run`, `runs`, and `demo`.

Build a Python package and install the console command with:

```bash
uv build
uv tool install .
613-coding --help
```

The first self-contained Linux x86_64 executable and checksums are produced by the pinned Docker
artifact builder described in [`docs/deployment.md`](docs/deployment.md).

## Provider Configuration

Put non-secret provider metadata in `harness.toml`:

```toml
[llm]
provider = "openai-compatible"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
credential = "openai"
timeout_seconds = 60.0
```

Store the key in the operating-system keyring:

```bash
uv run 613-coding credentials set openai
uv run 613-coding credentials status openai
```

The key is read lazily and is never written to repository configuration, SQLite, LanceDB,
events, prompts, subprocess arguments, logs, artifacts, or worker containers. `.env` is an
explicit development fallback only: it is plaintext, process-visible, and ignored by Git.

## State, Sandbox, And Limits

`.613-coding/state.sqlite` is authoritative for projects, sessions, runs, events, approvals,
memory text, and audit data. LanceDB under `.613-coding/vectors` is a rebuildable index of
redacted vectors. If embeddings are unavailable, SQLite keyword retrieval remains available.

Worker execution requires Docker Engine. Workers are short-lived, non-root containers with a
read-only root, dropped capabilities, default-deny network, finite CPU/memory/PID/disk/time/output
limits, and no host credential or Docker socket mounts. These controls mitigate ordinary
untrusted-code impact but cannot guarantee protection from kernel or runtime vulnerabilities.

Interactive runs do not have a product-wide five-turn cap. Configure per-agent turns, total model
calls, wall time, or provider cost in `harness.toml`; unattended runs must set a finite model-call
or cost budget.

## Development And CI

Canonical checks are:

```bash
uv run pytest -q --ignore=tmp
uv run ruff check .
uv run mypy src
uv lock --check
```

GitLab CI and GitHub Actions run the offline tests, deterministic mechanism demo, quality checks,
and release artifact build. Historical deployment records remain in the delivery ledger; current
operation is local TUI/CLI and artifact distribution only.

## Supported Platforms

The Python package follows the platforms supported by Python 3.12, `uv`, and Docker Engine. The
initial self-contained executable target is Linux x86_64. Other platforms should use the Python
package until a platform-specific artifact is published.
