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
remain scriptable: `credentials`, `providers`, `config`, `run`, `runs`, and `demo`.

## TUI Workflow

Type a task and press Enter to start a streamed Run. Use Ctrl+J for a newline, Esc to cooperatively
pause the active Run, and Ctrl+Q to exit. A paused session resumes with the same Run ID through
`613-coding --resume latest`; pending approvals are restored after restart. In the TUI, `/help`,
`/model`, `/config`, `/permissions`, `/runs`, `/resume`, `/clear`, and `/quit` provide the
corresponding local workflows. `A` and `R` approve or reject the displayed exact-action request.

Typing `/` opens the available slash-command list. Continue typing to filter it, press `Tab` to
complete, and use `↑`/`↓` to cycle through matching commands; the same keys navigate prompt history
when no completion is active. The composer footer repeats the common shortcuts, and `/help` shows
the full command catalog. Large tool results show a bounded preview; press `Ctrl+T` to expand or
collapse the latest result. Use `//` when a normal prompt should begin with a literal slash.

`/permissions list` displays project rules; `/permissions allow TOOL`, `/permissions deny TOOL`,
and `/permissions clear TOOL` update them through the application service. `/provider list`,
`/provider show NAME`, and `/provider use NAME` inspect or switch user-wide provider profiles.
`/context` reports bounded transcript accounting, `/compact` stores an additive redacted summary,
`/cost` shows resource usage, and `/doctor` runs injected local diagnostics. `/config` opens a
keyboard-selectable menu for policy toggles, safety-budget presets, providers, and the active
provider's model/reasoning choices; `/config show` remains available for the full text summary.
`/config set mode autonomous` and `/config set budgets.total_model_calls 20` are still available
for scripted use. `/provider` and `/model` without arguments open the corresponding selection
menus. Changes are validated and atomically persisted, then reloaded for subsequent runs.
Compaction never deletes the authoritative transcript. Prefix a slash with `//` when it should be
sent as prompt text.

Build a Python package and install the console command with:

```bash
uv build
uv tool install .
613-coding --help
```

When updating a local checkout, refresh an existing global tool environment with
`uv tool install --force .`; otherwise the shell may continue running an older copy of the
configuration model or UI dependencies. `uv run 613-coding` always uses the current checkout.

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

If a provider returns text without a tool action, 613 Coding gives it one repair turn. A second
text-only response is recorded as `no_progress` and stops the run, rather than consuming the full
model-call budget in a repeated planning loop.

Objective validation is required after repository changes, not for every read-only inspection.
Read-only tasks may finish once the requested evidence is collected; call `run_validation` only
when the user asks for it or when a change needs verification. Its `argv` argument must be the
exact JSON array shown in the configured validation command description (for example,
`["bash", "scripts", "verify.sh"]`).

Writes are batched: the loop does not spawn validation after each file mutation. The model can
request one declared validation at the end of a coherent change set; if it goes straight to
`finish`, the harness performs that task-end validation once. A successful no-op write is checked
immediately so deterministic `no_progress` feedback is preserved. At the beginning of a run the
model also calls `set_task_budget` with `standard` (16,384 tokens) or `complex` (128,000 tokens);
the harness clamps the
selected output-token profile to the configured ceiling and persists the choice. Agent turns are
not capped by that profile; the conversation continues while context is compacted as it reaches
its bound.

Large tool results are shown as a short redacted preview in the TUI. The loop retains up to
10,000,000 characters of a tool result internally; press `Ctrl+T` to expand the latest result,
with the expanded terminal view still bounded at 1 MiB for terminal safety.
Validation previews are limited to 10 lines (with a safety cap for a single extremely long line),
and use the same `Ctrl+T` expansion. The context metadata exposes `cache_prefix_sha256`; the stable
system guidance and task are placed before the changing run ledger/events so compatible Responses
providers can reuse their prompt-cache prefix.

