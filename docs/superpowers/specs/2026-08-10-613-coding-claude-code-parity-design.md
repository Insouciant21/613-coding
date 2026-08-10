# 613 Coding Claude-Code-Like TUI And CLI Parity Design

**Status:** Approved during brainstorming on 2026-08-10.

## Purpose

613 Coding is a local coding-agent harness. Its terminal experience must support the same
user-visible coding workflow as Claude Code: a user gives a natural-language prompt, the agent
inspects the repository, proposes and applies scoped changes, runs validation, uses deterministic
feedback to repair failures, and remains available for follow-up prompts in the same session.

The TUI and CLI are two adapters over one application service. Neither adapter may implement
policy, tool dispatch, validation, completion, context assembly, or state transitions itself. This
spec extends the interaction portion of
`docs/superpowers/specs/2026-08-09-613-coding-tui-distribution-design.md`; it does not reopen the
WebUI removal, package naming, sandbox, or artifact decisions already approved there.

The command and workflow vocabulary is informed by Anthropic's public CLI reference:
<https://docs.anthropic.com/en/docs/claude-code/cli-usage>. Compatibility means equivalent local
coding-agent behavior and stable contracts, not a copy of Anthropic's implementation, account
system, telemetry, or visual styling.

## Success definition

The work is successful when all of the following can be demonstrated offline with fake providers
and temporary Git repositories:

1. `613-coding` opens a usable interactive coding TUI, accepts multiple follow-up prompts, and
   shows assistant text, tool activity, diffs, validation, approvals, errors, and resource usage.
2. `613-coding "prompt"` starts the same application workflow with an initial prompt and then
   enters the TUI for follow-up interaction.
3. `613-coding -p "prompt"` (and stdin input) completes the same workflow without a TUI and
   produces a documented text, JSON, or JSON-lines event contract.
4. `--continue` and `--resume SESSION` rebuild the same persisted transcript and can continue a
   paused or approval-waiting run without creating hidden state.
5. Permission modes and exact action approvals are enforced by the existing policy and approval
   boundaries. A prompt, CLI option, memory entry, or model response cannot bypass hard safety
   rules.
6. Existing management commands (`credentials`, `config`, `run`, `runs`, and `demo`) continue to
   work, while their lifecycle operations use the same session/run services where applicable.

## Scope and compatibility boundary

### Included in this parity slice

- A persistent interactive session with multiple user turns and resumable runs.
- TUI prompt editing, history, interruption, pause/resume, session switching, slash commands,
  progress rendering, approval rendering, diff rendering, and diagnostics.
- Interactive and print-oriented CLI invocation, stdin input, continuation, resume, model and
  permission selection, context/system-prompt options, tool allow/deny options, resource budgets,
  verbosity, and stable output formats.
- A versioned redacted event envelope shared by TUI progress and `stream-json` output.
- Deterministic context accounting and an explicit compaction operation that preserves a bounded
  authoritative transcript summary.
- Tests for all contracts using injected fake LLMs, fake tools, temporary state, and Textual Pilot.

### Explicitly not cloned

- Anthropic account login, billing, telemetry, hosted services, visual theme, or proprietary
  prompt/tool internals.
- A `--dangerously-skip-permissions` equivalent. `autonomous` remains subject to hard rules.
- A WebUI, HTTP service, public URL, remote deployment, or product runtime container.
- MCP transport in the first implementation slice. The tool registry remains an injectable
  extension point; an MCP adapter may be specified separately after the local contract is green.
- High-level agent runners such as LangChain `AgentExecutor`, AutoGen, CrewAI, LlamaIndex agents,
  or a coding-agent SDK runner. The owned `AgentLoop` remains the only loop.

## User-facing command contract

The root command is parsed separately from management subcommands. A reserved first word is a
management command; `--` forces the remainder to be interpreted as a prompt. Prompt text is never
passed to a shell.

```text
613-coding
613-coding "repair the failing tests"
613-coding --repo /path/to/repository "add a cache"
613-coding --continue "now run the full suite"
613-coding --resume latest "inspect the remaining failure"
613-coding -p "summarize the repository"
cat request.txt | 613-coding -p --input-format text
cat events.jsonl | 613-coding -p --input-format stream-json
```

