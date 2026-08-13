# Dangerous Bypass Permission Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicitly selected `bypass` permission mode that executes every approval-eligible action, including undeclared shell commands, without creating approval requests while preserving all deterministic denials and sandbox constraints.

**Architecture:** Extend the existing `PermissionMode` and selection surfaces, then apply bypass once at the end of repository policy evaluation by converting only `ASK` decisions to `ALLOW`. Keep schema validation, invocation filters, explicit denials, hard safety checks, tool dispatch, feedback, budgets, and sandbox execution unchanged. Persist the canonical `bypass` string through existing config/run storage and make the dangerous state conspicuous in operator output.

**Tech Stack:** Python 3.12+, Pydantic, argparse, Typer, Textual, SQLite, pytest/pytest-asyncio, Ruff, mypy, uv.

## Global Constraints

- The new enum/config value is exactly `bypass`; existing values and the default `balanced` behavior remain unchanged.
- Only explicit user configuration or invocation options may select bypass; the model receives no mode-changing tool.
- Bypass converts `PolicyEffect.ASK` to `PolicyEffect.ALLOW`; it never changes `PolicyEffect.DENY`.
- `allow_writes = false`, `denied_tools`, explicit deny rules, repository/credential boundaries, secret redaction, destructive-command checks, invalid schemas, and unknown tools remain denied.
- Shell execution remains argv-only with no `shell=True`; timeouts, output caps, environment allowlists, resource limits, event persistence, and sandbox policy remain active.
- Existing pending approvals are never retroactively consumed when a later run or default selects bypass.
- Tests remain offline and use fakes; no real LLM, credential, network, Docker daemon, or external repository is required.
- Preserve unrelated user changes. At execution time use `using-git-worktrees` and record any justified workflow deviation in `AGENT_LOG.md`.
- Follow RED → GREEN → refactor for every implementation task and record the observed commands.

---

### Task 1: Domain, configuration, persistence, and root CLI selection

**Files:**
- Modify: `src/coding613/domain/models.py`
- Modify: `src/coding613/domain/session_events.py`
- Modify: `src/coding613/application/events.py`
- Modify: `src/coding613/cli/prompt.py`
- Modify: `tests/domain/test_models.py`
- Modify: `tests/config/test_config.py`
- Modify: `tests/application/test_configuration.py`
- Modify: `tests/adapters/storage/test_sqlite.py`
- Modify: `tests/cli/test_prompt.py`
- Modify: `tests/cli/test_entrypoint.py`
- Modify: `tests/cli/test_output.py`
- Modify: `tests/cli/test_parity_contract.py`

**Interfaces:**
- Consumes: `PermissionMode`, `HarnessConfig.permission_mode`, `Run.permission_mode`, `RootLaunchRequest.permission_mode`, `parse_root_args(argv)`.
- Produces: `PermissionMode.BYPASS = "bypass"`, root flag `--dangerously-skip-permissions`, deterministic conflicting-option rejection, and effective-mode fields in text/JSON/stream output.

- [ ] **Step 1: Write failing enum, config, storage, and CLI tests**

Add these focused contracts:

