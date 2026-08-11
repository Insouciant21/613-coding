# DELIVERY_STATUS.md

Last updated: 2026-08-12 02:16:57 (Asia/Shanghai)
Responsible actor: `/root` for OpenAI tool support, local shell execution, patch-conflict recovery, and local verification. No real provider request, deployment, or pipeline operation was performed.

This is an index of delivery evidence. Source records remain in `AGENT_LOG.md`, `PLAN.md`, `SPEC_PROCESS.md`, CI/CD logs, test output, and commits.

| Requirement | Status | Evidence | Next verification |
| --- | --- | --- | --- |
| Official OpenAI SDK chat adapter | implemented, review-repaired, offline verified, and integrated into `main` | design `b4b5a94`; plan `d3e34f6`; implementation `f7f2301`; repair `0fcd2af`; integrated tip `8e708e2`; `PLAN.md` OPENAI-SDK-LLM evidence | retain the offline regression gate; run a real provider smoke only with user-controlled credentials |
| Official OpenAI SDK Responses adapter | implemented in current worktree; offline verified | `docs/superpowers/specs/2026-08-11-responses-api-llm-design.md`; `docs/superpowers/plans/2026-08-11-responses-api-llm.md`; `PLAN.md` Responses evidence; 495-test offline suite; target verifier 46 web/5 API | run an optional user-controlled `/v1/responses` smoke; keep Chat Completions as the default for compatible endpoints |
| Claude-Code-like TUI/CLI parity | Tasks 1-7 implemented and offline verified in `feature/claude-code-parity`; handoff pending user integration choice | design `3a07f09`; plan; implementation `fd8871e`; evidence below and in `PLAN.md`/`AGENT_LOG.md` | merge or retain the isolated branch; configure a provider for a real coding run |
| Safe repository mutations | design and implementation plan committed; execution pending | design `e7f7ece`; plan `9ee205d` | select execution workflow and begin MUTATION-01 |
| Claude Code-like TUI | implemented and verified on main, including pause/restart/approval recovery | design `e7f7ece`; merge `4528bda`; Pilot and full-suite evidence in TUI-09 | retain regression coverage and configure provider credentials locally |
| Binary/wheel/sdist artifact builder | Docker-exported and runtime-smoked on main; CI/release configuration present | `Dockerfile`, `packaging/`, `scripts/build_artifacts.sh`, `scripts/smoke_artifacts.sh`; TUI-08/TUI-09 evidence | push/tag when an operator wants remote CI artifacts or a GitHub release |
| Main Web/HTTP removal | complete and verified on main | import/dependency/manifest absence contracts; merge `4528bda` | retain removal regression checks |
| Cube recovery through 613 Coding | design and recovery plan written; blocked on the two harness stages | `docs/superpowers/plans/2026-08-09-cube-solver-recovery.md`; Cube Task 2 `8c052ee` | repair Task 3 through new TUI after harness verification |
| Approved design | complete | `docs/superpowers/specs/2026-08-07-613-coding-design.md`; commits `6ad0eec`, `c4fd219`, `ba03b70` | none |
| `AGENTS.md` workflow rules | complete | `AGENTS.md`; commit `ba03b70` | keep updated per task |
| `SPEC.md` | approved with bootstrap revision | `SPEC.md`; commits `a2909c7`, `fc7bf53`; cold-start report incorporated | begin CORE-01 |
| `SPEC_PROCESS.md` | complete | `SPEC_PROCESS.md`; `/tmp/613-cold-start.T1D2Hh/cold-start-report.md`; revision `fc7bf53` | none |
| `PLAN.md` | approved with bootstrap revision | `PLAN.md`, `docs/superpowers/plans/`; commits `a2909c7`, `fc7bf53`; user selected Subagent-Driven on 2026-08-08 | begin CORE-01 |
| `AGENT_LOG.md` | active | `AGENT_LOG.md` | append every significant task |
| `DELIVERY_STATUS.md` | active | this file | update after every delivery change |
| Source implementation | Core complete after final-review repair | task evidence in `PLAN.md` and `AGENT_LOG.md`; final-review implementation/evidence commit `9af4f03`; final-fix report under `.superpowers/sdd/2026-08-08-613-coding-core/` | begin sandbox subsystem |
| Mock-LLM mechanism tests | persisted core demo complete and reviewed | scripted adapter tests plus offline feedback/repair/persistence demo in `tests/demo`; commits `2dd32f9` through `f9394d7` | retain as regression gate |
| Container sandbox | complete | SANDBOX-01 `9df471d`; SANDBOX-02 `aa3600a`; SANDBOX-03 `3ec6ac1`; SANDBOX-04 `439540f`; SANDBOX-05 `fb1c222`; reports under `.superpowers/sdd/2026-08-08-613-coding-sandbox/` | retain regression gate |
| Multi-agent orchestration | complete | MULTI-01 `9744339`; MULTI-02 `5910d7b`; MULTI-03 `43f51fc`; MULTI-04 `11eaef8`; MULTI-05 `376fd41`; reports under `.superpowers/sdd/2026-08-08-613-coding-multi-agent/` | retain regression gate |
| README and distribution | local TUI and artifact-only operation documented | `README.md`, `docs/deployment.md`, `Dockerfile`, package metadata, `scripts/smoke_artifacts.sh`; TUI-07/TUI-08 evidence below | retain artifact verification and CI upload gate |
| Strict package rename documentation and artifacts | deployed and verified | `eefee2d`; Task 3 artifacts and Task 4 CI/deployment evidence below | retain as regression gate |
| GitLab CI `unit-test` job | configured; local equivalent and artifact handoff verified | `.gitlab-ci.yml`; Docker export feeds dependent Python/uv `artifact-smoke`; current local pytest, Ruff, mypy, lock, and build gates pass | run the remote pipeline and record its final pass result |
| Provider-backed LLM composition | implemented; offline verified | `LLMConfig`, lazy keyring-backed OpenAI-compatible adapter, composition MockTransport test; current task evidence below | run a provider-backed smoke with user-controlled credentials |
| Codex/Claude-inspired prompt and loop controls | implemented; offline verified | `src/coding613/application/context.py`, `src/coding613/application/loop.py`, context/loop regressions; `PLAN.md` and `AGENT_LOG.md` 2026-08-11 21:13 evidence | retain offline gate; optionally run a user-controlled provider smoke |
| Codex-aligned provider retry window | implemented; offline verified | `_MAX_PROVIDER_RETRIES = 5` (six total requests maximum), non-retryable `ProviderRequestError` for client 4xx, loop/adapter regressions; `PLAN.md` and `AGENT_LOG.md` 2026-08-11 21:32 evidence | restart installed TUI and start a fresh user-controlled provider run |
| User-scoped provider and budget configuration | implemented; offline verified | `UserConfig`, `UserConfigurationService`, `613-coding providers ...`, TUI `/provider`, project `[llm]`/`[budgets]` rejection, migrated `tmp/cube` metadata, 562-test suite at 2026-08-12 00:12 | use `providers key-set/use` and run a fresh user-controlled provider smoke |
| Provider model catalog and Anthropic SDK | implemented; offline verified | `ModelConfig`, `[providers.NAME.models.ALIAS]`, `613-coding providers models ...`, `AnthropicLLM`/`CredentialedAnthropicLLM`, injected composition tests, 568-test suite at 2026-08-12 00:40 | configure an Anthropic key and run an optional user-controlled smoke |
| Selectable TUI configuration/provider/model menus | implemented; offline verified | `ConfigMenu`, `/config`, `/provider`, `/model`, keyboard-routing regression, TUI suite at 2026-08-12 00:40 | retain Pilot coverage and exercise interactively after restarting installed TUI |
| Repository tool composition | implemented; offline verified | local `ToolRegistry`/validator wiring and `read_file` → validation → `finish` test; current task evidence below | run real provider-backed repository smoke |
| Local shell and OpenAI hosted tools | implemented; offline verified | `run_command` argv executor; Responses hosted tool catalog/configuration; provider CLI/TUI opt-in; 601-test gate and current `AGENT_LOG.md` entry | run an optional user-controlled Responses smoke with a provider that implements the selected hosted tools |
| Real-provider worker reliability | unblocked and integrated on `main` | descriptor-relative delete and patch mutation Tasks 1-4; merge `69caa09`; fresh main evidence below | retain regression gate |
| GitHub source publication | complete | `git@github.com:Insouciant21/613-coding.git`; initial source snapshot `f4b9984`; CI repair `341d880`; publication evidence below | keep delivery records synchronized with pushed commits |
| GitHub Actions CI | configured for artifact upload and tag release; not rerun for `4528bda` | `.github/workflows/ci.yml`; exact-main local equivalent passed | push/tag to obtain current remote run and release evidence |
| Historical SSH deployment | prior evidence retained; no longer a deliverable | `edward@int21`; image `613-coding:eefee2d`; prior loopback evidence below | no new deployment or reverse proxy work |
| Deployment manifest | removed | `render.yaml` absent; absence contract passed on `4528bda` | none |
| Public WebUI URL | removed from product scope | approved TUI/distribution design | no action |
| Reflection | reserved for student | `REFLECTION.md` contains an explicit student-authored boundary and no AI-written narrative | student writes the final report |
| Cold-start implementation trial | completed with revisions | report at `/tmp/613-cold-start.T1D2Hh/cold-start-report.md`; revision committed as `fc7bf53` | gate satisfied |

## OPENAI-SDK-LLM Evidence

- TDD RED: the focused SDK boundary initially failed 2 tests before implementation; the old
  credential factory signature and direct HTTP chat boundary were the observed failures.
- Implementation: `f7f2301` adds the bounded `openai` dependency, official SDK Chat Completions
  calls, injected offline fakes, lazy `OpenAI(..., max_retries=0)` construction, stream cleanup,
  and README guidance. The embedding HTTP adapter is intentionally out of scope.
