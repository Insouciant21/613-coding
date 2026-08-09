# 613 Coding Package Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy `coding-harness` distribution and command and `coding_harness` import package with the strict `613-coding` distribution/command and `coding613` import package, then redeploy the renamed image without losing persisted state.

**Architecture:** Preserve all domain and application behavior while changing only public naming, module paths, credential namespace, packaging metadata, runtime entrypoints, and current documentation. Use one mechanical import-path migration after contract tests fail, then verify the built wheel and Docker image in clean environments before replacing the remote container.

**Tech Stack:** Python 3.12+, uv/uv_build, pytest, Ruff, mypy, Typer console scripts, Keyring, Docker, GitHub Actions, SSH deployment.

## Global Constraints

- Distribution and sole console command: `613-coding`.
- Import package and source directory: `coding613` and `src/coding613`.
- Persistent state directory: `.613-coding`.
- Keyring service namespace: `613-coding`.
- Remove all legacy aliases; do not provide `coding-harness` or `coding_harness` compatibility.
- Keep version `0.1.0` and preserve database schemas, API paths, domain formats, and application behavior.
- Manage Python and the lock file only through `uv`.
- Preserve the user-owned untracked `.claude/` and course requirement documents.
- Preserve the remote bind `127.0.0.1:8613`, data mount, security settings, resource limits, and reverse-proxy boundary.

---

## File Structure

- Rename: `src/coding_harness/` -> `src/coding613/` without internal structural changes.
- Modify: `pyproject.toml` for distribution and the sole console entrypoint.
- Modify: `uv.lock` only through `uv lock`.
- Modify: every tracked production/test import and string monkeypatch target from `coding_harness` to `coding613`.
- Modify: `src/coding613/adapters/credentials/keyring.py` for the Keyring service namespace.
- Modify: `docker/entrypoint.sh` for the renamed executable.
- Modify: `README.md`, `docs/deployment.md`, and `AGENTS.md` for current commands and source paths.
- Modify: `tests/test_distribution.py`, `tests/test_package.py`, `tests/adapters/credentials/test_keyring.py`, and `tests/test_docs.py` for the naming contract.
- Modify: `AGENT_LOG.md`, `PLAN.md`, and `DELIVERY_STATUS.md` for implementation, CI, and deployment evidence.

### Task 1: Rename Distribution, Import Package, And Console Script

**Files:**
- Rename: `src/coding_harness/` -> `src/coding613/`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: all `src/coding613/**/*.py` imports
- Modify: all `tests/**/*.py` imports and string monkeypatch targets
- Test: `tests/test_distribution.py`
- Test: `tests/test_package.py`

**Interfaces:**
- Consumes: existing `coding_harness.cli.entrypoint:main` and `__version__ = "0.1.0"` behavior.
- Produces: distribution `613-coding`, sole script `613-coding = "coding613.cli.entrypoint:main"`, and importable `coding613` package.

- [ ] **Step 1: Write failing naming-contract tests**

Replace the metadata assertions in `tests/test_distribution.py` and the package import in `tests/test_package.py` with:

```python
import importlib.util


def test_package_declares_only_613_coding_console_entrypoint() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "613-coding"
    assert data["project"]["scripts"] == {
        "613-coding": "coding613.cli.entrypoint:main",
    }


def test_only_coding613_import_package_is_available() -> None:
    assert importlib.util.find_spec("coding613") is not None
    assert importlib.util.find_spec("coding_harness") is None
```

```python
class PackageTests(unittest.TestCase):
    def test_package_exposes_version(self) -> None:
        import coding613

        self.assertTrue(coding613.__version__)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
uv run pytest tests/test_distribution.py::test_package_declares_only_613_coding_console_entrypoint tests/test_distribution.py::test_only_coding613_import_package_is_available tests/test_package.py -q
```

Expected: assertions fail because `pyproject.toml` still declares `coding-harness`, `coding613` is absent, and `coding_harness` remains importable.

- [ ] **Step 3: Perform the minimal source/import migration**

Move the package directory once, then apply the exact identifier replacement only to tracked Python source and tests:

```bash
mv src/coding_harness src/coding613
perl -pi -e 's/coding_harness/coding613/g' $(rg -l 'coding_harness' src/coding613 tests)
```

Change the `[project]` fields in `pyproject.toml` to:

```toml
name = "613-coding"
scripts = { 613-coding = "coding613.cli.entrypoint:main" }
```

Regenerate lock metadata:

```bash
uv lock
```

- [ ] **Step 4: Run focused and import-residue checks**

Run:

```bash
uv run pytest tests/test_distribution.py tests/test_package.py -q
rg -n 'coding_harness' src tests pyproject.toml uv.lock
```

Expected: tests pass and `rg` exits 1 with no legacy import/package references.

- [ ] **Step 5: Commit the core rename**

```bash
git add pyproject.toml uv.lock src tests
git commit -m "refactor: rename python package to coding613"
```

### Task 2: Rename Credential And Container Runtime Surfaces

**Files:**
- Modify: `tests/adapters/credentials/test_keyring.py`
- Modify: `tests/test_distribution.py`
- Modify: `src/coding613/adapters/credentials/keyring.py`
- Modify: `docker/entrypoint.sh`

**Interfaces:**
- Consumes: `KeyringCredentialStore(service_name: str = ...)` and the Docker image's shell entrypoint.
- Produces: default Keyring namespace `613-coding` and container command `613-coding web` with no legacy executable fallback.

- [ ] **Step 1: Write failing runtime-name tests**

Change the Keyring assertion and strengthen the entrypoint test:

```python
assert fake.values["613-coding", "openai"] == "sk-super-secret-123"
```

```python
def test_entrypoint_exposes_renamed_web_command() -> None:
    script = (ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    assert 'exec 613-coding web --host' in script
    assert "coding-harness" not in script
    assert "0.0.0.0" in script
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
uv run pytest tests/adapters/credentials/test_keyring.py::test_set_uses_hidden_keyring_input_and_status_is_redacted tests/test_distribution.py::test_entrypoint_exposes_renamed_web_command -q
```

Expected: both fail because the old Keyring service and executable remain.

- [ ] **Step 3: Apply the runtime rename**

Set the Keyring default in `src/coding613/adapters/credentials/keyring.py`:

```python
service_name: str = "613-coding",
```

Change `docker/entrypoint.sh` to:

```sh
# 613-coding web delegates to uvicorn with the isolated app factory.
exec 613-coding web --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
```

- [ ] **Step 4: Run focused runtime tests**

```bash
uv run pytest tests/adapters/credentials/test_keyring.py tests/test_distribution.py tests/test_container_smoke_script.py -q
```

Expected: all focused tests pass.

- [ ] **Step 5: Commit runtime surfaces**

```bash
git add src/coding613/adapters/credentials/keyring.py docker/entrypoint.sh tests/adapters/credentials/test_keyring.py tests/test_distribution.py
git commit -m "refactor: rename runtime command surfaces"
```

### Task 3: Update Current Documentation And Verify Built Artifacts

**Files:**
- Modify: `tests/test_docs.py`
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Modify: `AGENTS.md`
- Modify: `AGENT_LOG.md`
- Modify: `PLAN.md`
- Modify: `DELIVERY_STATUS.md`

**Interfaces:**
- Consumes: the renamed package and command from Tasks 1-2.
- Produces: current operator guidance containing only `613-coding` and `coding613`, plus traceable local release evidence.

- [ ] **Step 1: Write failing documentation-contract test**

Add to `tests/test_docs.py`:

```python
def test_current_docs_use_613_coding_package_names() -> None:
    current = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "docs/deployment.md", "AGENTS.md")
    )
    assert "613-coding web" in current
    assert "coding613.api.create_app" in current
    assert "coding-harness" not in current
    assert "src/coding_harness" not in current
```

- [ ] **Step 2: Run documentation test and verify RED**

```bash
uv run pytest tests/test_docs.py::test_current_docs_use_613_coding_package_names -q
```

Expected: fail because current guidance contains legacy commands and import paths.

- [ ] **Step 3: Update current guidance and delivery records**

Replace current command examples with `613-coding`, import examples with `coding613`, and source layout references with `src/coding613`. Do not rewrite timestamped historical evidence merely because it truthfully records the old package at that time.

Append the observed RED/GREEN results and commits to `AGENT_LOG.md`; add the rename task status to `PLAN.md`; update the delivery table and verification timestamp in `DELIVERY_STATUS.md`.

- [ ] **Step 4: Verify docs, full source, lock, and static quality**

```bash
uv run pytest tests/test_docs.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
uv lock --check
git diff --check
```