The root parser supports these options. Long spellings are canonical; the camel-case spellings
are accepted as compatibility aliases where Claude Code users expect them.

| Option | Contract |
| --- | --- |
| `--repo PATH` | Canonical repository root; must resolve to a directory. |
| `--add-dir PATH` | Additional explicitly allowed directory, repeated; path policy and symlink checks still apply. |
| `-p`, `--print` | Run without the TUI and emit the selected output format. |
| `--continue` | Select the most recently updated session in the current repository. |
| `--resume ID\|latest` | Select a specific or latest persisted session. |
| `--output-format text\|json\|stream-json` | Select a versioned output serializer. |
| `--input-format text\|stream-json` | Select prompt input decoding; default is `text`. |
| `--model NAME` | Override the configured model for this invocation. |
| `--permission-mode strict\|balanced\|autonomous` | Select the existing policy mode. |
| `--allowed-tools NAME...` / `--allowedTools` | Add validated tool names to the invocation allowlist. |
| `--disallowed-tools NAME...` / `--disallowedTools` | Add validated tool names to the invocation denylist. |
| `--max-turns N` | Bound agent turns for this invocation. |
| `--max-model-calls N` | Bound provider calls independently of turns. |
| `--max-wall-time SECONDS` | Bound total execution time. |
| `--max-cost VALUE` | Bound provider cost when reported by the provider. |
| `--system-prompt TEXT` | Replace the configured system prompt for this invocation. |
| `--append-system-prompt TEXT` | Append text after the configured system prompt. |
| `--verbose` | Include diagnostic lifecycle records in human output and event streams. |

`--json` remains an alias for `--output-format json` on existing management commands. Unknown
options, invalid enum values, malformed UUIDs, unsafe paths, invalid tool names, and contradictory
input options fail before a run is created.

### Output formats and exit codes

Every non-interactive output has `schema_version: 1` and redacts secrets before serialization.

- `text` prints assistant final text, followed by a compact status/error line. Tool and validation
  details are included when `--verbose` is set.
- `json` prints one `RunEnvelope` after execution. It includes session/run IDs, final status, stop
  reason, assistant text, changed files, validation evidence, approvals, feedback blockers, and
  resource usage. When `--input-format stream-json` supplies multiple user messages, the one JSON
  document is a `SessionEnvelope` with `schema_version`, `session_id`, and ordered `runs` entries,
  each using the same `RunEnvelope` shape.
- `stream-json` prints one JSON object per line using the shared `SessionEvent` envelope. Events
  have `event_id`, monotonically increasing `sequence`, `session_id`, `run_id`, `type`, UTC
  `timestamp`, and a redacted `data` object. The final event is always `run.completed` or
  `run.failed`.

The input `stream-json` format accepts one object per line with `schema_version: 1`,
`type: "user.message"`, and a nonblank `text`; unknown event types are rejected. Input lines are
processed in order and create follow-up runs in the selected session.

Exit codes are stable: `0` for a completed run, `1` for application/tool/validation failure,
`2` for invalid CLI input, `3` for policy denial or rejected approval, `4` for an unavailable
provider/credential, and `5` for a budget or timeout stop. A paused or approval-waiting run uses
the non-success status appropriate to its stop reason and remains resumable.

## TUI contract

Textual remains a presentation adapter. The screen contains:

- a scrollable transcript with user, assistant, tool, validation, feedback, and error entries;
- a composer with multiline editing, draft preservation, history navigation, and submit state;
- an active-operation panel with current run state, tool call, elapsed time, and budget usage;
- an approval/diff panel showing the exact action fingerprint, paths, reason, and allow/reject keys;
- a status footer showing repository, session, model, permission mode, and provider state.

The TUI accepts these keys without embedding business rules:

