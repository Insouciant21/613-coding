# Dangerous Bypass Permission Mode Design

Date: 2026-08-13
Status: approved design, awaiting written-spec review
Owner: `/root`

## Context

613 Coding currently supports `strict`, `balanced`, and `autonomous`. Even
`autonomous` pauses for undeclared commands, multi-command shell batches, and
sensitive actions that are not explicitly enabled by repository policy. The
user wants a fourth mode analogous to Claude Code's
`--dangerously-skip-permissions`: every action that would normally request an
approval should execute without an approval prompt.

The new request supersedes the earlier parity-design decision that excluded a
dangerous permission-bypass option. It does not supersede the repository's hard
safety invariants. The distinction is explicit: bypass removes `ASK` decisions;
it never converts a deterministic `DENY` decision into `ALLOW`.

## Goals

- Add `bypass` as a first-class, persisted `PermissionMode`.
- Automatically execute valid `run_command` and `run_shell` actions, including
  undeclared commands and ordered multi-command batches.
- Skip all other one-time approval prompts for recognized tools, including
  repository writes, validation, network, dependency-install, and Git-write
  actions.
- Expose the mode consistently through project configuration, root CLI, TUI
  commands, menus, status output, session/run persistence, and documentation.
- Make the dangerous state conspicuous without adding a second confirmation
  that would recreate the approval behavior the mode is intended to remove.
- Preserve deterministic validation, feedback, budgets, audit events, and
  sandbox enforcement.

## Non-goals

- Do not disable schema validation or execute malformed tool calls.
- Do not introduce raw `shell=True` execution; shell tools continue to accept
  validated argv arrays.
- Do not weaken repository-boundary, credential, secret, destructive-command,
  privileged-container, Docker-socket, or worker-sandbox denials.
- Do not let the model select `bypass`; only explicit user configuration or
  invocation options may select it.
- Do not remove the existing permission modes or reinterpret `autonomous`.

## User Interface

The canonical mode value is `bypass`:

```text
--permission-mode bypass
/permissions bypass
/config set mode bypass
```

The root CLI also accepts the explicit convenience flag:

```text
--dangerously-skip-permissions
```

The convenience flag maps to `PermissionMode.BYPASS`. If it is combined with
an explicit non-bypass `--permission-mode`, argument parsing fails with a clear
conflict error. Combining it with `--permission-mode bypass` is accepted.

The TUI permission/config menus include `bypass`. While active, the status
footer and configuration/status output display `DANGEROUS: BYPASS` rather than
presenting it as an ordinary mode. Explicitly choosing the command, menu item,
configuration value, or CLI flag is the user's acknowledgement; no approval
dialog is shown simply for entering the mode.

Project configuration may persist `mode = "bypass"`, matching the existing
mode ownership and reload behavior. Existing configurations remain unchanged
and continue to default to `balanced`.

## Policy Semantics

Policy evaluation retains the existing precedence:

1. hard safety rules;
2. validated repository denials and disabled capabilities;
3. explicit tool/path permission deny rules;
4. mode-derived allow or ask behavior;
5. exact one-time approval.

For `bypass`, the final policy layer converts only `ASK` to `ALLOW`. Existing
`ALLOW` and `DENY` decisions are unchanged. Centralizing the conversion after
all deterministic denial checks ensures current and future recognized tool
categories inherit bypass behavior without duplicating a special case in each
category.

The resulting matrix is:

| Action | `bypass` result |
| --- | --- |
| Repository reads | `ALLOW` |
| Repository writes | `ALLOW`, unless writes are disabled or another denial matches |
| Declared or undeclared argv command | `ALLOW`, unless a hard denial matches |
| Ordered shell command batch | `ALLOW`, unless any nested command is denied |
| Validation | `ALLOW` |
| Network, dependency installation, Git writes | `ALLOW`, unless explicitly denied by a hard/config/rule boundary |
| Unknown tool or invalid schema | `DENY` / invalid action |
| Repository escape, credential path, secret material, destructive or privileged command | `DENY` |