- Final verification at `2026-08-10 12:22:35 Asia/Shanghai`: initial adapter suite 33 passed; after review repair the adapter suite passed 37,
  application/composition/CLI regressions passed 25, and clean feature branch suite 405 passed.
  After integration, merged main passed 408 tests with 127 existing pytest-asyncio deprecation
  warnings; Ruff, mypy, `uv lock --check`, and `git diff --check` passed. No real provider request
  was made.
- Review: independent review found two Important cleanup/secrecy risks; repair `0fcd2af` addressed
  both, and follow-up review found no remaining Critical or Important issues.
- Integration: main fast-forwarded to `8e708e2` after a recoverable stash of tracked user changes;
  five unrelated user paths were restored, while overlapping adapter/test changes were carried
  into the SDK implementation. The stash remains as a user-change backup.

## RESPONSES-API Evidence

- Design/plan: `docs/superpowers/specs/2026-08-11-responses-api-llm-design.md` and
  `docs/superpowers/plans/2026-08-11-responses-api-llm.md`.
- TDD RED: the new adapter test initially failed during collection because the Responses adapter
  module did not exist; the streaming contract then failed on the missing `complete_stream` method.
- GREEN: Responses, credential, composition, and config focused tests passed 60; the full offline
  suite passed 495 tests with 253 existing pytest-asyncio deprecation warnings.
- Boundary: `[llm].api = "responses"` selects `client.responses.create`; flat function schemas,
  output items, streamed deltas, tool-call IDs, finish actions, and input/output/cache/reasoning
  usage are mapped to project values. Calls set `store=false` and never use an SDK agent runner.
- Static gates: Ruff, mypy, `uv lock --check`, and `git diff --check` passed. Independent target
  verification passed 46 Web tests, 5 API tests, lint, typecheck, build, Ruff, and mypy.

## OpenAI tool support evidence (2026-08-12 02:16 Asia/Shanghai)

- Local shell: `run_command` is an injected registry tool with argv schema validation, repository
  cwd confinement, allowlisted environment, `shell=False`, finite timeout, and a 10 MB output cap.
- Responses hosted tools: opt-in `responses_tools` profiles forward `web_search`,
  `web_search_preview`, `file_search`, `code_interpreter`, `image_generation`, remote `mcp`, and
  server-side `tool_search` payloads. Chat Completions and Anthropic safely omit hosted definitions.
- Patch recovery: stale `apply_patch` conflicts retain the stable error type while exposing a
  redacted current-file excerpt and fresh-patch instruction to the next model turn.
- Verification: `uv run pytest tests -q` -> 601 passed (379 warnings); Ruff and mypy passed; CLI
  `providers add/remove --responses-tool web_search` smoke passed without a provider request.

## DELIVERY-01 Evidence

- Verification timestamp: `2026-08-09 05:24:04 Asia/Shanghai`.
- Status: complete; implementation commit `2a53a73` (`feat: add configuration and credential commands`).
- TDD RED: focused collection failed with the expected missing `coding_harness.config` and `coding_harness.cli` modules.
- GREEN: focused config/credential suite passed 7 tests; full suite passed 201 tests.
- Static gates: scoped Ruff and mypy passed; `git diff --check` passed. CLI smoke `config check --repo .` exited 0.
- Boundary: TOML config canonicalizes repository paths, rejects non-argv validation commands and invalid unattended budgets, defaults to balanced mode, and exposes existing policy/budget values without policy logic in the CLI. Credential input is hidden and status/command output is secret-free.
- Detailed evidence: `.superpowers/sdd/2026-08-08-613-coding-delivery/task-1-report.md` and `AGENT_LOG.md`.

## CORE-02 Evidence