```python
def test_permission_modes_include_bypass() -> None:
    assert {mode.value for mode in PermissionMode} == {
        "strict", "balanced", "autonomous", "bypass"
    }


def test_load_config_accepts_bypass_mode(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        '[policy]\nmode = "bypass"\n', encoding="utf-8"
    )
    assert load_config(tmp_path).permission_mode is PermissionMode.BYPASS


def test_configuration_service_persists_bypass_mode(tmp_path: Path) -> None:
    updated = ConfigurationService(tmp_path).set_value("mode", "bypass")
    assert updated.permission_mode is PermissionMode.BYPASS
    assert 'mode = "bypass"' in (tmp_path / "harness.toml").read_text(encoding="utf-8")


def test_run_bypass_mode_survives_sqlite_round_trip(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "state.db")
    run = Run(task="unattended", permission_mode=PermissionMode.BYPASS)
    store.create_run(run)
    assert store.get_run(run.id) == run


def test_root_parser_accepts_bypass_and_dangerous_alias(tmp_path: Path) -> None:
    canonical = parse_root_args(
        ["--repo", str(tmp_path), "--permission-mode", "bypass", "run"]
    )
    alias = parse_root_args(
        ["--repo", str(tmp_path), "--dangerously-skip-permissions", "run"]
    )
    assert canonical.permission_mode is PermissionMode.BYPASS
    assert alias.permission_mode is PermissionMode.BYPASS


def test_root_parser_rejects_conflicting_dangerous_mode(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse_root_args([
            "--repo", str(tmp_path),
            "--permission-mode", "strict",
            "--dangerously-skip-permissions",
            "run",
        ])
```

Extend entrypoint dispatch coverage to assert the alias reaches `TuiLaunchRequest.permission_mode`
as `PermissionMode.BYPASS`.

Extend the terminal-output contract:

```python
def test_run_envelope_and_serializers_report_bypass_mode() -> None:
    envelope = RunEnvelope(
        session_id=uuid4(),
        run_id=uuid4(),
        status=RunState.COMPLETED,
        permission_mode=PermissionMode.BYPASS,
    )
    assert '"permission_mode":"bypass"' in JsonOutputSerializer().render(envelope)
    assert "permission_mode=bypass" in TextOutputSerializer().render(envelope)
```

In the print parity test, assert the terminal stream event has
`event["data"]["permission_mode"] == "bypass"` when the dangerous alias is selected.

- [ ] **Step 2: Run the focused tests and capture RED**

```bash
UV_CACHE_DIR=/tmp/coding613-uv-cache uv run pytest \
  tests/domain/test_models.py tests/config/test_config.py \
  tests/application/test_configuration.py tests/adapters/storage/test_sqlite.py \
  tests/cli/test_prompt.py tests/cli/test_entrypoint.py \
  tests/cli/test_output.py tests/cli/test_parity_contract.py -q
```

Expected: missing `PermissionMode.BYPASS`, rejected `bypass` config/CLI input, and unknown dangerous flag.

- [ ] **Step 3: Add the enum and deterministic CLI mapping**

```python
class PermissionMode(StrEnum):
    STRICT = "strict"
    BALANCED = "balanced"
    AUTONOMOUS = "autonomous"
    BYPASS = "bypass"
```

In `_parser()` add:

```python
parser.add_argument(
    "--dangerously-skip-permissions",
    action="store_true",
    help="Skip approval prompts; deterministic denials and sandbox limits remain active",
)
```

In `parse_root_args`, before creating `RootLaunchRequest`, resolve the single effective value:

```python
if (
    namespace.dangerously_skip_permissions
    and namespace.permission_mode not in {None, PermissionMode.BYPASS.value}
):
    parser.error(
        "--dangerously-skip-permissions conflicts with a non-bypass --permission-mode"
    )
permission_mode_value = (
    PermissionMode.BYPASS.value
    if namespace.dangerously_skip_permissions
    else namespace.permission_mode
)
```

Use `permission_mode_value` in the existing enum construction. Do not add a SQLite migration; the
column is text and must round-trip through existing Pydantic reconstruction.

Add `permission_mode: PermissionMode = PermissionMode.BALANCED` to `RunEnvelope`, accept it in
`RunEnvelope.from_summary`, pass `run.permission_mode` from `run_print`, and include the canonical
value in the terminal stream event data. Update `TextOutputSerializer` to append
`permission_mode=<value>` to its status line. JSON serialization then includes the enum field through
the existing Pydantic serializer without a separate branch.

- [ ] **Step 4: Run focused tests and refactor while green**