`allow_network`, `allow_dependency_install`, and `allow_git_writes` currently
control whether a sensitive action is automatically allowed or sent to
approval. In bypass mode their false value does not create an approval prompt;
the action becomes allowed unless a separate explicit denial or sandbox rule
blocks it. `allow_writes = false` remains a deterministic denial and is not
bypassed.

## Shell And Sandbox Boundary

`run_command` and `run_shell` retain their versioned schemas. Every command is
an argv array, receives the configured working directory, timeout, output cap,
environment allowlist, and resource limits, and is recorded through the normal
tool/event path. A multi-command batch is checked recursively so one hard-denied
nested command denies the batch before execution.

Bypass does not alter `SandboxPolicy`. Worker requirements such as a pinned
image, non-root user, dropped capabilities, read-only root filesystem, bounded
resources, credential-free environment, and configured network policy remain
authoritative. Thus bypass is dangerous because it removes human review, not
because it escapes the product sandbox.

## Run, Approval, And Resume Behavior

The selected mode is stored on each `Run` using the existing SQLite field. A
resumed run retains the mode with which it was created. New prompts use the
current invocation or configured default according to existing precedence.

In bypass mode policy-eligible actions never create `ApprovalRequest` records
or transition the run to `WAITING_APPROVAL`. Tool execution, validation,
feedback classification, patch-repair barriers, no-progress detection, and
budget exhaustion continue unchanged. An already-paused approval from a run
created in another mode is not silently consumed by switching the default to
bypass; it must still be approved, rejected, cancelled, or replaced by a new
run.

## Errors And Auditability

- Conflicting CLI permission options fail during argument parsing.
- Invalid `bypass` spellings fail through the strict enum/config parser.
- Deterministic denials retain their existing rule IDs and feedback.
- Allowed bypass actions record a `mode.bypass.*` policy rule ID so event logs
  show that approval was skipped deliberately.
- TUI, text, JSON, and stream-JSON summaries retain the effective mode.
- Secrets remain redacted before persistence.

## Test Strategy

Implementation follows TDD. Focused RED tests will first prove the missing
behavior, followed by the minimum implementation and relevant regression suite.
Coverage must include:

- enum, configuration, SQLite, and run/session round trips for `bypass`;
- automatic undeclared `run_command` execution;
- automatic single and multi-command `run_shell` execution;
- automatic writes, validation, network, dependency installation, and Git
  writes without approval records;
- unchanged hard denials for repository escape, credential/secret access,
  destructive commands, privileged containers, and invalid argv;
- unchanged explicit `denied_tools`, path/tool deny rules, and
  `allow_writes = false` behavior;
- CLI `--permission-mode bypass`, the convenience flag, and conflict handling;
- TUI command parsing, menu selection, prominent footer/status warning, and
  persisted configuration reload;
- resume behavior and the rule that existing pending approvals are not
  retroactively bypassed;
- deterministic demo/documentation updates for the fourth mode.

Verification will run focused policy/CLI/TUI/config/storage tests first, then
the maintained offline suite, Ruff, mypy, and `git diff --check`. Any unrelated
environmental timeout or nested-project collection failure will be reported
separately rather than represented as passing.

## Documentation And Compatibility

`SPEC.md`, `README.md`, CLI/TUI help, mechanism-demo expectations, and delivery
records will describe four modes and the warning boundary. The old three values
remain valid and keep their behavior. Adding the enum value requires no SQLite
schema migration because the mode is stored as text, but parsing and display
tests must prove old rows and new `bypass` rows both load correctly.

The security documentation must recommend using bypass only inside the
configured short-lived worker/container boundary and must state that removing
approval prompts increases the impact of model mistakes and prompt injection.

## Acceptance Criteria

The feature is accepted when an explicitly selected bypass run executes a
valid, undeclared shell command without entering `WAITING_APPROVAL`, while the
same action in `balanced` still asks and a hard-denied command in `bypass`
remains denied. All four selection surfaces report the effective mode, resume
preserves it, no approval record is created for bypassed actions, and focused
offline verification plus static checks pass.
