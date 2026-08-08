# 613 Coding

613 Coding is a local Python coding-agent harness with an objective feedback loop, SQLite source of truth, LanceDB retrieval index, Docker worker sandbox, and Supervisor orchestration.

## Operations Console

The FastAPI app serves the operations console at `/`. It submits tasks through the run API and displays Supervisor/worker state, ordered events, approvals, changed files, validation evidence, and terminal stop reasons. The browser never receives provider credentials.

Run the offline test suite with:

```bash
uv sync
uv run pytest
```

Build and install the package with `uv build` and `uv tool install .`. The installed command exposes `coding-harness config check`, `coding-harness credentials status`, `coding-harness run task`, and `coding-harness web`.

The API adapter is created with `coding_harness.api.create_app(services)`. Deployment, keyring safety, `.env` limitations, Docker boundaries, and CI stages are documented in [`docs/deployment.md`](docs/deployment.md).

The public console boundary is intentionally narrow: it may operate an example repository or an isolated upload, never an arbitrary host path. SQLite remains authoritative for structured state and memory text; LanceDB is rebuildable retrieval metadata.
