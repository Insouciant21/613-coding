# 613 Coding TUI And Distribution Design

**Status:** Approved during brainstorming on 2026-08-09.

## Purpose

613 Coding becomes a local terminal coding agent with a Claude Code-like interaction model. The
browser console and all HTTP serving surfaces are removed. Docker remains required for isolated
worker execution, but the project Dockerfile becomes a reproducible release builder rather than a
deployable web service.

## Command Experience

The root executable opens the TUI in the current repository:

```bash
613-coding
613-coding "repair the failing tests"
613-coding --repo /path/to/repository
613-coding --resume latest
```

`credentials`, `config`, `runs`, and `demo` remain stable, scriptable subcommands with JSON output
where currently supported. A reserved subcommand name is interpreted as a subcommand; `--` allows
a task that begins with a reserved word.

The first TUI release includes streaming assistant text, a scrollable conversation, multiline
input, tool status and results, patch diffs, validation feedback, budgets, explicit approvals,
cooperative interruption, and persisted session recovery. Slash commands include `/help`,
`/model`, `/permissions`, `/resume`, `/runs`, `/clear`, and `/quit`.

## Presentation Architecture

Textual is the TUI framework. The TUI is an adapter over application services and contains no
policy, tool, validation, or completion rules. Its principal widgets are a conversation log, an
input composer, an active-operation area, an approval/diff view, and a compact status footer.

The application adds an `InteractiveSession` persisted in SQLite. A session belongs to a project
and groups multiple auditable Runs. Each follow-up user message starts a new Run linked to the
session and receives bounded summaries of prior session events. Completed Runs stay terminal;
paused or approval-waiting Runs can resume. LanceDB remains a rebuildable retrieval index and is
not used as session authority.

The provider port gains streaming response events. The agent loop assembles and validates the
final response exactly as before while an injected `ProgressSink` publishes ephemeral token,
tool, validation, and status updates. Final responses and audit-relevant events are persisted;
individual token fragments are not. The loop runs away from the Textual UI thread.

Esc requests provider cancellation and persists the active Run as `PAUSED`. A second explicit
exit action closes the application. Provider failures, rate limits, invalid streamed responses,
expired approvals, and keyring failures produce actionable, redacted errors and leave resumable
state where safe.

## Web Removal

Remove the main project's FastAPI routes, WebUI templates and assets, API/Web tests, the `web`
command, FastAPI and Uvicorn dependencies, the web entrypoint and health check, and `render.yaml`.
Current documentation stops recommending Render, SSH deployment, ports, reverse proxies, public
URLs, or a long-running product container. Cube Solver is a separate local browser product and is
not affected by this removal.

## Release Artifacts

The first binary target is Linux x86_64. PyInstaller creates a single-file executable that does
not require host Python. The build configuration explicitly collects Textual, LanceDB/PyArrow,
keyring backends, schema resources, and required package metadata.

The Dockerfile is a pinned multi-stage builder. Its `artifacts` target exports:

- `613-coding-linux-x86_64`
- `613_coding-<version>-py3-none-any.whl`
- `613_coding-<version>.tar.gz`
- `SHA256SUMS`

The canonical local build is:

```bash
docker build --target artifacts --output type=local,dest=dist .
```

There is no product runtime stage. The executable may still require a host Docker Engine when the
user chooses container-isolated worker execution. Credentials remain in the host OS keyring and
are never copied into build layers, artifacts, or worker containers.

## CI/CD And Verification

GitHub Actions and GitLab CI run the offline unit suite, deterministic demos, Ruff, mypy, and lock
checks before invoking the same Docker `artifacts` target. Both upload the binary, wheel, sdist,
and checksums. Tag pipelines attach the same verified files to a release.

CI executes the binary in a minimal Linux environment without Python and tests root help,
configuration inspection, an offline deterministic demo, SQLite/LanceDB initialization, and a
graceful keyring-status path. It installs the wheel separately and verifies the same CLI contract.

Textual Pilot tests cover streaming updates, long output, narrow terminals, keyboard controls,
approval decisions, diffs, pause/resume, and session restoration. Pseudo-terminal smoke tests
cover real root-command dispatch. Repository scans must prove that current product code,
dependencies, tests, manifests, and current guidance contain no HTTP/Web deployment surface.
