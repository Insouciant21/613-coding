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
Typing `/` shows slash-command candidates; `Tab` completes and `↑`/`↓` cycles candidates (or prompt
history when no candidate is active). `/help` prints the complete catalog, and `//` escapes a literal
slash at the beginning of a normal prompt. Large tool results use a bounded preview; `Ctrl+T`
expands or collapses the latest result.

`/provider` opens the user-wide provider manager. Its menu can add a profile, switch the active
profile, edit endpoint/model/runtime metadata, delete a profile, set or clear its keyring key, and
confirm destructive actions before persistence. Scriptable equivalents are `/provider add`,
`/provider edit NAME`, `/provider remove NAME`, `/provider key NAME`, and
`/provider clear-key NAME`; API keys are entered through a password field and are never rendered
in the conversation log.

The composer has no hover-only tooltip, so its focus outline does not cover the input area. The
bottom usage and status rows remain visible in narrow terminals. If a provider emits text without
an action, the loop allows one repair turn and then records deterministic `no_progress` instead of
spending the entire configured model-call budget on identical planning text.

Transient provider failures use a harness-owned five-retry window after the initial request (`1/5`
through `5/5`), matching Codex's bounded reconnect behavior and allowing at most six total requests.
The SDK itself remains configured with zero automatic retries so the loop can persist each retry and
enforce its model-call, wall-clock, and cost budgets. Authentication and other client-side HTTP 4xx
request errors are non-retryable; rate limits, transport failures, and 5xx responses may be retried.

For scripts, use `uv run 613-coding -p "task"`, `--continue`, `--resume latest`,
`--input-format stream-json`, and `--output-format text|json|stream-json`. Stream input is one
versioned `user.message` JSON object per line. `--permission-mode`, model/system-prompt options,
tool allow/deny filters, and budget flags are shared with the TUI. `/permissions`, `/context`,
`/compact`, `/cost`, and `/doctor` are application-service commands; no adapter writes SQLite
directly.

Validation is mutation-aware: a read-only inspection does not need to invoke `run_validation`,
while a run that changed repository files must obtain fresh passing validation before `finish`.
The loop batches coherent writes and does not validate after each mutation. A model may call the
declared validation tool once at the task boundary; an omitted request is supplied by the harness
at `finish`. A successful no-op mutation remains an immediate validation case for deterministic
no-progress classification. The first model turn may select a schema-validated `set_task_budget`
profile (`standard` = 16,384 tokens or `complex` = 128,000 tokens); the selected output-token
ceiling is persisted for
resume. Agent turns are not capped; context compaction controls conversation length.
When calling `run_validation`, pass `argv` as the exact JSON array from the tool description, such
as `["bash", "scripts", "verify.sh"]`, rather than one shell-formatted string.

Large tool results are shown as a redacted preview; `Ctrl+T` expands the latest result up to the
1 MiB safety cap.
Validation output is previewed by 10 lines and can also be expanded with `Ctrl+T`. Tool and
validation text is rendered as plain Rich `Text`, avoiding syntax-highlighting backgrounds for
large command logs. The context assembler places the stable worker/repository/memory guidance and
task before changing ledger/event evidence and records a `cache_prefix_sha256` diagnostic; this is
the cache-friendly prefix boundary, not a provider-specific orchestration shortcut.

The model context is assembled on every loop turn from repository guidance and persisted evidence.
Configure the dynamic compaction window as `context_window_chars` in the active user provider
profile (default `256000`) and switch profiles with `/provider use NAME`. The bound is
character-based rather than tokenizer-based so offline tests and OpenAI-compatible providers share
the same deterministic behavior; a configuration reload applies the new value to future turns.
`AGENTS.override.md`, `AGENTS.md`, `CLAUDE.local.md`, and `CLAUDE.md` are read from the selected
repository root, redacted, and capped at 32 KiB. A deterministic ledger summarizes tool calls,
changed files, validation, and feedback without replaying unbounded output. When the dynamic
context budget is exceeded, old event messages are compacted while the task, ledger, and newest
evidence remain. A model response containing multiple independent read-only calls is dispatched
concurrently; mutation, approval, and validation calls remain serialized.

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

Responses-hosted web search, file search, code interpreter, image generation, remote MCP, tool
search, programmatic calling, shell/local-shell, apply-patch, computer, custom, and namespace
tools are opt-in provider definitions. Local `run_command` and Responses shell calls are argv-only
and bounded; apply-patch operations pass through the same repository policy and conflict recovery.
The Responses adapter reconstructs typed shell/patch output items for the next model request.
Computer, custom, and client-side tool-search calls remain explicit adapter-not-configured results
until an interactive adapter is injected. New tools must remain behind the versioned registry,
deterministic policy, approvals, and redaction interfaces.