Repeat Step 2. Expected: all selected tests pass and root `--help` lists the dangerous flag.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/coding613/domain/models.py src/coding613/domain/session_events.py \
  src/coding613/application/events.py src/coding613/cli/prompt.py \
  tests/domain/test_models.py tests/config/test_config.py \
  tests/application/test_configuration.py tests/adapters/storage/test_sqlite.py \
  tests/cli/test_prompt.py tests/cli/test_entrypoint.py \
  tests/cli/test_output.py tests/cli/test_parity_contract.py
git commit -m "feat: add bypass permission selection"
```

Record the RED/GREEN commands and commit hash in `AGENT_LOG.md`; mark Task 1 in `PLAN.md` only after
the focused command passes.

---

### Task 2: Central ASK-to-ALLOW policy conversion and AgentLoop execution

**Files:**
- Modify: `src/coding613/application/policy.py`
- Modify: `tests/application/test_policy.py`
- Modify: `tests/application/test_loop.py`
- Modify: `tests/application/test_permission_filters.py`
- Modify: `tests/sandbox/test_security_policy.py`

**Interfaces:**
- Consumes: `PolicyEngine.evaluate(call, config, mode) -> PolicyDecision`, `PolicyEffect`, `LoopDependencies.permission_mode`, and the existing approval service.
- Produces: `PolicyEngine._apply_permission_mode(decision, mode) -> PolicyDecision`; bypass decisions retain `mode.bypass.*` rule IDs and allowed actions create no approvals.

- [ ] **Step 1: Write failing policy matrix tests**

```python
@pytest.mark.parametrize(
    "call",
    [
        ToolCall(name="run_command", arguments={"argv": ["python", "-V"]}),
        ToolCall(name="run_shell", arguments={"commands": [
            {"argv": ["python", "-V"]},
            {"argv": ["git", "status"]},
        ]}),
        ToolCall(name="network_request", arguments={"url": "https://example.invalid"}),
        ToolCall(name="install_dependency", arguments={"name": "example"}),
        ToolCall(name="git_commit", arguments={"message": "checkpoint"}),
    ],
)
def test_bypass_allows_every_soft_approval(
    call: ToolCall, config: RepositoryPolicyConfig
) -> None:
    restricted = config.model_copy(update={
        "allow_network": False,
        "allow_dependency_install": False,
        "allow_git_writes": False,
    })
    decision = PolicyEngine().evaluate(call, restricted, PermissionMode.BYPASS)
    assert decision.effect is PolicyEffect.ALLOW
    assert decision.rule_id.startswith("mode.bypass.")
```

Add hard/config/rule denial tests:

```python
@pytest.mark.parametrize("call", [
    ToolCall(name="read_file", arguments={"path": "../secret"}),
    ToolCall(name="run_command", arguments={"argv": ["sudo", "id"]}),
    ToolCall(name="run_shell", arguments={"commands": [
        {"argv": ["python", "-V"]}, {"argv": ["mkfs", "/dev/x"]}
    ]}),
])
def test_bypass_does_not_override_hard_denials(
    call: ToolCall, config: RepositoryPolicyConfig
) -> None:
    assert PolicyEngine().evaluate(
        call, config, PermissionMode.BYPASS
    ).effect is PolicyEffect.DENY


def test_bypass_preserves_repository_denials(config: RepositoryPolicyConfig) -> None:
    no_writes = config.model_copy(update={"allow_writes": False})
    write = ToolCall(name="edit_file", arguments={"path": "a.py", "content": "x"})
    assert PolicyEngine().evaluate(
        write, no_writes, PermissionMode.BYPASS
    ).effect is PolicyEffect.DENY

    denied = config.model_copy(update={"permission_rules": (
        PermissionRule(scope="tool", pattern="run_command", effect="deny"),
    )})
    command = ToolCall(name="run_command", arguments={"argv": ["python", "-V"]})
    assert PolicyEngine().evaluate(
        command, denied, PermissionMode.BYPASS
    ).effect is PolicyEffect.DENY