| Key | Result |
| --- | --- |
| Enter | Submit the current prompt when no blocking action is active. |
| Ctrl-J | Insert a newline. |
| Up/Down | Navigate prior user prompts and restore an editable draft. |
| Esc | Request cooperative pause; repeated Esc is idempotent. |
| Ctrl-C | First request pause; a second explicit quit action exits after safe cleanup. |
| Ctrl-Q | Exit, persisting resumable state when possible. |
| A/R | Approve/reject the currently displayed exact approval. |

Slash commands are registered in one command catalog used by help, parsing, completion, and tests:

| Command | Behavior |
| --- | --- |
| `/help [COMMAND]` | Show the catalog and command-specific usage. |
| `/clear` | Start a fresh session view without deleting persisted sessions. |
| `/compact` | Ask the application context service to compact prior transcript context. |
| `/context` | Show included/omitted context sources and approximate token budget. |
| `/cost` | Show model calls, turns, wall time, and provider-reported cost. |
| `/doctor` | Run redacted local diagnostics for repository, config, keyring, provider, and Docker availability. |
| `/model [NAME]` | Display or change the current invocation model. |
| `/permissions [MODE\|list\|allow\|deny\|clear]` | Display mode/rules or request a validated rule change. |
| `/resume [ID\|latest]` | Restore a persisted session and continue resumable work. |
| `/runs` | List recent runs in the current project/session. |
| `/status` | Show active run, pending approval, validation, and budget state. |
| `/quit` | Pause safely if needed and exit. |

Command parsing is strict `shlex` parsing with validated arguments. A slash command never becomes a
model prompt unless the user escapes it with `//` or uses `--` in the CLI.

## Shared application architecture

### Conversation service

Extend `InteractiveSessionService` into a conversation facade with these injectable operations:

```python
class ConversationService(Protocol):
    def create_session(self, request: SessionRequest) -> InteractiveSession: ...
    def submit(self, request: PromptRequest) -> Run: ...
    def execute(self, run_id: UUID, sink: ProgressSink, cancellation: CancellationToken) -> RunSummary: ...
    def snapshot(self, session_id: UUID) -> InteractiveSnapshot: ...
    def continue_latest(self, project_id: UUID, message: str | None = None) -> Run: ...
    def compact(self, session_id: UUID) -> ContextSummary: ...
    def diagnostics(self, project_id: UUID) -> DiagnosticReport: ...
```

`PromptRequest` carries the repository/project, session selector, text, model override,
permission mode, allow/deny tool sets, additional directories, system-prompt additions, and
budget overrides. The service validates and normalizes it before creating a Run. Existing
`InteractiveSessionService` methods remain as compatibility wrappers during migration.

### Event and sink boundary

Introduce a versioned `SessionEvent` value and an injected `EventSink`:

```python
class EventSink(Protocol):
    def publish(self, event: SessionEvent) -> None: ...
```

The loop publishes ephemeral text/tool/validation progress through the same event adapter used by
the TUI queue and CLI stream serializer. SQLite persists authoritative user messages, final model
responses, approvals, iteration records, stop reasons, and redacted lifecycle events. Token deltas
remain ephemeral unless a caller explicitly chooses `stream-json` output.

Tool events use a unique `tool_call_id`, not a tool name, so concurrent or repeated calls render and
serialize independently. The existing policy, schema validation, feedback classifier, validator,
budget service, and `AgentLoop` remain authoritative.

### Context and compaction

Add a `ContextService` port that reports included sources, omitted sources, estimated token count,
and a stable summary revision. It may use the configured provider for compaction, but compaction is
an explicit application action and its result is persisted as a redacted session summary. A failed
compaction never deletes the original transcript. Normal context assembly continues to use SQLite
as authority and LanceDB only as a rebuildable index.

### Permissions

Add an invocation-scoped `PermissionRules` value and a SQLite-backed rule store. The effective
decision order stays:

1. hard safety rules;
2. validated repository policy;
3. invocation permission mode;
4. exact one-time approval for the action.

Allowed/denied tool names are filters, not policy bypasses. Rules are matched against validated
tool names and normalized paths. Absolute paths, `..`, symlink escapes, mount tricks, shell
injection, and secret-bearing arguments remain denied or approval-gated by the existing policy.

