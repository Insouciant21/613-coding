# Weather Calendar interactive E2E — 2026-10-24

Operator-driven interactive validation of the installed `613-coding` CLI
(package + user provider `ai2` / `gpt-5.6-terra`, keyring credential) on a fresh
temporary Git repository implementing a small "weather calendar" project.

## Setup

- Target repository: `/tmp/weather-calendar` (fresh `git init`), containing only
  the operator-authored seeds: `harness.toml` (declared validation argv
  `[<harness-venv>/python, -m, pytest, -q]`, balanced mode), `data/weather.json`
  (8 April 2026 records), and `tests/test_weathercal.py` (8 acceptance tests
  written before the run; the task prompt pinned the rendering contract).
- Turn 1: `613-coding "<implementation task>" --repo /tmp/weather-calendar -p
  --max-model-calls 16 --max-wall-time 600` → `status=failed
  stop_reason=budget_exhausted` (log: turn1.log).
- Operator amendment: one acceptance assertion was over-constrained (it
  demanded an unpadded first calendar row while `·` padding is equally valid);
  amended to a padding-agnostic column check and committed as `2dba348`.
- Turn 2: `613-coding "<re-validate and finish>" --repo /tmp/weather-calendar
  -p --continue --max-model-calls 6 --max-wall-time 300` → `status=completed
  stop_reason=success`, CLI exit code 0 (log: turn2.log).

## Results

- Turn 1 exhausted its 16-call budget stuck on the ambiguous acceptance
  assertion: the agent produced a correct implementation in its first patch,
  7/8 tests passed, and it then looped on formatting variants for the one
  over-constrained test without re-running validation in most turns
  (21 iterations, only 2 validation runs, 4 hard `policy.repository_escape`
  denials after it tried to execute the absolute-path validation argv via
  `run_command`, and 2 patch/tool errors).
- Turn 2 (session continuation via `--continue`) correctly consumed the
  operator amendment, re-ran the declared validation once (8 passed), left the
  renderer untouched, and finished in 3 iterations.
- Independent verification outside the harness: 8/8 acceptance tests pass; CLI
  output for 2026-04 renders the Monday-first calendar with correct weekday
  alignment (checked cell by cell), per-condition summary lines, `avg 12.2°C`,
  and exit code 2 with a usage error for an invalid month.
- Provider usage across both runs (persisted iteration metadata): 23 model
  calls, 182,345 input tokens, 63,497 cached input tokens (34.8%),
  12,212 output tokens.

## Findings recorded for follow-up

1. Bare `613-coding providers` and `613-coding credentials status` crash with
   an unhandled `NoArgsIsHelpError` traceback instead of printing help.
2. Declaring an absolute-path validation argv makes the model try to run it
   through `run_command` (blocked 4x by the hard repository-escape rule with
   only a generic "policy denied action" message), burning repair budget;
   guidance toward `run_validation` and a specific denial message would help.
3. The turn-1 repair loop announced validation repeatedly but executed it in
   only 2 of 21 iterations without triggering the no-progress stop; repeated
   identical read/patch turns still consumed the model-call budget.
4. Exit-code behavior of a failed run was initially misread as 0 because the
   operator piped the CLI through `tail`; direct measurement shows the mapped
   codes (completed=0). The mapping code itself is correct.

## Artifacts

- `turn1.log`, `turn2.log` — full CLI transcripts.
- `weathercal-project.zip` — final target project (no `.git`/`.613-coding`).
- `summary.json` — machine-readable run summary from the harness state DB.
