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

Configure a real OpenAI-compatible provider with metadata only:

```toml
[llm]
provider = "openai-compatible"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
credential = "openai"
timeout_seconds = 60.0
```

Then run `coding-harness credentials set openai`. The provider reads the key lazily from the OS keyring on its first call and keeps it only in the ephemeral HTTP client. The local composition registers bounded file/search/diff tools and executes only validation commands declared in `harness.toml`. Missing credentials remain a controlled provider error; no key is written to repository configuration, SQLite, LanceDB, events, prompts, subprocess arguments, or container environments.

## Runtime Boundary

The public WebUI calls only the API and must be limited to an example repository or isolated upload. It must never accept an arbitrary host path. Worker execution uses short-lived non-root containers with read-only roots, dropped capabilities, default-deny network, finite CPU/memory/PID/disk/time/output limits, and no Docker socket mount. The Docker adapter passes the disk bound through `storage_opt`; the host Docker storage driver must support project quotas, otherwise container creation fails and its workspace is cleaned up. These controls reduce ordinary untrusted-code impact but do not guarantee protection from kernel or runtime vulnerabilities.

SQLite is the source of truth for runs, events, approvals, task graphs, memory text, and audit state. LanceDB stores redacted vectors linked to SQLite IDs and can be rebuilt. If embeddings fail, SQLite keyword retrieval remains available.

## GitLab CI/CD

`.gitlab-ci.yml` defines `unit-test`, `lint`, `typecheck`, `demo`, `build`, and `docker-build` stages. `.github/workflows/ci.yml` provides equivalent push/PR checks when the repository is hosted on GitHub. Jobs use locked `uv` dependencies, run tests/demos, build the package, and build the Docker image. `scripts.record_delivery` validates a Git commit and appends command/result evidence without converting failures into passes.

## Limitations And Evidence

The Docker Engine is an operator prerequisite for real worker containers. The current environment has a Docker daemon, but the latest Docker build could not retrieve the Docker Hub OAuth token because the network connection reset; no image pull or container smoke pass is claimed. `render.yaml` is an operator-controlled deployment declaration, not evidence of a deployed service. No unverified deployment claim is made. A deployed URL: not verified.

## Directory Layout

`src/coding_harness/domain` contains infrastructure-free value objects; `application` owns the loop, RunService, Supervisor, policy, feedback, and integration; `adapters` contain SQLite/LanceDB, keyring, Docker, filesystem, CLI, API, and WebUI boundaries. `tests/` mirrors those contracts and all tests run without a real LLM.