- Verification timestamp: `2026-08-08 22:08:51 Asia/Shanghai`.
- Commit: `59bc4f2`.
- Domain tests: 7 passed with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src uv run --no-sync pytest tests/domain -q`.
- Ruff and mypy: passed for `src/coding_harness/domain` and `tests/domain`.
- Scoped review fix: false-positive `monkey` redaction reproduced and fixed; explicit event timestamp enforced.

## CORE-03 Evidence

- Verification timestamp: `2026-08-08 22:17:38 Asia/Shanghai`.
- Status: complete; commit `e8b938f`.
- Tests: 4 focused port tests passed; 11 combined domain/port tests passed.
- Ruff and mypy: passed for domain and ports.

## CORE-04 Evidence

- Verification timestamp: `2026-08-08 22:21:23 Asia/Shanghai`.
- Status: complete; commit `a97e711`.
- Tests: 5 focused SQLite tests and 16 combined core tests passed, including foreign-key rollback and concurrent append checks.
- Persistence: direct raw-secret event payloads are redacted before SQLite insertion.

## CORE-05 Evidence

- Verification timestamp: `2026-08-08 22:25:19 Asia/Shanghai`.
- Status: complete; commit `2dcb00e`.
- Tests: 7 focused LLM-adapter tests and 23 combined core tests passed.
- Provider boundary: only MockTransport used; no real LLM, network request, or credential.

## CORE-06 Evidence

- Verification timestamp: `2026-08-08 22:31:15 Asia/Shanghai`.
- Status: complete; commit `44a4a9a`.
- Tests: 8 focused repository-tool tests and all 32 project tests passed.
- Security boundary: path/symlink escape, size, UTF-8, unknown tool, and invalid JSON Schema arguments are rejected before execution.

## CORE-07 Evidence

- Verification timestamp: `2026-08-08 22:37:12 Asia/Shanghai`.
- Status: complete; commit `8956821`.
- Tests: 17 focused policy/approval tests and all 49 project tests passed.
- Governance: hard denials remain unapprovable; sensitive actions use exact, expiring, single-use approvals.

## CORE-08 Evidence

- Verification timestamp: `2026-08-08 22:44:36 Asia/Shanghai`.
- Status: complete; commit `1e01249`.
- Tests: 19 focused feedback/budget/runner tests and all 68 project tests passed.
- Feedback boundary: objective outputs, exit status, resources, changes, repetition, and freshness determine classification; no LLM classification is used.

## CORE-09 Evidence

- Verification timestamp: `2026-08-08 22:56:36 Asia/Shanghai`.
- Status: complete; commit `86c4633`.
- Tests: 7 focused SQLite/LanceDB/context tests and all 75 project tests passed.
- Memory boundary: SQLite stores authoritative redacted text; LanceDB stores rebuildable IDs, filters, and vectors only; final permission filtering occurs after SQLite reload.

## CORE-10 Evidence

- Verification timestamp: `2026-08-09 01:11:12 Asia/Shanghai`.
- Status: complete after persistence/audit hardening and independent scoped re-review; commits `2dd32f9`, `d705637`, `06b397e`, `f9394d7`.
- Tests: `uv run pytest -q` passed with 110 tests; focused fix gates passed with 66 tests.
- Static gates: Ruff, mypy, `uv lock --check`, and `git diff --check f154bba..f9394d7` passed.
- Mechanism: invalid actions, policy deny/ask/allow, cross-process exact approval resume/reject/expiry, redacted and atomic SQLite session/approval/iteration persistence, persisted budget limits/usage and validation freshness, objective completion blockers, terminal audit records, no progress, cancellation, dependency terminal states, and four budget types remain deterministic and injectable.
- Demo check: direct execution returned `completed/success`, observed objective feedback, blocked the guardrail escape, retrieved memory, corrected `answer.py`, and persisted `runs.state=completed`. Scripted mock LLM only; explicit `total_model_calls=5` is demo configuration, not a product-wide limit; no credentials or network calls.
- Review: scoped re-review from `f154bba` through `f9394d7` marked all findings addressed with no new Critical/Important breakage. Stale concurrent `RunService._persist_status` was recorded as out-of-scope for this fix diff and remains a final-review observation.

## CORE-11 Evidence

- Verification timestamp: `2026-08-09 02:02:37 Asia/Shanghai`.
- Status: complete after independent review and fix round 1; commits `552593e`, `d748a0e`.
- Tests: focused credential suite passed 6 tests; full suite passed 116 tests.
- Static gates: Ruff, mypy, `uv lock --check`, and `git diff --check` passed.
- Security boundary: returned status/references contain no key material; fake-keyring captured-output checks remain secret-free; providers use isolated entries; environment fallback is disabled by default and must be explicitly enabled.
- Follow-up boundary: raw-secret injection into a provider call is intentionally absent and must be designed as a separately governed non-persisting integration.
- Review: the task review found two Important issues; fix round 1 added backend failure tests, mapped double-faults to `CredentialError`, and removed the source type suppression. Scoped re-review marked both addressed with no new Critical/Important breakage.

## Core Final-Review Fix Evidence

- Verification timestamp: `2026-08-09 02:59:19 Asia/Shanghai`.
- Base: `b26833f31336d75166dda3b6e0be6f8b9780d01b`; implementation/evidence commit: `9af4f03`.
- Findings: SQLite connections were not closed by transaction context exit; stale `RunService` status writes could replace a newer terminal row and return a stale summary.
- TDD RED: required focused command produced 6 failed and 42 passed, covering success/exception connection leaks, absent SQLite run CAS, and deterministic `resume`/`cancel` races. Review repair RED produced 2 failed and 33 deselected for terminal entry points returning stale summaries and re-entering the loop.
- GREEN: terminal-entry regression passed 2 tests; required focused command passed 50 tests; full suite passed 126 tests.
- Static gates: full Ruff, mypy across 44 source files, `uv lock --check`, and `git diff --check` passed.
- Boundaries: connection closure is deterministic and preserves commit/rollback; SQLite run persistence uses one full-snapshot CAS statement; lost races and later terminal operations return authoritative state/stop reason; terminal operations do not re-enter mutating loop paths; unknown runs retain `KeyError` behavior.
- Review/report: independent review found one Important terminal-entry gap and no Critical/Minor issues; the finding was addressed through a separate RED/GREEN cycle. Full command output and self-review are recorded in `.superpowers/sdd/2026-08-08-613-coding-core/core-final-review-fix-report.md`.

## SANDBOX-01 Evidence

- Verification timestamp: `2026-08-09 03:33:03 Asia/Shanghai`.
- Status: complete after independent review and fix round 1; commits `024925a`, `5d4e787`, and evidence commit `9df471d`.
- TDD RED: focused collection failed with the sandbox adapter package missing.
- GREEN: focused contracts passed 5 tests; full offline suite passed 131 tests.
- Static gates: Ruff, mypy across 48 source files, `uv lock --check`, and `git diff --check` passed.
- Boundary: strict specs require a pinned SHA-256 image digest, non-root execution, read-only root, no capabilities, default-deny network, finite resource limits, and an environment-name allowlist. The fake runtime records create/execute/export/destroy order and rejects use after destroy.
- Workflow note: the external implementer's nested bwrap test process did not exit; the controller reproduced a clean full-suite run outside the nested sandbox and interrupted the stalled process. The exact evidence is in `.superpowers/sdd/2026-08-08-613-coding-sandbox/task-1-report.md`.
- Review fix: one Important finding showed `float("inf")` was accepted for CPU/time limits. Focused RED was 2 failed and 7 passed; `allow_inf_nan=False` plus parameterized coverage produced 9 focused passes and 135 full-suite passes. Ruff, mypy, lock, and diff checks passed at `2026-08-09 03:48:49 Asia/Shanghai`; scoped re-review marked the finding `ADDRESSED` with no new breakage or out-of-scope observations.

## SANDBOX-02 Evidence

- Verification timestamp: `2026-08-09 04:18:00 Asia/Shanghai`.
- Status: implementation, review repairs, and independent re-review complete through `aa3600a`.
- TDD RED: focused workspace/artifact collection failed with two expected missing-module errors before implementation.
- GREEN: 17 focused workspace/artifact tests, 26 sandbox tests, and the full 152-test suite passed.
- Static gates: full Ruff, mypy across 50 source files, `uv lock --check`, and `git diff --check` passed.
- Boundary: complete working-tree copy retains `.git`, ignored, and untracked files; manager-issued immutable workspaces reject forged and replaced roots; empty write sets deny changes; patches include mode-only changes and are deterministic/redacted; binary data is summarized without bytes; cleanup covers complete owned roots across success and failure paths.
- Detailed source evidence: `.superpowers/sdd/2026-08-08-613-coding-sandbox/task-2-report.md`.
- Review evidence: `.superpowers/sdd/2026-08-08-613-coding-sandbox/task-2-review.md`; repairs `840cc21` and `aa3600a`.

## SANDBOX-03 Evidence

- Verification timestamp: `2026-08-09 04:30:00 Asia/Shanghai`.
- Status: complete through `bf129cd` and `3ec6ac1`; fake-client lifecycle review clean.
- GREEN: 8 focused Docker runtime tests, 34 sandbox tests, and the full 160-test suite passed.
- Static gates: Ruff, mypy across 52 source files, `uv lock --check`, and `git diff --check` passed.
- Boundary: copied workspaces only; pinned image, non-root/read-only/capability-free container, no socket or credential mounts, network disabled, memory/PID/CPU/output/time limits, opaque identity handles, artifact export, and cleanup on lifecycle failures.
- Real smoke: Docker daemon `29.6.2` available, but no approved pinned worker image exists locally; smoke was explicitly skipped without pulling an image.
- Detailed source evidence: `.superpowers/sdd/2026-08-08-613-coding-sandbox/task-3-report.md`.

## SANDBOX-04 Evidence

- Verification timestamp: `2026-08-09 04:42:00 Asia/Shanghai`.
- Status: complete through `439540f`; deterministic hard-boundary policy review clean.
- GREEN: 8 focused security-policy tests and the full 168-test suite passed.
- Static gates: Ruff, mypy across 53 source files, `uv lock --check`, and `git diff --check` passed.
- Boundary: default-deny network, exact allowlist approval, pinned/approved images, credential-free environments, finite resource bounds, and resource-exhausted result mapping cannot be overridden by autonomous mode.
- Detailed source evidence: `.superpowers/sdd/2026-08-08-613-coding-sandbox/task-4-report.md`.

## SANDBOX-05 Evidence

- Verification timestamp: `2026-08-09 04:50:00 Asia/Shanghai`.
- Status: complete through `fb1c222`; offline demo and final sandbox verification clean.
- Demo: all seven summary boundaries returned `true`, including per-worker isolation, dangerous command/socket denial, default-deny network, resource timeout mapping, artifact export, and cleanup.
- Verification: demo test passed 1; full suite passed 169; Ruff, mypy across 54 source files, `uv lock --check`, and `git diff --check` passed.
- Real Docker smoke was explicitly skipped because no approved pinned worker image was local.
- Detailed source evidence: `.superpowers/sdd/2026-08-08-613-coding-sandbox/task-5-report.md`.

## MULTI-01/02 Evidence

- `MULTI-01`: complete at `9744339`; 7 focused and 176 full tests passed; graph/worker contracts are recorded in the multi-agent task report.
- `MULTI-02`: complete at `5910d7b`; 5 focused and 181 full tests passed; role policies and worker runtime enforce scoped writes and cleanup.
- Detailed evidence: `.superpowers/sdd/2026-08-08-613-coding-multi-agent/task-1-report.md` and `task-2-report.md`.

## MULTI-03 Evidence

- Verification timestamp: `2026-08-09 05:25:00 Asia/Shanghai`.
- Status: complete through `43f51fc`.
- GREEN: 7 focused scheduler/Supervisor tests and the full 188-test suite passed.
- Boundary: dependency order is explicit, independent ready nodes share a wave, retries and total-call budgets are bounded, failures do not run dependents, and pause/resume/cancel are explicit states.
- Detailed source evidence: `.superpowers/sdd/2026-08-08-613-coding-multi-agent/task-3-report.md`.

## MULTI-04 Evidence

- Verification timestamp: `2026-08-09 05:40:00 Asia/Shanghai`.
- Status: complete through `11eaef8`.
- GREEN: 5 focused integration tests and the full 193-test suite passed.
- Boundary: integration checks patch paths against artifact metadata and declared writes before applying; conflicts produce `merge_conflict`, policy violations produce `policy_blocked`, and replay is limited to one marker.
- Detailed source evidence: `.superpowers/sdd/2026-08-08-613-coding-multi-agent/task-4-report.md`.

## MULTI-05 Evidence

- Verification timestamp: `2026-08-09 05:55:00 Asia/Shanghai`.
- Status: complete through `376fd41`; deterministic offline demo clean.
- Demo: completed graph with 5 calls, coder retry, exact approval, clean integration, and final validation; all summary flags true.
- Verification: demo test passed 1; full suite passed 194; Ruff, mypy across 65 source files, `uv lock --check`, and `git diff --check` passed.
- Detailed source evidence: `.superpowers/sdd/2026-08-08-613-coding-multi-agent/task-5-report.md`.

## Recording Rules

Every completed plan task must link a commit and fresh verification output here. Failures, pauses, rejected approvals, user changes, and CI failures remain visible until superseded by new evidence.

## Bootstrap Revision Evidence

- `fc7bf53` adds standard-library CORE-01 verification, explicit online/offline dependency provisioning, and a hard stop when the local cache or wheelhouse is absent.

## Plan Evidence

- `2026-08-08`: `writing-plans` produced four subsystem plans and the root dependency index in commit `a2909c7`.
- CORE-01 through CORE-04 are implemented with task-scoped tests and evidence; Docker and CI work have not started.

## CORE-01 Evidence

- Status: complete, commit recorded in task report.
- Focused test: `PYTHONPATH=src python3 -m unittest tests.test_package.PackageTests.test_package_exposes_version` passed.
- Baseline compile: `python3 -m py_compile scripts/bootstrap_dev.py src/coding_harness/.../__init__.py` passed.
- Provisioning: `DEPENDENCY_PROVISIONING_BLOCKED`; third-party checks were not run.

## CORE-01 Review Repair Evidence

- Verification timestamp: `2026-08-08 18:14:08 Asia/Shanghai`.
- `uv lock`: passed with 54 resolved packages after registry access was approved.
- Bootstrap command: `uv run python scripts/bootstrap_dev.py` is now the documented probe so imports and commands resolve from the managed environment.
- Review status: important findings addressed; generated Python bytecode is ignored and removed from the repair commit.
- Full runtime provisioning: resolved; LanceDB/PyArrow wheel hashes matched `uv.lock`, and `uv sync --all-extras --frozen` completed successfully.

## CORE-01 Development-Tool Verification

- Verification timestamp: `2026-08-08 21:59:19 Asia/Shanghai`.
- `uv run --no-sync python scripts/bootstrap_dev.py`: `DEPENDENCIES_PROVISIONED`.
- `PYTHONPATH=src uv run --no-sync pytest -q`: 1 passed.
- `uv run --no-sync ruff check .`: passed.
- `uv run --no-sync mypy src`: passed.

## DELIVERY-02 Evidence

- Status: complete; implementation commit `bae307b`, evidence commit `4658c54`.
- TDD: focused runner tests first failed on the missing CLI module, then 11 CLI/config/credential tests passed.
- Verification: full suite passed 205 tests; Ruff, mypy, and root Typer help smoke passed.
- Detailed report: `.superpowers/sdd/2026-08-08-613-coding-delivery/task-2-report.md`.

## DELIVERY-03 Evidence

- Status: complete; implementation commit `a8b1f63`, evidence commit `5c1b550`.
- Verification: API-focused suite passed 5 tests; full suite passed 210 tests; Ruff and mypy passed.
- Boundary: request validation, generic error responses, health, ordered events, and lifecycle endpoints are covered.
- Detailed report: `.superpowers/sdd/2026-08-08-613-coding-delivery/task-3-report.md`.

## DELIVERY-04 Evidence

- Status: complete; implementation commit `8403520`, evidence commit `767bfd6`.
- Verification: focused WebUI/API suite passed 7 tests; full suite passed 212 tests; Ruff and mypy passed; root/static smoke returned 200.
- Open Design boundary: the local MCP was unavailable, so implementation followed the approved operations-console design without external generation.
- Detailed report: `.superpowers/sdd/2026-08-08-613-coding-delivery/task-4-report.md`.

## DELIVERY-05 Evidence

- Status: complete for package/files; Docker build blocked by external Docker Hub authorization network reset.
- Verification: distribution suite passed 4; full suite passed 216; `uv build`, Ruff, and mypy passed.
- Boundary: image is non-root with healthcheck and no socket mount; no unverified Docker smoke result is recorded.
- Detailed report: `.superpowers/sdd/2026-08-08-613-coding-delivery/task-5-report.md`.

## DELIVERY-06 Evidence

- Status: complete; implementation commit `511fdd9`, evidence commit `188add5`.
- Verification: recorder suite passed 3 tests; full suite passed 219 tests; Ruff and mypy passed.
- Boundary: commit references are validated, duplicate records are suppressed, and failed results remain visible.
- Detailed report: `.superpowers/sdd/2026-08-08-613-coding-delivery/task-6-report.md`.

## DELIVERY-07 Evidence

- Status: complete; implementation/evidence commit `773bc2a`, final index commit `318dc4a`.
- Final verification: `uv run pytest -q` passed 222 tests; `uv run ruff check .`, `uv run mypy src`, `uv lock --check`, `git diff --check`, and `uv build` passed.
- Runtime audit: installed `run task` now creates and persists a real SQLite/LanceDB-backed run; resume returns a controlled provider failure until an `LLMProvider` is injected, with no placeholder success or credential leakage.
- Repair commit: `d657369` wires the local service bundle and repository-scoped lifecycle commands.
- Boundary: no deployed URL is claimed; Docker network failure remains visible; reflection narrative is reserved for the student.
- Detailed report: `.superpowers/sdd/2026-08-08-613-coding-delivery/task-7-report.md`.

## Delivery Audit Evidence

- Verification timestamp: `2026-08-09 06:32:20 Asia/Shanghai`.
- Fresh gates: `uv run pytest -q` passed 225 tests (one existing Starlette deprecation warning); Ruff passed; mypy passed for 80 source files; `uv lock --check` passed; `uv build` produced both distribution artifacts. `uv tool install . --offline` and its CLI help smoke passed; a live WebUI smoke returned `/healthz` 200 and `/` 200.
- Current-state correction: the requirement table now marks package/Docker files and GitLab CI as implemented/configured with local evidence, while keeping remote pipeline, public URL, Docker registry access, and student reflection as explicitly unverified or reserved.
- Docker boundary: an offline dependency-order simulation was blocked by the uncached `pyarrow==25.0.0` wheel; no Docker build or container smoke pass is claimed.
- No remote CI/deployment claim is made because this workspace has no configured Git remote or deployment credentials.

## SANDBOX-03 Timeout Hardening Evidence

- Verification timestamp: `2026-08-09 06:43:06 Asia/Shanghai`.
- TDD evidence: the timeout test failed before the fix because no container kill occurred; the focused timeout pair passed after the fix.
- Fresh gates: full suite `225 passed`; Ruff, mypy, `uv lock --check`, and `git diff --check` passed.
- Security boundary: Docker command timeout now kills the worker container before returning `timed_out`; cleanup force-removes the terminated container.

## SANDBOX-03 Disk Quota Evidence

- Verification timestamp: `2026-08-09 06:47:21 Asia/Shanghai` (focused RED/GREEN).
- Commit: `287202a`.
- TDD evidence: hardened-container test failed before `storage_opt` wiring and passed after the fix.
- Security boundary: validated `disk_bytes` is passed to Docker storage quota configuration; unsupported storage drivers fail creation and trigger workspace cleanup. Real Docker smoke remains unverified because no approved image was available locally.

## Provider-backed Composition Evidence

- Verification timestamp: `2026-08-09 07:00:59 Asia/Shanghai`.
- Implementation commit: `cf252e0`.
- TDD evidence: config/adapter/composition focused tests passed 13 after expected RED failures.
- Fresh gates: full suite `231 passed`; Ruff passed; mypy passed for 81 source files; `uv lock --check`, `git diff --check`, and `uv build` passed.
- Security boundary: provider metadata is non-secret; the keyring secret is read lazily and is absent from persisted event JSON. No real provider request or deployment claim is made.

## Repository Tool Composition Evidence

- Verification timestamp: `2026-08-09 07:08:18 Asia/Shanghai` (focused RED/GREEN).
- Implementation commit: `cf25473`.
- TDD evidence: the composition workflow test failed before repository tool registration and passed after the toolset/validator wiring.
- Security boundary: tool schemas and policy are still enforced by the owned loop; validation accepts only exact configured argv commands.

## Safe Repository Mutations Evidence

- Status: Tasks 1-4 complete in the reviewed `fix/provider-context-history` worktree; no deployment or remote state was changed.
- Commits: Task 1 `9255c08`, `62c4fe6`; Task 2 `338b363`, `ad2cd04`, `80366e5`; Task 3 `1e6fb22`, `890e576`; Task 4 implementation `c6ce018` plus final close-boundary fix `e80883b`; evidence-record commit follows after this hash is linked.
- Task 4 evidence: `apply_patch` is registered as `coding613.tool.apply_patch.v1`; composition, permission-mode, schema rejection, partial-commit propagation, and credential-header denial regressions are covered.
- Review: independent review's Critical credential-header bypass and Important missing-record findings were addressed; no Critical or Important findings remain.
- Fresh verification: safe mutation and loop integration suite passed 133 tests; full suite passed 313 tests with one pre-existing Starlette/httpx deprecation warning; Ruff, mypy for 83 source files, `uv lock --check`, and `git diff --check` passed.
- Source records: `PLAN.md`, `AGENT_LOG.md`, and `.superpowers/sdd/2026-08-09-safe-repository-mutations/progress.md`.

- Main integration evidence: merge commit `69caa09`; `uv run pytest -q --ignore=tmp` passed 313 tests, Ruff, mypy, lock, and diff checks passed. Unfiltered pytest collection remains blocked by the user-owned `tmp/cube` package import path and is not claimed.

## TUI-01 Evidence

- Status: persisted interactive-session domain/storage implementation and its first review-fix
  round are locally verified and independently re-reviewed with no open Critical/Important issue.
- Commits: `66c11d8` and `b45bb71`.
- Fix evidence: a real SQLite authorizer denial after v1 mutations now rolls the schema and
  `user_version` back together. Offset-bearing session/Run timestamps persist in UTC, legacy
  offset rows normalize on reopen, and chronological activity ordering is covered.
- Latest verification: focused domain/storage suite 19 passed; full harness suite 322 passed with
  one existing Starlette/httpx deprecation warning; relevant Ruff/mypy, `uv lock --check`, and
  `git diff --check` passed.
- Source records: `PLAN.md`, `AGENT_LOG.md`, and
  `.superpowers/sdd/2026-08-09-613-coding-tui-distribution/task-1-report.md`.
- Review: `66c11d8..c23f217` scoped re-review verdict was both findings ADDRESSED, with no new
  breakage or out-of-scope observation.

## TUI-02 Evidence

- Verification timestamp: `2026-08-10 03:21:46 Asia/Shanghai`.
- Status: complete locally at `330d4a5` after recovery from the prior external implementer's
  authentication failure; no deployment, credential, or remote CI state changed.
- TDD: inherited contract/SSE RED/GREEN evidence was reported but not persisted by the failed
  implementer. Controller pre-takeover baseline passed 334 tests. Fresh regression RED produced
  10 expected failures covering deep payload mutation, malformed normal messages, invalid SSE
  tool-call containers/fragments, and a corrected credentialed public-call metadata expectation.
- GREEN: focused Task 2 suite passed 30 tests; scoped Ruff and mypy passed; full offline suite
  passed 342 tests with one existing Starlette/httpx warning; `uv lock --check` and
  `git diff --check` passed.
- Boundary: streaming provider support is optional, progress is ephemeral and recursively frozen,
  malformed provider shapes return `ProviderResponseError`, and one lazy credentialed delegate is
  reused across public stream calls. Source detail is in
  `.superpowers/sdd/2026-08-09-613-coding-tui-distribution/task-2-report.md`.
- CI/CD: no Task 2 remote pipeline was triggered. The latest recorded GitHub Actions result remains
  `31299431092` passed; the next pipeline must cover the TUI branch changes before remote delivery.
- Review fix round 1: missing streamed tool-call IDs now raise `ProviderResponseError` instead of
  receiving a fabricated audit ID. Focused suite passed 31; full offline suite passed 343 with the
  existing Starlette/httpx warning; Ruff, mypy, lock, and diff checks passed. Scoped re-review is
  The focused regression and scoped diff verification address the finding; an independent scoped
  re-review was unavailable in this turn and is explicitly carried into the broad branch review.

## TUI-03 Evidence

- Verification timestamp: `2026-08-10 04:00:00 Asia/Shanghai`.
- Status: implementation locally verified; independent task review pending.
- Focused evidence: loop/composition suite `50 passed`; loop/composition/CLI regression suite
  `55 passed`; Ruff and mypy application checks passed.
- Boundary: progress remains ephemeral, cancellation is cooperative, and idle pause persists a
  nonterminal `PAUSED` Run without a stop reason. No `tmp/cube`, Web removal, packaging, or remote
  deployment files changed.

## TUI-04 Evidence

- Verification timestamp: `2026-08-10 04:20:00 Asia/Shanghai`.
- Status: interactive session application service locally complete; independent review is deferred
  because external Codex authentication returns `refresh_token_invalidated`.
- Evidence: focused suite 20 passed; full offline suite 352 passed with the existing Web warning;
  Ruff, mypy for 87 source files, lock, and diff checks passed.
- Boundary: SQLite remains authoritative; transcript deltas are not persisted; session context is
  bounded and redacted; no Web, packaging, `tmp/cube`, deployment, or credential path changed.

## TUI-05 Evidence

- Verification timestamp: `2026-08-10 04:45:00 Asia/Shanghai`.
- Root `613-coding` now opens the local Textual shell; `--repo`, `--resume`, initial task, help,
  unknown-option, missing-repository, and management dispatch contracts are tested.
- Focused suite passed 13; full offline suite passed 365 with the existing Web warning; Ruff,
  mypy for 91 source files, uv lock, and diff checks passed.

## TUI-06 Evidence

- Verification timestamp: `2026-08-10 04:29:21 Asia/Shanghai`.
- Commit: `048bdbc` (`feat: add streamed coding conversation tui`).
- TDD/Pilot: `uv run pytest tests/tui tests/cli tests/application/test_interactive.py tests/application/test_loop.py -q` passed 95 tests.
- Static gates: scoped Ruff and mypy passed; `uv lock --check` and `git diff --check` passed.
- Behavior: streamed assistant reconciliation, background service execution, idempotent pause,
  approval fingerprint/reason/path/diff details, explicit approve/reject keys, slash commands,
  provider metadata, bounded redacted tool/validation/error output, and 80x24/60x20 long-diff
  scrollability.
- Review boundary: external Codex review remains unavailable due HTTP 401 `refresh_token_invalidated`;
  no independent review success is claimed. No `tmp/cube`, deployment, Web removal, or release
  artifact state changed.

## TUI-07 Evidence

- Verification timestamp: `2026-08-10 04:39:05 Asia/Shanghai`.
- Commit: `4877a7f` (`refactor: replace web console with local tui`).
- Removal/CLI/application suite passed 143 tests; full offline suite passed 380 tests.
- FastAPI/Uvicorn, `coding613.api`, `coding613.web`, Render manifest, runtime entrypoint, and
  container smoke script are absent from the main product. Current guidance no longer instructs a
  server, public URL, SSH, or reverse proxy. Worker sandbox and orchestration sources were not
  changed.

## CI and Deployment Manifest Evidence

- Verification timestamp: `2026-08-09 07:14:20 Asia/Shanghai`.
- Implementation commit: `0d8d63a`.
- Distribution-focused suite passed 7; Ruff, mypy, and `git diff --check` passed.
- Docker build was attempted and failed only while fetching the Docker Hub OAuth token due to connection reset; no image smoke pass is claimed.
- GitLab/GitHub workflow files and Render manifest are configuration evidence only; no remote CI result or public URL is claimed.

## Final External-State Audit

- Verification timestamp: `2026-08-09 07:21:49 Asia/Shanghai`.
- No Git remote, forge token, deployment credential, local CI runner, or public tunnel is available. Docker daemon `29.6.2` is available, but Docker Hub OAuth retrieval resets.
- Remaining external requirements are therefore explicitly open: remote CI final pass, Docker image/worker smoke, deployed WebUI URL, and student-written reflection.

## GitHub Publication Evidence

- Verification timestamp: `2026-08-09 08:49:55 Asia/Shanghai`.
- Remote: `git@github.com:Insouciant21/613-coding.git` configured as `origin`; `git ls-remote --symref origin` confirmed the repository was empty before publication.
- Authentication: `ssh -T git@github.com` identified `Insouciant21`; `git push -u origin main` published `main` at `f4b9984` and established upstream tracking.
- CI result: after GitHub API authentication, runs `31286984595` and `31287048578` exposed a deterministic Ruff `EXE001` failure. Commit `341d880` preserved the bootstrap script executable bit; follow-up run `31287334414` passed all four jobs, including package and Docker image builds.
- Protected paths: `.claude/` and both user-owned requirement documents remain untracked and were not staged.

- REMOTE-CI-01 | 341d880dae20fcfb881e0cc65c9b1e2e7527161e | pass | GitHub Actions run 31287334414 passed: unit-test, quality, demo, package-and-container; Docker image build passed

## Delivery Container Smoke Evidence

- Verification timestamp: `2026-08-09 09:31:00 Asia/Shanghai`.
- Commit: `774c07a`; the Dockerfile now pins `python:3.12.8-slim-bookworm@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0`, exposes `/app/.venv/bin`, and runs as `coding`.
- TDD: the original image smoke failed with exit `127` (`coding-harness: not found`); the PATH contract, smoke behavior, and CI wiring then passed their RED/GREEN cycles.
- Local evidence: `docker build --pull=false -t 613-coding:smoke-fix .` succeeded; `scripts/smoke_container.sh 613-coding:smoke-fix` returned `container smoke passed: health=healthy user=coding`; `docker ps -a` showed no retained smoke container.
- Remote evidence: [GitHub Actions run 31288535830](https://github.com/Insouciant21/613-coding/actions/runs/31288535830) passed for main commit `cf7f8a5`; [package-and-container job 93181629275](https://github.com/Insouciant21/613-coding/actions/runs/31288535830/job/93181629275) passed Docker build and smoke. The full isolated suite passed `237 tests`; Ruff, mypy, and `git diff --check` passed.

- DELIVERY-05-SMOKE | 774c07abed7c16200b341277a094bbe1f4e844fb | pass | Local image built and smoke passed: health=healthy user=coding; no smoke container remained

- REMOTE-CI-02 | 60ce34bf795f04f3c33d2d25fb24468d1c9cad82 | pass | main 60ce34b passed: unit-test, quality, demo, package-and-container; Docker build and smoke passed

- REMOTE-CI-03 | cf7f8a5ee387965003f76bd1f374a288bc0067c0 | pass | main cf7f8a5 passed: unit-test, quality, demo, package-and-container; Docker build and smoke passed

- DEPLOY-01 | 35a383a9bed47d5fc50c691655e71eb18d630348 | blocked | Render API returned HTTP 401; no Render credential or deployed service URL is available

## Claude-Code-Parity Task 5 Evidence

- Verification timestamp: 2026-08-10 14:10:00 Asia/Shanghai.
- Commit: `b7111cd` (`feat: enforce invocation permission filters`).
- TDD/verification: focused permission/policy/loop/composition/storage/TUI/CLI suite passed 126 tests; the final changed-boundary gate passed 36 tests; `uv run ruff check .`, `uv run mypy src`, and `git diff --check` passed.
- Boundary: `ToolFilter` is applied after hard policy evaluation and again during approval resume; project permission rules are validated, persisted in SQLite, loaded into new run dependencies, and exposed through the application service used by TUI slash commands. No API key or network operation was used.

## Claude-Code-Parity Task 6 Evidence

- Verification timestamp: 2026-08-10 14:25:00 Asia/Shanghai.
- Commit: `67206b7` (`feat: add context diagnostics and model overrides`).
- TDD/verification: Task 6 focused context/compaction/diagnostics/SDK/TUI suite passed 43 tests; the full offline suite passed 443 tests; Ruff, mypy across 102 source files, and `git diff --check` passed.
- Boundary: summaries are redacted and additive in SQLite, deterministic compaction is injected and failure-safe, diagnostics isolate failed checks, and model/system-prompt overrides are request-scoped without changing configured provider defaults or persisting secrets.

## Claude-Code-Parity Task 7 Evidence

- Verification timestamp: 2026-08-10 14:50:00 Asia/Shanghai.
- Commits: `fd8871e` (`feat: align tui and cli conversation workflow`), `f27dba6` (documentation and evidence updates), and `aefde6e` (final references).
- TDD/verification: focused RED/GREEN contracts cover documentation, shared TUI/CLI request delegation, follow-up after resume, escaped slash prompts, lifecycle/diagnostic stream events, invalid selectors, active-run prevention, and prompt redaction. `uv run pytest -q --ignore=tmp` passed `460`; Ruff, mypy across 102 source files, `uv lock --check`, and `git diff --check` passed.
- Smoke/review: `uv run 613-coding --help` returned 0. Provider-unconfigured print and verbose stream smokes returned documented exit code 4 with versioned redacted output. Independent review agents disconnected before returning reports; local spec/security/type review found no unresolved Critical issue, and no independent pass is claimed.
- Boundary: the TUI compatibility adapter and print CLI share `ConversationService`; SQLite remains authoritative, active runs are not duplicated, and MCP remains an injectable future boundary. Main-worktree user changes and untracked files were not staged.

## Claude-Code-Parity completion audit evidence

- Verification timestamp: 2026-08-10 15:04:34 Asia/Shanghai.
- Commit: `45decdd` (`feat: expose tui and cli run feedback`).
- TDD: the audit RED cycle covered missing CLI verbose validation/feedback/approval fields,
  missing TUI terminal summary/footer/elapsed/pause behavior, and strict enum parsing at the
  JSON-safe validation-progress display boundary. GREEN added the fixes and a real Textual Pilot
  prompt-to-harness integration test.
- Verification: `uv run pytest tests/tui -q` passed 51; `uv run pytest tests/cli -q` passed 33;
  `uv run pytest -q --ignore=tmp` passed 468; Ruff, mypy across 102 source files, `uv lock --check`,
  and `git diff --check` passed. `613-coding --help` returned 0; provider-unconfigured print
  returned 4 with `status=failed stop_reason=provider_error`.
- Boundary: no real provider, credential/keyring, network, Docker, remote CI, merge, or deployment
  operation was used. The main worktree's pre-existing user changes and untracked files remain
  untouched and unstaged.

## Claude-Code-Parity local integration evidence

- Verification timestamp: 2026-08-10 16:22:48 Asia/Shanghai.
- Integration: the user selected local merge; `feature/claude-code-parity` fast-forwarded `main`
  from `75c6877` to `0c37379`.
- Preservation: the pre-existing main-worktree changes were saved in recoverable
  `stash@{0}` (`pre-merge-user-changes-2026-08-10`) and restored. The only conflict was
  `src/coding613/application/context.py`; its resolution retains both the user's no-progress
  escalation and the parity context-store interface. `tmp/cube/` is a nested Git repository and
  was left untouched.
- Verification: merged main passed `uv run pytest -q --ignore=tmp` (`471 passed, 253 existing
  pytest-asyncio deprecation warnings`), Ruff, mypy across 102 source files, `uv lock --check`, and
  `git diff HEAD --check`.
- Current status: parity code is integrated locally; user-modified tracked files and untracked
  user files remain uncommitted and unstaged. No remote pull/push, provider, credential, Docker, or
  deployment operation was performed.

## Package Rename Task 3 Evidence

- Verification timestamp: `2026-08-09 14:26:25 Asia/Shanghai`.
- TDD RED: `uv run pytest tests/test_docs.py::test_current_docs_use_613_coding_package_names -q` failed with one assertion because current guidance did not contain `613-coding web`.
- TDD GREEN: the focused contract passed `1`; the documentation suite passed `4`; the full suite passed `241` with the pre-existing deferred Starlette TestClient warning. Ruff, mypy across `82` source files, lock, and diff checks passed.
- Clean artifacts: `uv build` generated `613_coding-0.1.0-py3-none-any.whl` and `613_coding-0.1.0.tar.gz`; a fresh venv exposed `613-coding --help`, had no `coding-harness` executable, imported `coding613`, and did not resolve the legacy import.
- Container: `613-coding:rename-smoke` built from the current source and the smoke script returned `container smoke passed: health=healthy user=coding`; no smoke container remained.
- Source record: `.superpowers/sdd/2026-08-09-613-coding-package-rename/task-3-report.md`.

## Package Rename Task 4 Evidence

- Verification timestamp: `2026-08-09 14:49:47 Asia/Shanghai`.
- Review and publication: the full rename diff had no Critical or Important findings. Branch run [31299368456](https://github.com/Insouciant21/613-coding/actions/runs/31299368456) and exact-main run [31299431092](https://github.com/Insouciant21/613-coding/actions/runs/31299431092) passed `unit-test`, `quality`, `demo`, and `package-and-container` at `eefee2dd2a2f33ea9921fe0ce147e88719d4b14d`.
- Runtime: `/home/edward/services/613-coding/releases/eefee2d` produced `613-coding:eefee2d` (`sha256:61d42ea1397ba878caf0a04592b3b6c1637c9ee9537deb3b2657ab91a913b0b2`). `613-coding --help` succeeded in the deployed container, `coding-harness` was absent, and `/healthz` plus `/` returned 200.
- State: existing runs `c0313a2c-7513-4a7b-a594-9afe0d31dc70` and `b9bc83a2-dac2-48c3-a15a-8bae7568118b` remained readable. New run `de1c5292-d40f-4924-8d0d-2d85df1b4731` returned 200 before and after a container restart.
- Boundary: loopback bind, data mount, read-only root, tmpfs restrictions, dropped capabilities, `no-new-privileges`, resource/PID limits, supplementary group, non-root user, and restart policy match the pre-deployment container. The reverse proxy and ports 80/443 were not changed; no public URL is claimed.

## SSH Deployment Evidence

- Verification timestamp: `2026-08-09 13:15:03 Asia/Shanghai`.
- Fix: commits `4d1fbad` and `71c281d` make a newly persisted run readable before its first loop session; independent review found no Critical or Important issue.
- Verification: the focused regression passed, then the full suite passed 239 tests; Ruff, mypy for 82 source files, lock, and diff checks passed. Branch run `31295983040` and main run [31296034199](https://github.com/Insouciant21/613-coding/actions/runs/31296034199) passed all four jobs, including Docker build and smoke.
- Runtime: `edward@int21` runs `613-coding:71c281d` at `127.0.0.1:8613` with persistent state at `/home/edward/services/613-coding/data`. The root page and `/healthz` returned 200/healthy.
- Persistence: pre-fix run `c0313a2c-7513-4a7b-a594-9afe0d31dc70` became readable after deployment. New run `b9bc83a2-dac2-48c3-a15a-8bae7568118b` returned 200 both immediately and after `docker restart`, with the same `running` state and empty evidence.
- Boundary: no reverse proxy, ports 80/443, domain, or public URL was configured or claimed.

## Same-run provider retry

- Status: implemented and offline verified in the current dirty worktree.
- Evidence: `AGENT_LOG.md` entry `2026-08-10 18:05:00 Asia/Shanghai`; RED focused timeout test,
  GREEN loop/adapter tests (71), `uv run pytest tests -q` (472), Ruff, and mypy.
- Behavior: typed transient provider timeouts become persisted retryable feedback and the same
  `AgentLoop` resumes with event context; model-call and wall-clock budgets remain finite.
- Boundary: no real provider request or credential operation was performed during verification.

## 2026-08-10 21:19:31 Asia/Shanghai - Self-iteration target audit

- Status: root same-run retry implementation is verified; `tmp/cube` remains an incomplete,
  worker-authored RED artifact and is not a delivered product.
- Run evidence: `5bdaef15-c288-429c-b3ac-5cd22d7dd1a6` stayed in one process for 16 model calls
  and briefly reached 43/43 web tests before oscillating on lint. Follow-ups
  `ae7c581b-e52f-4fc2-9d15-30fb7eedf4fb`, `54240807-d35b-4b76-863e-41836f2d3539`, and
  `74a5ee84-f4f3-41b8-9dc4-bd5d8f47f1cc` were cancelled after repeated non-minimal rewrites.
- Current verification: target `bash scripts/verify.sh` is RED; no completion, package, or
  deployment evidence is claimed for the cube application. No provider credential or
  `deepseek-chat` configuration was used.
- Fresh target verifier at 21:22 failed 36/43 web tests (`cloneStickers is not a function` at
  `apps/web/src/cube/moves.ts:212`).

## 2026-08-10 21:37:42 Asia/Shanghai - Codex patch protocol

- Status: harness compatibility slice verified; target delivery remains in progress.
- Evidence: the new Codex marker-format parser test was RED before implementation and GREEN
  afterward; focused tests passed 81 and the full root suite passed 475.
- Quality gate: Ruff, mypy (102 files), `uv lock --check`, and `git diff --check` passed.
- Boundary: no `tmp/cube` product source was controller-authored; the target verifier is still RED.
- Next: resume a single patch-only 613 Coding run using the configured `deepseek-v4-flash` model,
  then record the independent target verifier result here.

## 2026-08-10 22:18:00 Asia/Shanghai - Repeated-write guard

- Status: in progress; the harness now blocks exact replays of successful file mutations and the
  target product is not yet delivered.
- Evidence: TDD focused guard passed; `uv run pytest tests -q` passed 481, Ruff, mypy (102 files),
  `uv lock --check`, and `git diff --check` passed.
- Target: `559fb873-1725-464c-9289-6e573e2893a9` is failed by budget exhaustion after 30 calls;
  target web tests were 43/43 at the last build run, but TypeScript build/API contract errors
  remain and the final `bash scripts/verify.sh` is RED.
- Responsible actor: root harness plus the next long-lived 613 Coding target run. No controller
  authored or overwrote `tmp/cube` product source.

## 2026-08-10 21:23:17 Asia/Shanghai - Root verification refresh

- Root harness: `uv run pytest tests -q` passed 473 (253 existing warnings); retry-focused tests,
  Ruff, mypy, `uv lock --check`, and `git diff --check` passed.
- Target: `tmp/cube` remains a worker-authored RED artifact; its verifier failure is recorded in
  the target `AGENT_LOG.md` and no delivery claim is made.

## 2026-08-10 23:25:55 Asia/Shanghai - Target foundation/domain delivery

- Status: foundation/domain slice complete; full target product acceptance remains in progress.
  Source under `tmp/cube/apps/web/src/cube` was written by governed 613 Coding worker runs.
- Fresh verification: `(cd tmp/cube && bash scripts/verify.sh)` passed 43 web tests, ESLint,
  TypeScript, Vite build, API pytest, Ruff, and mypy. Existing Starlette deprecation warning only.
- Security: worker-generated temporary provider-data file `tmp` was removed by governed
  `delete_file`; credential-pattern scanning of target files returned no matches.
- Responsible actor: 613 Coding worker for target source; controller for verification, safety
  review, and delivery records. Root offline gate passed: 481 tests, Ruff, mypy, lock, and diff
  checks are green.
- Open scope: 3D editing, solver API/jobs, rich reachability diagnostics, playback, and browser
  end-to-end acceptance are not yet delivered.

## 613 Coding workbench/API vertical slice

- Status: partial delivery complete; full cube-solver acceptance remains in progress.
- Verification timestamp: 2026-08-11 00:21:06 Asia/Shanghai.
- Target evidence: governed worker run `a9330e89-776d-4e1e-b9d1-8abdcd372b02` completed with
  `(cd tmp/cube && bash scripts/verify.sh)` green: 45 web tests, ESLint, TypeScript, Vite build,
  5 API tests, Ruff, and mypy. Existing Starlette TestClient deprecation warning only.
- Delivered target surface: interactive responsive sticker workbench with order selection,
  palette painting, moves, undo/redo/reset, plus synchronous `/api/validate` diagnostics.
- Harness evidence: SQLite cross-process run-status CAS regression passed; root offline gate passed
  482 tests (253 existing warnings), Ruff, mypy across 102 files, `uv lock --check`, and
  `git diff --check`.
- Responsible actor: 613 Coding workers authored target source; controller ran verification,
  safety checks, and records. No `deepseek-chat`, credential value, remote push, or deployment was
  used.
- Remaining acceptance: Three.js 3D editor, rich reachability/solver integration, job events and
  cancellation, formula explanation/playback, Docker Compose, and Playwright browser tests.
- Documentation synchronization: target README and AGENT_LOG were updated by governed runs
  `fa5a3510-ce43-4911-bf17-600835305951` and `5a23372a-fbe4-4ffc-bcd0-f87e0f50442c`; their target
  verifiers passed with the same 45 web / 5 API test evidence.

## 2026-08-11 04:02:00 Asia/Shanghai - Context and patch-tool audit

- Status: harness compatibility improvements verified; Cube product delivery remains in progress.
- Root evidence: default Responses `max_output_tokens` is 8192 after RED/GREEN testing; the
  standard Git patch wrapper and unique stale-hunk recovery are covered by new RED/GREEN tests.
  `uv run pytest tests -q` passed 500, Ruff, mypy, and diff checks passed.
- Target evidence: worker persistence slice completed after bounded repairs; fresh
  `tmp/cube/bash scripts/verify.sh` passed 61 Web tests, 8 API tests, ESLint, TypeScript, Vite
  build, Ruff, and mypy at 04:01. One expected jsdom localStorage warning remains.
- Forensic conclusion: persisted events show partial context, model tool actions, output-budget
  truncation, and patch-format/offset errors. The run did not operate with zero context.
- Remaining acceptance: full Three.js editor, authoritative reachability/solver replay, formula
  playback, Compose/Nginx, Playwright coverage, and final target delivery evidence.

## 2026-08-11 04:44 CST - Three.js viewport checkpoint

- Status: partial target progress; not a final delivery.
- Evidence: worker runs `d561ff22-0b76-4e16-8c6a-f9965017a3e7`,
  `f35e5bf8-b67a-44d8-baac-f056872a7ce7`, and `624146d5-caf1-45e3-aa09-f6d9b90379b8`
  installed/implemented/repaired the viewport. Independent `bash scripts/verify.sh` passed
  62 Web tests and 8 API tests plus ESLint, TypeScript, Vite build, Ruff, and mypy at
  2026-08-11 04:44 CST.
- Harness evidence: root config RED/GREEN test now enforces default `max_output_tokens=32768`
  after trace evidence showed 8192-token reasoning truncation. Root full-suite rerun is still
  required after this change.
- Remaining: authoritative solver/replay and reachability, formula explanation/playback, job
  event streaming/cancellation, Docker Compose/Nginx, Playwright desktop/mobile, docs, and
  final review.
- Post-change root verification at 04:45 CST: 503 offline tests passed; Ruff, mypy, and
  `git diff --check` passed. This checkpoint is not final delivery evidence.

## Current Working-tree Repair (2026-08-11 19:00 CST)

- Status: verified locally; responsible actor: controller.
- Change: `run_validation` now exposes a redacted actionable undeclared-command error and lists
  declared argv guidance; CLI TUI mode inheritance respects repository config; TUI `/config`
  supports validated show/set operations with atomic persistence and reload.
- Fresh verification: `uv run pytest -q --ignore=tmp` → 517 passed; `uv run ruff check .` and
  `uv run mypy src` → passed; `613-coding config check --repo tmp/cube` → configuration valid.
- Delivery boundary: no remote CI, push, deployment, or credential-backed provider request was
  performed. Changes are still uncommitted in the pre-existing working tree.

## Current TUI Discoverability Slice (2026-08-11 19:09 CST)

- Status: verified locally; responsible actor: controller.
- Change: the Textual TUI now displays persistent shortcut/approval guidance, live slash-command
  candidates, Tab/↑/↓ completion cycling, and `/help` discovery instructions while retaining
  prompt-history fallback and strict command parsing.
- Fresh verification: `uv run pytest -q --ignore=tmp` → 521 passed; `uv run ruff check .`,
  `uv run mypy src`, and `git diff --check` → passed.
- Documentation evidence: README and `docs/development.md` describe the new interaction.
- Delivery boundary: no remote CI, provider request, credential access, push, or deployment was
  performed; changes remain in the existing uncommitted working tree.

## Current TUI No-action and Composer Display Repair (2026-08-11 19:55 CST)

- Status: verified locally; responsible actor: controller.
- Delivered: an explicit action-repair prompt plus a bounded no-action retry (one repair turn, then
  `no_progress`), per-turn assistant draft replacement, tooltip-free focused composer, and
  narrow-terminal layout regression checks.
- Fresh evidence: `uv run pytest -q --ignore=tmp` passed 528 tests; Ruff, mypy, lock, and diff checks
  passed. The global tool was rebuilt with `uv tool install --force --reinstall --no-cache .` and
  `613-coding config check --repo tmp/cube` passed at 20:00 CST.
- Boundary: no external model request, credential access, target source change, deployment, or
  remote CI result; changes remain in the existing uncommitted working tree.
- Distribution refresh at 19:45 CST: global `613-coding` was rebuilt from the current checkout;
  installed-tool preview/expand and configuration probes passed.
- Final 19:11 CST refresh after the layout/shortcut hint polish preserved the same green evidence.

## Current TUI Dependency/Startup Repair (2026-08-11 19:23 CST)

- Status: verified locally; responsible actor: controller.
- Change: pinned Rich to the Textual-compatible `<14.2` range, added a Markdown-link regression,
  and refreshed the global `613-coding` uv tool so the Responses-aware configuration fields are
  available at runtime.
- Fresh verification: `uv run pytest -q --ignore=tmp` → 522 passed; Ruff, mypy, `uv lock --check`,
  and `git diff --check` → passed. Installed-tool configuration and Markdown-link probes passed.
- Documentation evidence: README and `docs/deployment.md` document global-tool refresh behavior.
- Delivery boundary: no remote CI, provider request, credential access, push, or deployment was
  performed; changes remain in the existing uncommitted working tree.

## Current TUI Tool Output Preview (2026-08-11 19:43 CST)

- Status: verified locally; responsible actor: controller.
- Change: large `read_file`/tool-result entries now render a 1,200-character preview with
  redaction preserved; `Ctrl+T` toggles the latest result between preview and expanded view.
- Fresh verification: `uv run pytest -q --ignore=tmp` → 524 passed; TUI suite → 64 passed;
  Ruff, mypy, and `git diff --check` → passed.
- Delivery boundary: no remote CI, provider request, credential access, push, or deployment was
  performed; changes remain in the existing uncommitted working tree.

## Current Responses Tool Stream Repair (2026-08-11 20:18 CST)

- Status: verified locally; responsible actor: controller.
- Root cause: DeepSeek's Responses stream splits function-call metadata across events and omits
  `name` on `response.function_call_arguments.done`; the old parser rejected the valid sequence,
  so the loop retried 30 provider errors before reporting budget exhaustion and never reached TUI
  tool rendering.
- Delivered: event merging now preserves the function name from `output_item.added`; repeated
  retryable provider errors stop after two attempts with `provider_error`; regression coverage was
  added for both behaviors.
- Fresh evidence: `uv run pytest -q --ignore=tmp` → 529 passed; Ruff, mypy, lock, and diff checks
  passed. Direct live stream parsing produced a `read_file` action. The refreshed global
  `613-coding` executable passed `config check`, and a bounded print-mode smoke run persisted
  successful `read_file`/`search_files` tool completions before its deliberate three-call cap.
- Delivery boundary: no credentials were exposed, no target files were edited by the smoke run,
  and no remote CI, push, or deployment was performed. Restart any old TUI process and start a
  fresh run; historical failed runs in SQLite are retained for diagnosis.

## Current apply_patch Conflict Repair (2026-08-11 20:28 CST)

- Status: verified locally; responsible actor: controller.
- Root cause: repository tool error wrapping discarded the useful `PatchConflictError` message,
  leaving the TUI with only the exception class and leaving the next model call without a stale-
  patch recovery instruction.
- Delivered: bounded redacted conflict details are now visible in the tool result and loop
  feedback; context assembly tells the worker to re-read affected files and create a fresh patch,
  while explicitly forbidding unchanged retries.
- Fresh evidence: `uv run pytest -q --ignore=tmp` → 531 passed; Ruff, mypy, lock, and diff checks
  passed. The refreshed global executable passed `config check --repo tmp/cube` and CLI help.
- Delivery boundary: patch safety remains strict and no automatic overwrite was added; changes
  remain in the existing uncommitted working tree.

## Current Tool Output and Validation Repair (2026-08-11 20:46 CST)

- Status: verified locally; responsible actor: controller.
- Root causes addressed: large tool output was truncated in the agent progress layer before TUI
  expansion; `run_validation` displayed shell syntax that encouraged a one-element argv; and the
  finish gate required validation for read-only inspections.
- Delivered: tool output now travels through a redacted 1 MiB safety cap, renders as a 1,200-character
  preview with `Ctrl+T` expansion, and validation descriptions/errors show exact JSON argv arrays.
  Read-only runs may finish without validation; any repository mutation still requires fresh passing
  validation.
- Fresh evidence: `uv run pytest -q --ignore=tmp` passed 533 tests; Ruff, mypy, `uv lock --check`,
  and `git diff --check` passed. The refreshed global executable passed `613-coding config check
  --repo /home/int21/Workspace/ai4se_project/tmp/cube` and CLI help.
- Delivery boundary: no credentials, provider request, target cube source edit, remote CI/push, or
  deployment was performed. Changes remain in the existing uncommitted working tree.

## Current Legacy Validation argv Compatibility (2026-08-11 20:52 CST)

- Status: verified locally; responsible actor: controller.
- Delivered: old prompts that send `argv=["bash scripts/verify.sh"]` are canonicalized only when
  they exactly match a declared command after `shlex.split`; exact JSON argv remains the primary
  model contract and undeclared commands are still rejected.
- Fresh evidence: focused RED/GREEN regression, `uv run pytest -q --ignore=tmp` → 534 passed,
  Ruff, mypy, `uv lock --check`, and `git diff --check` passed. Global `613-coding` refresh,
  `config check --repo /home/int21/Workspace/ai4se_project/tmp/cube`, and CLI help passed.
- Delivery boundary: shell execution remains disabled; no credentials, provider request, target
  source edit, remote CI/push, or deployment was used.

## Current Codex-aligned Provider Retry Window (2026-08-11 21:32 CST)

- Status: implemented and offline verified; responsible actor: `/root`.
- Behavior: transient provider failures now have five retries after the initial request (`1/5`
  through `5/5`), allowing at most six total requests; the sixth failure is terminal. Authentication and other client-side HTTP 4xx request errors
  are classified as non-retryable `ProviderRequestError`; rate limits, transport failures, and
  5xx responses remain retryable.
- TDD/verification: the updated repeated-provider-error test was RED at the old two-attempt
  behavior; focused loop/adapter tests passed 85; full offline suite passed 538 tests. Ruff,
  mypy, lock, and diff checks passed.
- Boundary: the historical failed run is not rewritten. No real provider request, credential
  access, target source edit, remote push, or deployment was performed; restart an installed TUI
  and start a fresh run to exercise the change.

## Current Retry Semantics Correction (2026-08-11 21:40 CST)

- Codex parity is now precise: five retries after the initial request (`1/5` through `5/5`),
  allowing six total provider calls; the sixth failure is terminal.
- Final evidence: the six-call RED/GREEN regression passed; `uv run pytest -q --ignore=tmp` passed
  538 tests; Ruff, mypy, lock, and diff checks passed. The global `613-coding` tool was refreshed,
  and CLI/config probes passed.
- No real provider request, credential exposure, target source edit, remote push, or deployment
  occurred. Existing failed runs remain historical; use a fresh run.

## Current Context/Validation/TUI/Budget Follow-up (2026-08-11 22:10 CST)

- Status: implemented and offline verified; responsible actor: `/root`.
- Context/cache: the stable system prefix now contains worker/repository/memory/final guidance,
  with task before changing ledger/events; `cache_prefix_sha256` is emitted for diagnostics.
- Validation: write tools no longer launch validation; explicit `run_validation` or the final
  `finish` boundary performs the objective check, while no-op writes remain immediately classified.
- TUI: tool and validation results render with plain `Text`, validation previews are capped at 240
  lines, and `Ctrl+T` expands both details; output backgrounds are explicit to avoid Syntax blocks.
- Budgets: model-selected `set_task_budget` chooses clamped simple/standard/complex profiles,
  persists the selection, updates per-agent turns, and passes per-run output-token caps to both
  OpenAI-compatible Chat and Responses adapters.
- Evidence: `uv run pytest -q --ignore=tmp` → 542 passed with 316 existing warnings;
  `uv run ruff check .` and `uv run mypy src` passed. No real provider request, credential access,
  target `tmp/cube` source edit, remote push, deployment, or destructive Git operation occurred.

### Final verification (2026-08-11 22:22 Asia/Shanghai)

- Status: verified locally; responsible actor: `/root`.
- Offline suite: 542 passed, 316 existing warnings.
- Ruff, mypy, lock consistency, and diff whitespace checks passed.
- Installed `613-coding` was rebuilt from this checkout; CLI help and the `tmp/cube` configuration
  probe passed.
- No provider request, credential access, target source mutation, remote push, or deployment was
  performed.

### TUI Preview Limits (2026-08-11 22:24 Asia/Shanghai)

- Status: verified locally; responsible actor: `/root`.
- Requested limits: tool preview 200 characters, validation preview 10 lines; expansion and safety
  bounds are unchanged.
- Focused renderer tests and full offline suite passed; Ruff, mypy, lock, and diff checks passed.
- Global CLI was rebuilt and the `tmp/cube` configuration probe passed.

### Context-Controlled Agent Conversation (2026-08-11 23:09 Asia/Shanghai)

- Status: implemented and verified locally; responsible actor: `/root`.
- User-visible repair: when the model returns an empty `content` with a valid `finish.summary`,
  the TUI/transcript now shows the finish answer rather than stale planning text. The profile
  selection tool is removed from subsequent model requests.
- Runtime behavior: per-agent-turn budgets no longer stop a run; context compaction controls
  dynamic conversation length. Output-token profiles remain adaptive, while total calls, wall time,
  and provider cost remain safety limits. Legacy config is displayed as `per_agent_turns:unbounded`.
- Fresh evidence: `uv run pytest -q --ignore=tmp` → 543 passed (316 warnings); Ruff, mypy, and
  `git diff --check` passed. `uv tool install --force --editable .`, direct CLI config check, and
  installed-module inspection passed.
- Latest verification timestamp: 2026-08-11 23:09 CST. No provider request, credential access,
  target `tmp/cube` source edit, remote push, deployment, or destructive Git operation occurred.

### Final-answer precedence follow-up (2026-08-11 23:15 Asia/Shanghai)

- A screenshot-shaped regression (planning text first, accepted finish summary second, empty final
  content) was reproduced and fixed. Completed-iteration `finish.summary` now takes precedence over
  stale planning text in the interactive transcript.
- Fresh evidence: full offline suite 543 passed with 316 warnings; Ruff, mypy, and diff checks
  passed; editable `613-coding` refresh and `tmp/cube` config check passed.

### LLM Context Window Configuration (2026-08-11 23:36 Asia/Shanghai)

- Status: implemented and verified locally; responsible actor: `/root`.
- Configuration: add `[llm] context_window_chars = 48000` to `harness.toml`; the setting controls
  dynamic event compaction. `/config set llm.context_window_chars VALUE` validates and applies it
  to future turns after reload; the CLI config check displays the active value.
- Fresh evidence: `uv run pytest -q --ignore=tmp` → 547 passed (316 warnings); Ruff, mypy,
  `uv lock --check`, and `git diff --check` passed. Editable global CLI refresh and `tmp/cube`
  config probe passed.
- Latest verification timestamp: 2026-08-11 23:36 CST. No provider request, credential access,
  target source/config mutation, remote push, deployment, or destructive Git operation occurred.

### Default resource and reasoning-level update — 2026-08-12 01:13 Asia/Shanghai

- Status: implemented and verified locally; responsible actor `/root`.
- Delivery: default context `256000` chars; internal tool output progress cap `10000000` chars;
  standard/complex output profiles `16384`/`128000` decimal tokens; `simple` removed; arbitrary
  provider-defined reasoning strings supported in configuration, CLI, TUI suggestions, Chat
  Completions, Responses, and Anthropic paths.
- Verification: 582 offline tests passed (334 warnings); Ruff, mypy, lock, and whitespace checks
  passed. Editable CLI installation, provider help, local defaults probe, and `tmp/cube` policy
  config check passed. No provider request or credential mutation was performed.

### TUI provider management — delivered (2026-08-12 01:36 Asia/Shanghai)

- Status: ready for commit; responsible actor: `/root`.
- User-facing behavior: `/provider` opens Add/Use/Edit/Delete/Set key/Clear key actions; direct
  slash forms support `/provider add`, `/provider edit NAME`, `/provider remove NAME`,
  `/provider key NAME`, and `/provider clear-key NAME`. Add/edit use a modal form, API keys use
  password inputs, and destructive actions require confirmation.
- Scope/security: non-secret provider metadata is persisted through `UserConfigurationService`;
  API keys remain in the OS keyring and are never rendered in conversation output. Removing a
  profile does not silently erase its credential; the explicit clear-key action does that.
- Verification: `uv run pytest -q --ignore=tmp` -> 595 passed with 370 warnings; `uv run ruff check .`,
  `uv run mypy src`, `uv lock --check`, and `git diff --check` passed.
- Latest verification timestamp: 2026-08-12 01:36 Asia/Shanghai. Commit: `280817f`.

### TUI provider menu worker fix — delivered (2026-08-12 01:49 Asia/Shanghai)

- Status: verified; responsible actor: `/root`.
- Fix: provider menu selections now run through a `config-menu` worker. This covers add/edit/set-key
  actions that await modal dismissal and preserves ordered cleanup for switch/delete/clear actions.
- Regression: selecting Add provider from the menu and saving now persists metadata without rendering
  the Textual worker-context error.
- Verification: `uv run pytest -q --ignore=tmp` -> 596 passed with 379 warnings; Ruff, mypy, and
  diff checks passed. Commit: `698e0c0`.

### Repeated patch-conflict recovery — delivered (2026-08-12 02:25 Asia/Shanghai)

- Status: verified locally; responsible actor: `/root`.
- Fix: identical stale `apply_patch` calls now receive one deterministic fresh-read repair turn,
  then stop with `NO_PROGRESS` rather than filling the TUI with repeated failures. Different
  patches and intervening reads remain eligible to continue. Legacy conflict events without output
  now show the same re-read guidance in the renderer.
- Verification: `uv run pytest tests -q` -> 604 passed with 379 warnings; `uv run ruff check src
  tests`, `uv run mypy src`, and `git diff --check` passed.
- Commit: pending this follow-up commit.