```

Add the invocation-filter regression:

```python
def test_bypass_cannot_override_invocation_disallow(tmp_path: Path) -> None:
    call = ToolCall(name="run_command", arguments={"argv": ["python", "-V"]})
    allowed = PolicyEngine().evaluate(
        call, RepositoryPolicyConfig(repository_root=tmp_path), PermissionMode.BYPASS
    )
    filtered = ToolFilter(disallowed=frozenset({"run_command"})).apply(call, allowed)
    assert filtered.effect is PolicyEffect.DENY
    assert filtered.rule_id == "invocation.tool_disallowed"
```

In every sandbox hard-constraint parametrization that currently uses `AUTONOMOUS`, add or replace a
case with `PermissionMode.BYPASS` and retain the exact expected `hard.*` rule IDs for root workers,
unapproved network, credentials, capabilities, and excessive resources.

- [ ] **Step 2: Write a failing AgentLoop approval test**

Register a fake `run_command` definition in `tests/application/test_loop.py`, script an undeclared
command followed by `finish`, and assert:

```python
summary = AgentLoop().run(run_id, "run local command", deps)

assert summary.status is RunState.COMPLETED
assert summary.approvals == ()
assert [call.name for call in executor.calls] == ["run_command"]
assert records.list_approvals(run_id) == []
assert any(
    record.policy_decision is not None
    and record.policy_decision.rule_id == "mode.bypass.command"
    and record.policy_decision.effect == "allow"
    for record in records.iterations
)
```

Construct `deps` with `PermissionMode.BYPASS` and an empty `validation_commands` tuple. Keep the
existing strict approval test unchanged to prove old-mode isolation.

Extend the existing approval-restart fixture with a default-mode change and assert the stored run
remains authoritative:

```python
request_id = first.resume(run.id).approvals[-1]
assert store.get_run(run.id).permission_mode is PermissionMode.STRICT

# Reconstruct services with BYPASS as the default only for new runs.
resumed = second.resume(run.id)
assert resumed.status is RunState.WAITING_APPROVAL
assert resumed.approvals == (request_id,)
assert store.get_approval(request_id).status is ApprovalStatus.PENDING
```

The second dependency factory must continue to use `run.permission_mode`, as production composition
does; do not substitute the new default into an existing run.

- [ ] **Step 3: Run policy/loop tests and capture RED**

```bash
UV_CACHE_DIR=/tmp/coding613-uv-cache uv run pytest \
  tests/application/test_policy.py tests/application/test_permission_filters.py \
  tests/sandbox/test_security_policy.py tests/application/test_loop.py -q
```

Expected: soft actions remain `ASK` and the loop pauses in `WAITING_APPROVAL`.

- [ ] **Step 4: Implement one central permission-mode finalizer**

```python
@staticmethod
def _apply_permission_mode(
    decision: PolicyDecision, mode: PermissionMode
) -> PolicyDecision:
    if mode is PermissionMode.BYPASS and decision.effect is PolicyEffect.ASK:
        return decision.model_copy(update={"effect": PolicyEffect.ALLOW})
    return decision
```

Keep every existing early deterministic denial. In `PolicyEngine.evaluate`, let explicit deny remain
an early return, let explicit allow resolve an `ASK`, and pass the final non-denied decision through
`_apply_permission_mode`. Do not special-case each category: existing category rule IDs already
interpolate `mode.value` and therefore produce `mode.bypass.command`, `.command_batch`, `.network`,
`.dependency_install`, and `.git_write`.

- [ ] **Step 5: Run focused tests and refactor while green**

Repeat Step 3. Expected: bypass actions run without approval; strict still pauses; hard, config,
filter, and sandbox denials remain `DENY`.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/coding613/application/policy.py \
  tests/application/test_policy.py tests/application/test_loop.py \
  tests/application/test_permission_filters.py tests/sandbox/test_security_policy.py
git commit -m "feat: bypass soft permission prompts"
```

