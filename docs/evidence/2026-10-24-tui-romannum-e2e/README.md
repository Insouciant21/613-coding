# TUI interactive E2E (romannum) — 2026-10-24

Second interactive validation, this time through the real Textual TUI driven
by tmux (220x50 pane), after switching the active `ai2` provider model to
`gpt-6.1-sol` (alias `sol`; the previous `gpt-5.6-terra` remains under the
`legacy` alias).

## Setup

- Target repository: `/tmp/tui-demo` (fresh `git init`), seeded by the
  operator with an in-repo `.venv` (pytest), `harness.toml` declaring a
  **relative** validation argv `[".venv/bin/python", "-m", "pytest", "-q"]`,
  and 5 pre-written acceptance tests for a Roman-numeral converter
  (baseline RED: collection error, module missing).
- TUI launched with `uv run 613-coding --repo /tmp/tui-demo` inside tmux;
  header confirmed `model=gpt-6.1-sol | mode=balanced | provider=ai2`.

## Run result

- Single conversational turn typed into the TUI composer and submitted with
  Enter. Tool progress rendered inline (`set_task_budget`, `list_files`,
  `read_file` with truncation hint, `apply_patch`, `git_diff`,
  `run_validation` — 5 passed on the first validation).
- Run completed: 8 turns / 8 model calls / 128.9 s wall time. Session id
  `42422bf6`. Zero policy denials — the relative validation argv removed the
  `hard.repository_escape` friction observed in the weather-calendar run
  (4 denials there, 0 here).
- Independent verification outside the harness: 5/5 acceptance tests;
  `python -m romannum 2026` → `MMXXVI`, `3999` → `MMMCMXCIX`, `abc` →
  stderr error and exit 2. Target repo commits `a6ac919` (seed) and
  `7315757` (agent implementation).
- Usage from persisted iteration metadata: 9 calls, 58,894 input tokens,
  15,724 cached (26.7%), 1,679 output tokens.

## New defect found: TUI submit soft-lock after a completed run

After the run completed (summary rendered, status Idle), the Enter key
stopped submitting: typing still worked, `Ctrl+J` (newline, direct
`composer.insert`) still worked, keypad Enter inserted newlines, but
`Enter` neither submitted nor reached the TextArea default binding, and the
slash-command palette's "Enter run" also no-op'd — first `/cost`, then
`/status` could not be executed. The app-level Enter priority binding is
firing and `action_submit_task` is silently returning, which points at a
stuck truthy `_executing` guard (the final summary/Idle were rendered via
the separate progress channel, consistent with `_submit_message` never
finishing its `finally`). `Ctrl+Q` exit remained healthy. Reproduced twice
in-session; needs a focused failing TUI test against a real controller
lifecycle before a fix.

## Artifacts

- `tui-final-screen.txt` — final pane capture showing the completed run and
  the unsubmitted `/cost` input.
- `summary.json` — machine-readable summary.
- `romannum-project.zip` — final target project (no `.git`/`.613-coding`).
