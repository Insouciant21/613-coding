# Deployment And Operations

## Acquisition

Use Python 3.12+ managed by `uv`:

```bash
uv sync --all-extras
uv run pytest
uv build
uv tool install .
coding-harness web --host 127.0.0.1 --port 8000
```

The Docker demonstration uses `docker build -t 613-coding .` and `docker run --rm -p 8000:8000 613-coding`. The image starts the local FastAPI console and exposes `/healthz`. CLI/API adapters use the local SQLite/LanceDB composition by default; resuming a run requires an injected real `LLMProvider`, and provider/policy composition stays outside presentation code.

## Credentials And Configuration

`coding-harness credentials set PROVIDER` reads the key with hidden terminal input and stores it in the operating-system keyring. Status output contains only provider, configured state, and source metadata. `credentials clear` removes the entry.

`.env` is an explicit development fallback only. It is ignored by Git and Docker, remains plaintext, and can leak through process environments. Never put a provider key in `harness.toml`, SQLite, LanceDB, prompts, event payloads, CI files, or worker containers.

## Runtime Boundary

The public WebUI calls only the API and must be limited to an example repository or isolated upload. It must never accept an arbitrary host path. Worker execution uses short-lived non-root containers with read-only roots, dropped capabilities, default-deny network, finite CPU/memory/PID/disk/time/output limits, and no Docker socket mount. The Docker adapter passes the disk bound through `storage_opt`; the host Docker storage driver must support project quotas, otherwise container creation fails and its workspace is cleaned up. These controls reduce ordinary untrusted-code impact but do not guarantee protection from kernel or runtime vulnerabilities.

SQLite is the source of truth for runs, events, approvals, task graphs, memory text, and audit state. LanceDB stores redacted vectors linked to SQLite IDs and can be rebuilt. If embeddings fail, SQLite keyword retrieval remains available.

## GitLab CI/CD

`.gitlab-ci.yml` defines `unit-test`, `lint`, `typecheck`, `demo`, and `build` stages. Jobs use locked `uv` dependencies, run offline tests/demos, and publish `dist/` as the build artifact. `scripts.record_delivery` validates a Git commit and appends command/result evidence without converting failures into passes.

## Limitations And Evidence

The Docker Engine is an operator prerequisite for real worker containers. The current environment has a Docker daemon, but the DELIVERY-05 build could not retrieve the Docker Hub token because the network connection reset; no image pull or container smoke pass is claimed. No unverified deployment claim is made. A deployed URL: not verified.

## Directory Layout

`src/coding_harness/domain` contains infrastructure-free value objects; `application` owns the loop, RunService, Supervisor, policy, feedback, and integration; `adapters` contain SQLite/LanceDB, keyring, Docker, filesystem, CLI, API, and WebUI boundaries. `tests/` mirrors those contracts and all tests run without a real LLM.
