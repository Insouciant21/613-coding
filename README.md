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

## TUI Workflow

Type a task and press Enter to start a streamed Run. Use Ctrl+J for a newline, Esc to cooperatively
pause the active Run, and Ctrl+Q to exit. A paused session resumes with the same Run ID through
`613-coding --resume latest`; pending approvals are restored after restart. In the TUI, `/help`,
`/model`, `/permissions`, `/runs`, `/resume`, `/clear`, and `/quit` provide the corresponding local
workflows. `A` and `R` approve or reject the displayed exact-action request.

`/permissions list` displays project rules; `/permissions allow TOOL`, `/permissions deny TOOL`,
and `/permissions clear TOOL` update them through the application service. `/context` reports
bounded transcript accounting, `/compact` stores an additive redacted summary, `/cost` shows
resource usage, and `/doctor` runs injected local diagnostics. Compaction never deletes the
authoritative transcript. Prefix a slash with `//` when it should be sent as prompt text.

Build a Python package and install the console command with:

```bash
uv build
uv tool install .
613-coding --help
```

The first self-contained Linux x86_64 executable and checksums are produced by the pinned Docker
artifact builder described in [`docs/deployment.md`](docs/deployment.md).

## Prompt, Print, And Stream Mode

The root command accepts the same prompt workflow as the TUI. `-p`/`--print` runs prompts without
opening Textual, `--continue` selects the latest session, and `--resume SESSION_ID` (or
`--resume latest`) continues a persisted session:

```bash
613-coding -p --repo . --output-format text "repair the tests"
613-coding -p --continue --output-format json "run validation"
613-coding -p --resume latest --permission-mode strict "inspect the approval"
```

Prompts can come from stdin. Text input is the default; stream input is one JSON object per line
with `{"schema_version":1,"type":"user.message","text":"..."}`:

```bash
printf '%s\n' '{"schema_version":1,"type":"user.message","text":"review the diff"}' \
  | 613-coding -p --input-format stream-json --output-format stream-json
```

`--output-format` accepts `text`, `json`, or `stream-json`. JSON emits a versioned `RunEnvelope`
(or `SessionEnvelope` for multiple prompts); stream JSON emits ordered versioned session events,
including `diagnostic.completed` when `--verbose` is set.
Exit codes are `0` success, `1` general failure, `2` invalid input, `3` policy blocked, `4`
provider unavailable, and `5` budget/timeout stop. `--verbose` adds diagnostics and resource
usage without exposing credentials.

The options `--model`, `--system-prompt`, `--append-system-prompt`, `--allowed-tools` /
`--allowedTools`, `--disallowed-tools` / `--disallowedTools`, `--add-dir`, and budget flags are
passed through the same `PromptRequest` used by the TUI. `--permission-mode` accepts `strict`,
`balanced`, or `autonomous`; hard safety rules always remain active.

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

Chat and tool calls use the official OpenAI Python SDK; `base_url` keeps OpenAI-compatible
endpoints supported. The SDK client is created lazily with zero automatic retries so Harness model
call budgets and provider errors remain deterministic.

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

MCP transport is not part of this parity slice. The tool registry is injectable and versioned;
future MCP integration must pass through the same schema, policy, approval, and redaction
boundaries rather than bypassing the owned AgentLoop.

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