Expected: all checks pass; the full suite count is recorded rather than predicted.

- [ ] **Step 5: Build and inspect a clean wheel installation**

```bash
release_dir=$(mktemp -d)
uv build --out-dir "$release_dir/dist"
uv venv "$release_dir/venv"
uv pip install --python "$release_dir/venv/bin/python" "$release_dir"/dist/613_coding-*.whl
"$release_dir/venv/bin/613-coding" --help
test ! -e "$release_dir/venv/bin/coding-harness"
"$release_dir/venv/bin/python" -c 'import coding613; import importlib.util; assert importlib.util.find_spec("coding_harness") is None'
```

Expected: wheel install, new command, and new import pass; no old command/import is present.

- [ ] **Step 6: Build and smoke the Docker image**

```bash
docker build --pull=false -t 613-coding:rename-smoke .
scripts/smoke_container.sh 613-coding:rename-smoke
```

Expected: image becomes healthy as user `coding`; the smoke container is removed.

- [ ] **Step 7: Commit documentation and local evidence**

```bash
git add README.md docs/deployment.md AGENTS.md AGENT_LOG.md PLAN.md DELIVERY_STATUS.md tests/test_docs.py
git commit -m "docs: publish 613 coding package commands"
```

### Task 4: Review, Publish, Redeploy, And Record Evidence

**Files:**
- Modify after evidence: `AGENT_LOG.md`
- Modify after evidence: `PLAN.md`
- Modify after evidence: `DELIVERY_STATUS.md`
- Modify after evidence: `docs/deployment.md`

**Interfaces:**
- Consumes: reviewed rename commits, passing local gates, GitHub Actions, and SSH Docker host `edward@int21`.
- Produces: published main branch, immutable remote release/image, healthy `127.0.0.1:8613` service, and post-restart proof that existing SQLite state survived.

- [ ] **Step 1: Request independent code review**

Review the full diff from the pre-rename base through the current head for legacy aliases, broken imports/resource paths, lock consistency, Keyring namespace, Docker entrypoint, and unintentional behavioral changes. Resolve all Critical/Important findings through new RED/GREEN cycles.

- [ ] **Step 2: Push the implementation branch and require CI**

```bash
git push -u origin "$(git branch --show-current)"
branch_name=$(git branch --show-current)
run_id=$(gh run list --branch "$branch_name" --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$run_id" --exit-status
```

Expected: unit-test, quality, demo, and package-and-container jobs pass.

- [ ] **Step 3: Fast-forward main and require main CI**

From the primary clean worktree, fast-forward `main` to the reviewed branch, push it, obtain the run ID for the exact head SHA, and run `gh run watch "$run_id" --exit-status`. Do not deploy before the exact main run succeeds.

- [ ] **Step 4: Transfer and build the immutable remote release**

```bash
release_sha=$(git rev-parse --short=7 HEAD)
ssh edward@int21 "mkdir -p /home/edward/services/613-coding/releases/$release_sha"
git archive HEAD | ssh edward@int21 "tar -x -C /home/edward/services/613-coding/releases/$release_sha"
ssh edward@int21 "docker build --pull -t 613-coding:$release_sha /home/edward/services/613-coding/releases/$release_sha"
```

- [ ] **Step 5: Replace the application container without changing its boundary**

Inspect the existing container first and recreate `613-coding` with the same loopback port, data bind, read-only root, tmpfs, dropped capabilities, `no-new-privileges`, supplementary group, 1 GiB memory, one CPU, 256 PIDs, and `unless-stopped` policy, changing only the image tag.

- [ ] **Step 6: Verify runtime name, health, and persisted state**

Run inside the new remote container:

```bash
ssh edward@int21 'docker exec 613-coding 613-coding --help'
ssh edward@int21 'docker exec 613-coding sh -c "! command -v coding-harness"'
```

Verify `coding-harness` is absent, `/healthz` and `/` return 200, a known pre-rename run remains readable, a new run is readable before and after `docker restart`, and container security/mount settings match the pre-deployment inspect output.

- [ ] **Step 7: Record deployment evidence and run final gates**

Record exact commit/image SHA, CI URL/jobs, remote health, persistence run IDs, and the no-public-URL boundary in all four delivery files. Run:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
uv lock --check
git diff --check
```

Commit and push the evidence, then wait for the final documentation commit's GitHub Actions run to pass before claiming completion.