Each model turn receives a bounded repository context assembled by the harness. The repository
root may provide `AGENTS.override.md`, `AGENTS.md`, `CLAUDE.local.md`, or `CLAUDE.md`; their
redacted guidance is capped at 32 KiB and is combined with a deterministic run ledger containing
recent tool, validation, feedback, and changed-file state. Older dynamic event output is compacted
when the context budget is reached, while the task, ledger, and newest evidence are retained.
Configure that dynamic compaction window as `context_window_chars` in the active user provider
profile (default `256000`), and switch profiles with `/provider use NAME`. The bound is
character-based rather than tokenizer-based so offline tests and OpenAI-compatible providers share
the same deterministic behavior; a configuration reload applies the new value to future turns.
Independent read-only calls returned in one model turn may run concurrently; writes, approvals,
and validation always remain ordered through the policy-controlled loop.

The options `--model`, `--system-prompt`, `--append-system-prompt`, `--allowed-tools` /
`--allowedTools`, `--disallowed-tools` / `--disallowedTools`, `--add-dir`, and budget flags are
passed through the same `PromptRequest` used by the TUI. `--permission-mode` accepts `strict`,
`balanced`, or `autonomous`; hard safety rules always remain active.

## Provider Configuration

Provider profiles and budgets are user-wide. On Linux/macOS they are stored in
`$XDG_CONFIG_HOME/613-coding/config.toml` (normally `~/.config/613-coding/config.toml`); on Windows
use `%APPDATA%/613-coding/config.toml`. `harness.toml` contains project policy only. Create and
switch profiles with:

```bash
613-coding providers add ai2 --base-url https://ai2.example/v1 --model gpt-5.6-terra \
  --api responses --credential ai2 --active
613-coding providers key-set ai2
613-coding providers list
613-coding providers use ai2
613-coding providers models add ai2 fast --model gpt-5.6-flash --active
613-coding providers models add ai2 deep --model gpt-5.6 --reasoning-effort high
613-coding providers models list ai2
613-coding providers models use ai2 deep
613-coding providers models reasoning ai2 deep high
```

The resulting non-secret profile is equivalent to:

```toml
active_provider = "ai2"

[providers.ai2]
provider = "openai-compatible"
api = "responses"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
credential = "openai"
timeout_seconds = 60.0
max_output_tokens = 128000
context_window_chars = 256000
streaming = false

[providers.ai2.models.fast]
model = "gpt-5.6-flash"
reasoning_effort = "low"

[providers.ai2.models.deep]
model = "gpt-5.6"
reasoning_effort = "high"
max_output_tokens = 128000

[budgets]
total_model_calls = 30
```

Chat and tool calls use the official OpenAI Python SDK; `base_url` keeps OpenAI-compatible
endpoints supported. Select `api = "responses"` for an endpoint implementing `/v1/responses`.
Each provider profile can contain multiple model aliases under `[providers.NAME.models.ALIAS]`.
Selecting an alias applies its model identifier and optional `reasoning_effort`, output-token,
context-window, and streaming overrides. Use `providers models use` or the TUI `/model` menu to
switch aliases without changing credentials or endpoint metadata. The same menu exposes low, med,
medium, high, xhigh, and max reasoning choices for every alias; arbitrary provider-defined
levels are also accepted by the config and CLI. The CLI equivalent is
`providers models reasoning PROVIDER ALIAS LEVEL`.
Anthropic Messages is supported through the official `anthropic` Python SDK: configure
`provider = "anthropic"`, `api = "anthropic"` (or `api = "messages"`), an Anthropic base URL, and
the keyring credential name. Any configured non-low reasoning level maps to Anthropic extended thinking when the
configured output budget leaves the required thinking-token headroom.
The Responses adapter maps output items and function calls back into 613's own loop; it does not
delegate orchestration or tool execution to an SDK agent runner. `streaming = true` enables SDK
stream events for either API, while the default is non-streaming to keep latency and output-token
budgets explicit. The SDK client is created lazily with zero automatic retries so Harness model
call budgets and provider errors remain deterministic. The harness owns a bounded five-retry
window after the initial request for transient provider failures, matching Codex's visible `1/5`
through `5/5` reconnect behavior (at most six total requests). Authentication and other
client-side HTTP 4xx request errors fail fast; rate limits, transport failures, and 5xx responses
remain eligible for the five-retry window.

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

Interactive runs do not have a product-wide five-turn cap or a model-selected per-agent turn cap.
The context assembler compacts older evidence when the context bound is reached. Total model calls,
wall time, and provider cost remain optional safety limits in the user configuration; unattended runs
must set a finite model-call or cost budget. The legacy `per_agent_turns` setting is retained for
config compatibility but is informational only.

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
