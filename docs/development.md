# Development Bootstrap

613 Coding uses `uv` for dependency management. Python source can be checked
before third-party dependencies are installed with:

```bash
PYTHONPATH=src python3 -m unittest tests.test_package.PackageTests.test_package_exposes_version
```

For an online environment, provision the locked development environment with:

```bash
uv sync --all-extras --frozen
```

For an air-gapped environment, provide a populated `uv` cache or wheelhouse,
then run:

```bash
uv sync --all-extras --frozen --offline
```

Run `python3 scripts/bootstrap_dev.py` to verify provisioning. If it reports
`DEPENDENCY_PROVISIONING_BLOCKED`, install dependencies using one of the
commands above before running the canonical checks:

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```
