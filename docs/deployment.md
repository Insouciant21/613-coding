# Deployment And Operations

## Acquisition

Use Python 3.12+ managed by `uv`:

```bash
uv sync --all-extras
uv run pytest
uv build
uv tool install .
613-coding web --host 127.0.0.1 --port 8000
```

The Docker demonstration uses `docker build -t 613-coding .` and `docker run --rm -p 8000:8000 613-coding`. The image starts the local FastAPI console and exposes `/healthz`. CLI/API adapters use the local SQLite/LanceDB composition by default; resuming a run requires an injected real `LLMProvider`, and provider/policy composition stays outside presentation code.

## Credentials And Configuration

`613-coding credentials set PROVIDER` reads the key with hidden terminal input and stores it in the operating-system keyring. Status output contains only provider, configured state, and source metadata. `credentials clear` removes the entry.

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

Then run `613-coding credentials set openai`. The provider reads the key lazily from the OS keyring on its first call and keeps it only in the ephemeral HTTP client. The local composition registers bounded file/search/diff tools and executes only validation commands declared in `harness.toml`. Missing credentials remain a controlled provider error; no key is written to repository configuration, SQLite, LanceDB, events, prompts, subprocess arguments, or container environments.

## Runtime Boundary

The public WebUI calls only the API and must be limited to an example repository or isolated upload. It must never accept an arbitrary host path. Worker execution uses short-lived non-root containers with read-only roots, dropped capabilities, default-deny network, finite CPU/memory/PID/disk/time/output limits, and no Docker socket mount. The Docker adapter passes the disk bound through `storage_opt`; the host Docker storage driver must support project quotas, otherwise container creation fails and its workspace is cleaned up. These controls reduce ordinary untrusted-code impact but do not guarantee protection from kernel or runtime vulnerabilities.

SQLite is the source of truth for runs, events, approvals, task graphs, memory text, and audit state. LanceDB stores redacted vectors linked to SQLite IDs and can be rebuilt. If embeddings fail, SQLite keyword retrieval remains available.

## GitLab CI/CD

`.gitlab-ci.yml` defines `unit-test`, `lint`, `typecheck`, `demo`, `build`, and `docker-build` stages. `.github/workflows/ci.yml` provides equivalent push/PR checks when the repository is hosted on GitHub. Jobs use locked `uv` dependencies, run tests/demos, build the package, build the digest-pinned Docker image, and run `scripts/smoke_container.sh` to verify the health check, non-root `coding` user, and cleanup. `scripts.record_delivery` validates a Git commit and appends command/result evidence without converting failures into passes.

## SSH Deployment

Commit `71c281d` is deployed on `edward@int21` as image `613-coding:71c281d`. The service binds only to `127.0.0.1:8613`; an operator-managed reverse proxy should target `http://127.0.0.1:8613` and use `/healthz` for health checks. Ports 80 and 443 are intentionally untouched.

The immutable release source is under `/home/edward/services/613-coding/releases/71c281d`. Persistent SQLite and LanceDB state lives under `/home/edward/services/613-coding/data`, mounted at `/app/.613-coding`. Back up this data directory before migrations or destructive maintenance. The `613-coding` container runs as UID 10001 with a read-only root, a bounded `/tmp` tmpfs, all capabilities dropped, `no-new-privileges`, 1 GiB memory, one CPU, a 256 PID limit, and `unless-stopped` restart policy.

## Limitations And Evidence

The Docker Engine is an operator prerequisite for real worker containers. In IPv6-restricted environments, Docker Hub OAuth may reset before a build; an approved registry mirror can be used only when it resolves to the Dockerfile's pinned digest. Local verification built `613-coding:smoke-fix` and passed `scripts/smoke_container.sh` with `health=healthy` and `user=coding`. Main commit `71c281d` passed [GitHub Actions run 31296034199](https://github.com/Insouciant21/613-coding/actions/runs/31296034199), including the pinned build and smoke gate. The SSH deployment passed `/`, `/healthz`, immediate run retrieval, and retrieval of the same persisted run after container restart. `render.yaml` remains an optional operator-controlled deployment declaration. The SSH service has no verified public URL until the operator configures and validates the reverse proxy. Deployed URL: not verified; any public endpoint remains unverified.

## Directory Layout

`src/coding613/domain` contains infrastructure-free value objects; `application` owns the loop, RunService, Supervisor, policy, feedback, and integration; `adapters` contain SQLite/LanceDB, keyring, Docker, filesystem, CLI, API, and WebUI boundaries. `tests/` mirrors those contracts and all tests run without a real LLM.