## CLI/TUI adapter responsibilities

The CLI adapter owns argument decoding, input streams, output serialization, terminal detection,
and exit-code mapping. It calls `ConversationService`; it does not construct tools, classify
feedback, or mutate SQLite directly.

The TUI adapter owns Textual widgets, focus, keyboard bindings, rendering, and command dispatch
through the command catalog. It calls the same service and receives queued `SessionEvent` values;
it does not make approval, completion, or retry decisions.

Management commands remain scriptable. Lifecycle commands gain optional `--output-format` support
by delegating to the same serializers, while their existing `--json` behavior remains stable.

## Testing and verification requirements

All tests run without network access or a real LLM.

### Application tests

- Multiple prompts in one session create ordered linked runs and reconstruct the transcript.
- `continue` selects the latest session; `resume` selects an explicit UUID; paused and
  approval-waiting runs resume without duplicate execution.
- Context accounting and compaction preserve the original transcript on failure and record a
  stable summary revision on success.
- Allow/deny rules, permission modes, exact approvals, unsafe paths, and hard-rule precedence are
  enforced regardless of model output.
- Tool progress is keyed by call ID; repeated tool names do not overwrite one another.
- Event sequence numbers are monotonic and final event/stop reason mappings are deterministic.

### CLI tests

- Root dispatch distinguishes TUI, prompt, print, stdin, `--`, and management commands.
- Every option in the command table validates success and failure cases.
- Text, JSON, and stream-JSON output are parseable, redacted, versioned, and stable.
- Input stream-JSON rejects malformed/unknown records and preserves ordering.
- Exit codes cover success, invalid input, policy denial, provider failure, validation failure,
  timeout, and budget exhaustion.
- `--continue`, `--resume`, `--model`, permission, tool filter, system-prompt, and budget options
  reach the injected `PromptRequest` exactly once.

### TUI tests

Textual Pilot tests cover multiline editing, history/drafts, slash command completion/help,
streaming reconciliation, repeated tool names, approval/diff actions, pause/interrupt, resume,
narrow terminals, long output, session switching, `/compact`, `/context`, `/doctor`, and clean
exit. A pseudo-terminal smoke test proves the installed root command reaches the same service.

### Static and delivery gates

Each implementation slice must run focused RED/GREEN tests, `uv run ruff check .`, `uv run mypy src`,
`uv lock --check`, `git diff --check`, and the relevant offline suite. `PLAN.md`, `AGENT_LOG.md`,
`SPEC_PROCESS.md`, and `DELIVERY_STATUS.md` must contain the actual command output and commit hash
before the slice is declared complete.

## Migration and rollout

1. Add the shared request/event/output contracts while preserving current TUI and management CLI
   behavior.
2. Move root prompt/print parsing and serializers onto the shared conversation service.
3. Expand the TUI command catalog, history, diagnostics, and context controls.
4. Add permission-rule persistence, tool-call IDs, and compaction with migration tests.
5. Run the full offline suite and pseudo-terminal/TUI checks, then update the README with examples,
   supported platforms, permission semantics, output schemas, and known MCP boundary.

Existing `.613-coding/state.sqlite` files must migrate idempotently. Existing sessions, runs,
approvals, events, and memory text remain readable. No migration may log keys, full environment
dumps, unredacted command output, or prompt secrets.

## Risks and mitigations

- **Scope growth:** deliver the shared contracts first and keep MCP/remote integration separate.
- **TUI blocking:** all service calls remain off the Textual thread and use cooperative
  cancellation; a hung provider is bounded by the existing wall-time and cancellation policy.
- **Output drift:** serializers consume one versioned event model and have golden contract tests.
- **Permission confusion:** show the effective mode and exact action in the TUI/CLI, and keep hard
  rules outside user-configurable rule stores.
- **Context loss:** compaction is explicit, append-only, revisioned, and reversible by retaining
  the authoritative transcript.
- **Secret leakage:** redact at event creation/persistence boundaries and test redaction in every
  output format.