Record the RED/GREEN evidence, denial matrix, and commit hash in `AGENT_LOG.md` and `PLAN.md`.

---

### Task 3: TUI selection and conspicuous dangerous-mode status

**Files:**
- Modify: `src/coding613/tui/commands.py`
- Modify: `src/coding613/tui/app.py`
- Modify: `src/coding613/application/configuration.py`
- Modify: `tests/tui/test_commands.py`
- Modify: `tests/tui/test_app.py`
- Modify: `tests/application/test_configuration.py`

**Interfaces:**
- Consumes: `PermissionMode.BYPASS`, `SlashCommand.parse`, `CodingApp.permission_mode`, and `ConfigurationService.summary()`.
- Produces: `/permissions bypass`, config-menu action `mode:bypass`, and warning label `DANGEROUS: BYPASS` in footer, `/status`, permission listing, and configuration summary.

- [ ] **Step 1: Write failing command and configuration-summary tests**

Extend the slash-parser table:

```python
("/permissions bypass", "permissions", ("bypass",)),
```

Add:

```python
def test_configuration_summary_warns_when_bypass_is_persisted(tmp_path: Path) -> None:
    (tmp_path / "harness.toml").write_text(
        '[policy]\nmode = "bypass"\n', encoding="utf-8"
    )
    summary = ConfigurationService(tmp_path).summary()
    assert "mode=bypass" in summary
    assert "DANGEROUS: BYPASS" in summary
```

- [ ] **Step 2: Write failing Textual tests**

```python
@pytest.mark.asyncio
async def test_tui_bypass_mode_is_selectable_and_visibly_dangerous() -> None:
    fake = FakeUiServices()
    app = CodingApp(controller=_controller(fake))
    async with app.run_test(size=(100, 28)) as pilot:
        app.query_one(TaskComposer).load_text("/permissions bypass")
        await pilot.press("enter")
        await pilot.pause()
        assert app.permission_mode is PermissionMode.BYPASS
        assert "DANGEROUS: BYPASS" in str(app.query_one(StatusFooter).renderable)
```

Add a config-menu test that opens `/config` and asserts exactly one option has prompt
`Permission mode: bypass` and id `mode:bypass`:

```python
menu = app.query_one(ConfigMenu)
matching = [option for option in menu.options if option.id == "mode:bypass"]
assert len(matching) == 1
assert str(matching[0].prompt) == "Permission mode: bypass"
```

Add a `/status` test:

```python
app.permission_mode = PermissionMode.BYPASS
app.query_one(TaskComposer).load_text("/status")
await pilot.press("enter")
await pilot.pause()
texts = [str(item.renderable) for item in app.query(Static)]
assert any("mode=DANGEROUS: BYPASS" in text for text in texts)
assert any("approval=" in text for text in texts)
```

- [ ] **Step 3: Run focused TUI/config tests and capture RED**

```bash
UV_CACHE_DIR=/tmp/coding613-uv-cache uv run pytest \
  tests/tui/test_commands.py tests/tui/test_app.py \
  tests/application/test_configuration.py -q
```

Expected: the parser rejects `bypass`, the menu omits it, and status surfaces lack the warning.

- [ ] **Step 4: Implement selection and warning rendering**

Add `bypass` to `_permission_arguments`, the permission handler, and the config menu:

```python
if arguments[0] in {"strict", "balanced", "autonomous", "bypass", "list"}:
    ...

("Permission mode: bypass", "mode:bypass"),
```

Use one display-only helper in `tui/app.py`:

```python
def _permission_mode_display(mode: PermissionMode) -> str:
    return "DANGEROUS: BYPASS" if mode is PermissionMode.BYPASS else mode.value
```

Use it in `_update_footer`, `/status`, and `/permissions list`; stored and JSON values remain the
canonical string `bypass`. In `ConfigurationService.summary`, retain the machine-readable value and
append the warning:

```python
mode_line = f"mode={config.permission_mode.value}"
if config.permission_mode is PermissionMode.BYPASS:
    mode_line += " (DANGEROUS: BYPASS)"
```

- [ ] **Step 5: Run focused tests and refactor while green**

Repeat Step 3. Expected: all selected tests pass without changing existing menu navigation or
completion behavior.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/coding613/tui/commands.py src/coding613/tui/app.py \
  src/coding613/application/configuration.py tests/tui/test_commands.py \
  tests/tui/test_app.py tests/application/test_configuration.py
git commit -m "feat: expose dangerous bypass mode in tui"
```

Record focused TUI evidence and the commit hash in `AGENT_LOG.md` and `PLAN.md`.

---

### Task 4: Specification, README, offline demo, and documentation contract

**Files:**
- Modify: `SPEC.md`
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Modify: `src/coding613/demo/core_feedback.py`
- Modify: `tests/demo/test_core_feedback.py`
- Modify: `tests/test_docs.py`

**Interfaces:**
- Consumes: `PermissionMode.BYPASS`, `PolicyEngine.evaluate`, and `CoreFeedbackDemoResult`.
- Produces: `CoreFeedbackDemoResult.bypass_command_allowed: bool` and current documentation for four modes and both CLI selectors.

- [ ] **Step 1: Write failing demo and documentation-contract tests**

Extend the demo assertion:

```python
result = run_core_feedback_demo(tmp_path)
assert result.bypass_command_allowed is True
assert result.guardrail_blocked is True
```

Add:

```python
def test_current_docs_define_dangerous_bypass_boundary() -> None:
    text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "SPEC.md", "docs/deployment.md")
    )
    for marker in (
        "--permission-mode bypass",
        "--dangerously-skip-permissions",
        "DANGEROUS: BYPASS",
        "ASK",
        "DENY",
        "argv",
        "sandbox",
    ):
        assert marker.lower() in text.lower()
```

- [ ] **Step 2: Run demo/docs tests and capture RED**

```bash
UV_CACHE_DIR=/tmp/coding613-uv-cache uv run pytest \
  tests/demo/test_core_feedback.py tests/test_docs.py -q
```

Expected: the result lacks `bypass_command_allowed` and current docs omit required markers.

- [ ] **Step 3: Extend the deterministic policy demo**

```python
class CoreFeedbackDemoResult(DomainModel):
    summary: RunSummary
    feedback_observed: bool
    guardrail_blocked: bool
    bypass_command_allowed: bool
    memory_retrieved: bool
    changed_file_text: str
```

Evaluate the bypass command without starting an external process:

```python
bypass_command = policy.evaluate(
    ToolCall(name="run_command", arguments={"argv": ["python", "-V"]}),
    policy_config,
    PermissionMode.BYPASS,
)
```

Return `bypass_command_allowed=bypass_command.effect is PolicyEffect.ALLOW`. Keep the existing
repository-escape guardrail so the same demo proves bypass and hard denial together.

- [ ] **Step 4: Update current specifications and operator warnings**

- `SPEC.md`: list four modes; define bypass as `ASK -> ALLOW` with `DENY` unchanged; add bypass to
  deterministic permission-mode demo requirements.
- `README.md`: document `--permission-mode bypass`, `--dangerously-skip-permissions`,
  `/permissions bypass`, `/config set mode bypass`, and `DANGEROUS: BYPASS`.
- `docs/deployment.md`: state that bypass removes human review and should only run inside the
  configured short-lived container/workspace; hard denials and sandbox limits remain active.

Do not rewrite historical specs. The approved 2026-08-13 design is the superseding record.

- [ ] **Step 5: Run demo/docs tests and refactor while green**

Repeat Step 2. Expected: all selected tests pass and the demo stays offline and deterministic.

- [ ] **Step 6: Commit Task 4**

```bash
git add SPEC.md README.md docs/deployment.md \
  src/coding613/demo/core_feedback.py tests/demo/test_core_feedback.py tests/test_docs.py
