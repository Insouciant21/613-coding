# 613 Coding

613 Coding is a local Python coding-agent harness with an objective feedback loop, SQLite source of truth, LanceDB retrieval index, Docker worker sandbox, and Supervisor orchestration.

## Operations Console

The FastAPI app serves the operations console at `/`. It submits tasks through the run API and displays Supervisor/worker state, ordered events, approvals, changed files, validation evidence, and terminal stop reasons. The browser never receives provider credentials.

Run the offline test suite with:

```bash
uv sync
uv run pytest
```

The API adapter is created with `coding_harness.api.create_app(services)`; deployment and package entrypoints are documented as the distribution work lands.