git commit -m "docs: document dangerous bypass boundary"
```

Record demo evidence and the commit hash in `AGENT_LOG.md` and `PLAN.md`.

---

### Task 5: Full verification, two-stage review, and delivery evidence

**Files:**
- Modify: `AGENT_LOG.md`
- Modify: `PLAN.md`
- Modify: `DELIVERY_STATUS.md`
- Modify only if review finds a defect: Task 1-4 files and focused tests

**Interfaces:**
- Consumes: Task 1-4 commits and verification output.
- Produces: traceable completion evidence, spec-compliance review, code-quality review, and final branch handoff.

- [ ] **Step 1: Run the complete focused bypass suite**

```bash
UV_CACHE_DIR=/tmp/coding613-uv-cache uv run pytest \
  tests/domain/test_models.py tests/config/test_config.py \
  tests/application/test_configuration.py tests/application/test_policy.py \
  tests/application/test_permission_filters.py tests/application/test_loop.py \
  tests/sandbox/test_security_policy.py tests/adapters/storage/test_sqlite.py \
  tests/cli/test_prompt.py tests/cli/test_entrypoint.py tests/cli/test_output.py \
  tests/cli/test_parity_contract.py \
  tests/tui/test_commands.py tests/tui/test_app.py \
  tests/demo/test_core_feedback.py tests/test_docs.py -q
```

Expected: all selected tests pass. Record the exact count and warnings.

- [ ] **Step 2: Run maintained offline and static verification**

```bash
UV_CACHE_DIR=/tmp/coding613-uv-cache uv run pytest tests -q
UV_CACHE_DIR=/tmp/coding613-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/coding613-uv-cache uv run mypy src
UV_CACHE_DIR=/tmp/coding613-uv-cache uv lock --check
git diff --check
```

Expected: each command passes. If the known LanceDB hang or untracked nested-project boundary
recurs, isolate and record it with focused green evidence; do not claim the full suite passed.

- [ ] **Step 3: Perform spec-compliance review**

Use `requesting-code-review` with the approved design, this plan, Task 1-4 commit hashes, and test
output. Require checks that every approval-eligible action is automatic in bypass; no `DENY` is
converted; no approval or `WAITING_APPROVAL` is created; old modes and pending approvals are stable;
all selection surfaces exist; and shell remains argv-only and sandboxed. Fix every Critical or
Important finding with a new RED regression and rerun the focused suite.

- [ ] **Step 4: Perform code-quality review**

After spec compliance passes, request a separate quality review covering duplicated mode logic,
policy return paths, rule IDs, parser conflicts, warning consistency, typing, test isolation, and
unrelated worktree changes. Resolve every Critical finding and document lower-severity decisions.

- [ ] **Step 5: Update delivery evidence**

Append an Asia/Shanghai entry to `AGENT_LOG.md` with the approved 方案 A, skills/subagents, RED/GREEN
commands, commit hashes, review findings, verification limits, and confirmation that no credentials
or real LLM were used. Update `PLAN.md` with each task's status, exact verification, and commit.
Update `DELIVERY_STATUS.md` with behavior, warning, timestamp, responsible actor, and design/plan links.

- [ ] **Step 6: Commit delivery records**

```bash
git add AGENT_LOG.md PLAN.md DELIVERY_STATUS.md SPEC_PROCESS.md
git commit -m "docs: record bypass permission delivery"
```

If these files contain unrelated edits that cannot be staged safely, do not bundle them. Record the
constraint and leave the exact changes visible for the user.

- [ ] **Step 7: Finish the development branch**

Invoke `finishing-a-development-branch`, present its integration choices, and do not push or open a
PR unless the user selects that outcome. Never reset or overwrite the original dirty worktree.
