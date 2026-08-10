# OpenAI SDK LLM Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the production chat/tool-calling HTTP and SSE implementation with the official OpenAI Python SDK while preserving the owned LLM port, agent-loop semantics, credential boundaries, and offline tests.

**Architecture:** Keep `LLMProvider` and `StreamingLLMProvider` as the application boundary. `OpenAICompatibleLLM` will receive an injected SDK-shaped client, map project models to `chat.completions.create`, convert typed SDK responses/chunks back to project models, and translate SDK exceptions into the existing provider errors. `CredentialedOpenAICompatibleLLM` will lazily construct one official `OpenAI` client with `max_retries=0`, custom `base_url`, timeout, and Keyring secret. The embedding adapter remains on its existing HTTP path.

**Tech Stack:** Python 3.12+, official `openai` Python package, Pydantic project models, pytest, `uv`, existing `LLMProvider` ports, and injected fake SDK clients for offline tests.

## Global Constraints

- Use `OpenAI.chat.completions.create(...)` for chat and tool calls; do not migrate this task to the Responses API.
- Do not use the SDK's high-level agent loop, assistants, or orchestration features.
- Preserve `coding613.ports.llm.LLMProvider` and `StreamingLLMProvider`; SDK objects must not escape the adapter package.
- Keep `base_url`, `model`, credential reference, and timeout configuration compatible with existing `harness.toml` files.
- Construct the production client with `max_retries=0` so one harness model call maps to one provider request.
- Read credentials lazily once; never persist or log key material, SDK headers, or provider response bodies.
- Preserve `$id` removal from provider tool schemas without mutating `ToolDefinition.input_schema`.
- Preserve project-owned `LLMResponse`, `ToolCall`, `FinishAction`, provider error classes, cancellation, and absolute stream deadline behavior.
- Do not migrate `src/coding613/adapters/embeddings/openai_compatible.py` in this feature.
- All tests must use injected fake SDK clients; no API key, network, or real LLM is required.
- Preserve the eight pre-existing tracked user changes in `src/coding613/adapters/llm/credentialed.py`, `src/coding613/adapters/llm/openai_compatible.py`, `src/coding613/application/context.py`, `src/coding613/application/loop.py`, `src/coding613/domain/models.py`, and their tests; do not reset, overwrite, or silently drop them. The overlapping adapter/credential changes are explicitly carried forward into the SDK migration commits; unrelated context/loop/model changes remain outside the migration staging set.
- Every task uses TDD: observe the focused RED, implement the minimum GREEN behavior, rerun the focused tests, then run the relevant regression suite before committing.

---

## File Map

- Modify `pyproject.toml`: add a bounded `openai` runtime dependency.
- Modify `uv.lock`: regenerate from the declared dependency with `uv lock`.
- Modify `src/coding613/adapters/llm/openai_compatible.py`: replace direct chat HTTP/SSE transport with an injectable SDK-shaped client while retaining project response/error mapping.
- Modify `src/coding613/adapters/llm/credentialed.py`: lazily construct and cache the official `OpenAI` client and pass it to the adapter.
- Modify `src/coding613/application/composition.py`: keep provider construction injection-compatible with the new SDK client factory.
- Modify `tests/adapters/llm/test_openai_compatible.py`: replace HTTP transport fixtures with SDK response/chunk fakes and retain all existing behavior contracts.
- Modify `tests/adapters/llm/test_credentialed.py`: test lazy key lookup, SDK constructor arguments, client reuse, and secret-free failures.
- Modify `tests/application/test_composition.py`: test configured SDK provider construction and persistence redaction using a fake client factory.
- Create `tests/adapters/llm/sdk_fakes.py`: small deterministic fake SDK client, completion messages, chunks, streams, and capture records shared by focused tests.
- Modify `README.md`: state that chat calls use the official OpenAI Python SDK while compatible endpoints remain supported through `base_url`.
- Modify `AGENT_LOG.md`, `PLAN.md`, `SPEC_PROCESS.md`, and `DELIVERY_STATUS.md`: record RED/GREEN output, task commits, review results, and final verification evidence.

## Interfaces Shared Across Tasks

The adapter may use private Protocols to avoid exposing unstable SDK types outside the adapter:

```python
class ChatCompletionsClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class SDKClient(Protocol):
    chat: Any

    def close(self) -> None: ...
```

The production factory must satisfy:

```python
SDKClientFactory = Callable[[str, str, float], SDKClient]


def _default_client(api_key: str, base_url: str, timeout: float) -> SDKClient:
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0,
    )
```

`OpenAICompatibleLLM` consumes an SDK client and exposes the existing methods:

```python
def complete(
    self, context: ModelContext, tools: Sequence[ToolDefinition]
) -> LLMResponse: ...


def complete_stream(
    self,
    context: ModelContext,
    tools: Sequence[ToolDefinition],
    on_text_delta: Callable[[str], None],
    cancelled: Callable[[], bool],
) -> LLMResponse: ...
```

## Task 1: SDK Dependency, Client Injection, And Test Fixtures

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/coding613/adapters/llm/openai_compatible.py`
- Modify: `src/coding613/adapters/llm/credentialed.py`
- Create: `tests/adapters/llm/sdk_fakes.py`
- Modify: `tests/adapters/llm/test_credentialed.py`
- Modify: `tests/adapters/llm/test_openai_compatible.py`

**Interfaces:**
- Consumes: existing `LLMProvider`, `ModelContext`, `ToolDefinition`, Keyring reader, and project provider exceptions.
- Produces: an SDK-shaped injected client and `SDKClientFactory(api_key, base_url, timeout)` used by Tasks 2–4.

- [ ] **Step 1: Write failing injection and dependency-boundary tests**

Add tests that do not import `httpx` or call a network transport:

```python
def test_credentialed_factory_receives_key_url_timeout_and_zero_retry() -> None:
    calls: list[tuple[str, str, float]] = []
    fake = FakeSDKClient()

    def factory(api_key: str, base_url: str, timeout: float) -> FakeSDKClient:
        calls.append((api_key, base_url, timeout))
        return fake

    provider = CredentialedOpenAICompatibleLLM(
        provider="openai",
        base_url="https://api.example.test/v1",
        model="coding-model",
        read_secret=lambda _: "sk-test-secret",
        client_factory=factory,
        timeout_seconds=12.0,
    )

    provider.complete(ModelContext(run_id=uuid4(), task="task"), ())

    assert calls == [("sk-test-secret", "https://api.example.test/v1", 12.0)]
    assert fake.closed is False
```

Add a source-boundary test that reads only `openai_compatible.py` and asserts it does not import
`httpx` or contain a direct `"/chat/completions"` post path. Add fake SDK response classes with
attribute access matching the SDK's `choices[0].message` and iterable stream shapes.

- [ ] **Step 2: Run focused tests and record the RED**

Run:

```bash
uv run pytest tests/adapters/llm/test_credentialed.py tests/adapters/llm/test_openai_compatible.py -q
```

Expected: FAIL because the current factories require an `httpx.Client`, the adapter imports
`httpx`, and no SDK-shaped client seam exists. Record the failure count and key assertion in
`AGENT_LOG.md` only after implementation work for this task is complete; do not edit product code
to hide the RED.

- [ ] **Step 3: Add the bounded dependency and minimal SDK client seam**

Add a bounded `openai` entry to `[project].dependencies`, regenerate the lock file, and change
the constructor/factory types to accept an injected SDK client. Keep the existing public class
names and project error classes so application callers do not see SDK types. Import `OpenAI` only
for the production default factory in `credentialed.py`.

- [ ] **Step 4: Run the fixture and import checks**

Run:

```bash
uv lock --check
uv run pytest tests/adapters/llm/test_credentialed.py tests/adapters/llm/test_openai_compatible.py -q
```

Expected: dependency lock succeeds; the new fixture/seam tests collect, while response-mapping
tests may remain RED until Tasks 2–3 replace the old parser.

- [ ] **Step 5: Commit the seam**

Stage the dependency, adapter seam, and focused fixtures/tests. Because the adapter and credential
files contain overlapping user-owned reliability changes, inspect their complete diff and confirm
those changes remain present; do not stage the unrelated context/loop/model files. Confirm
`git diff --cached --name-only` excludes those unrelated paths, then commit:

```bash
git add pyproject.toml uv.lock src/coding613/adapters/llm/openai_compatible.py \
  src/coding613/adapters/llm/credentialed.py tests/adapters/llm/sdk_fakes.py \
  tests/adapters/llm/test_credentialed.py tests/adapters/llm/test_openai_compatible.py
git commit -m "refactor: inject official OpenAI SDK client"
```

## Task 2: Synchronous Chat Completion And Error Mapping

**Files:**
- Modify: `src/coding613/adapters/llm/openai_compatible.py`
- Modify: `tests/adapters/llm/sdk_fakes.py`
- Modify: `tests/adapters/llm/test_openai_compatible.py`

**Interfaces:**
- Consumes: Task 1 SDK client seam and fake completion objects.
- Produces: `complete(context, tools) -> LLMResponse` backed by `client.chat.completions.create`.

- [ ] **Step 1: Replace HTTP fixtures with failing SDK-call expectations**

Rewrite the ordinary-call tests to capture keyword arguments from
`fake.chat.completions.create` and return a fake completion:

```python
def test_complete_calls_sdk_chat_completions_and_maps_tool_call() -> None:
    client = FakeSDKClient(
        completion=FakeCompletion(
            message=FakeMessage(
                content="",
                tool_calls=(FakeToolCall("call-1", "read_file", '{"path":"a.py"}'),),
            )
        )
    )
    provider = OpenAICompatibleLLM("https://provider.invalid/v1", "test-model", client)

    response = provider.complete(
        ModelContext(run_id=uuid4(), task="read a.py"),
        (ToolDefinition(name="read_file", description="Read", input_schema={"$id": "local", "type": "object"}),),
    )

    assert client.chat.completions.calls[0]["model"] == "test-model"
    assert client.chat.completions.calls[0]["messages"] == [{"role": "user", "content": "read a.py"}]
    assert client.chat.completions.calls[0]["tools"][0]["function"]["parameters"] == {"type": "object"}
    assert response.actions[0].action == ToolCall(name="read_file", arguments={"path": "a.py"})
```

Retain tests for empty choices, non-object messages, malformed tool arguments, `finish`, and
input-schema immutability, changing only the fixture transport.

- [ ] **Step 2: Run the synchronous RED**

Run:

```bash
uv run pytest tests/adapters/llm/test_openai_compatible.py -q -k 'complete or response or finish or schema'
```

Expected: FAIL because `complete` still calls the old HTTP client and parses JSON dictionaries.

- [ ] **Step 3: Implement the SDK request and project response conversion**

Build a request dictionary from `_messages(context)` and `_tool_payload(tool)`, then call:

```python
completion = self._client.chat.completions.create(
    model=self._model,
    messages=self._messages(context),
    tools=[self._tool_payload(tool) for tool in tools],
)
```

Read only the first choice. Convert SDK attributes to the existing project response. Validate
that `choices` exists, the message is object-like, every function call has string `id`, `name`,
and JSON-object `arguments`, and content is `str | None`. Preserve `provider_metadata["tool_call_ids"]`.

Catch SDK authentication, rate-limit, timeout, connection, status, and generic SDK errors in
that order and raise the existing generic provider errors without including provider details.

- [ ] **Step 4: Run the synchronous GREEN and regression checks**

Run:

```bash
uv run pytest tests/adapters/llm/test_openai_compatible.py -q
uv run pytest tests/application/test_composition.py tests/application/test_context.py -q
```

Expected: all adapter tests and relevant composition/context regressions pass; no test starts a
real network client.

- [ ] **Step 5: Commit synchronous support**

Inspect the complete adapter diff before staging so the pre-existing schema-filter and deadline
behavior remains present alongside the SDK conversion. Stage only the adapter and its focused
fixtures/tests:

```bash
git add src/coding613/adapters/llm/openai_compatible.py tests/adapters/llm/sdk_fakes.py \
  tests/adapters/llm/test_openai_compatible.py
git commit -m "feat: call chat completions through OpenAI SDK"
```

## Task 3: Streaming Chunks, Cancellation, Deadline, And Cleanup

**Files:**
- Modify: `src/coding613/adapters/llm/openai_compatible.py`
- Modify: `tests/adapters/llm/sdk_fakes.py`
- Modify: `tests/adapters/llm/test_openai_compatible.py`

**Interfaces:**
- Consumes: Task 2 conversion/error helpers and Task 1 SDK client seam.
- Produces: `complete_stream(...) -> LLMResponse` using SDK `stream=True` and preserving the
  existing progress/cancellation contract.

- [ ] **Step 1: Write failing SDK stream tests**

Use fake chunks with the SDK shape (`chunk.choices[0].delta.content` and
`delta.tool_calls[*].function.arguments`) and assert:

```python
def test_complete_stream_aggregates_sdk_chunks_and_closes_stream() -> None:
    stream = FakeStream(
        [
            FakeChunk(content="hel"),
            FakeChunk(content="lo", tool_call=FakeToolDelta("call-1", "read_file", '{"pa')),
            FakeChunk(tool_call=FakeToolDelta(None, None, 'th":"a.py"}')),
        ]
    )
    client = FakeSDKClient(stream=stream)
    deltas: list[str] = []

    response = OpenAICompatibleLLM("https://provider.invalid/v1", "model", client).complete_stream(
        ModelContext(run_id=uuid4(), task="read a.py"), (), deltas.append, lambda: False
    )

    assert deltas == ["hel", "lo"]
    assert response.actions[0].action == ToolCall(name="read_file", arguments={"path": "a.py"})
    assert stream.closed is True
```

Add tests for missing `[DONE]` equivalent/incomplete stream, missing provider call ID, malformed
chunk containers, cancellation after a text delta, deadline expiry using an injected clock, and
cleanup when parsing or SDK iteration raises.

- [ ] **Step 2: Run streaming RED**

Run:

```bash
uv run pytest tests/adapters/llm/test_openai_compatible.py -q -k 'stream'
```

Expected: FAIL because the adapter expects text lines and JSON SSE records rather than SDK chunk
attributes.

- [ ] **Step 3: Implement SDK stream aggregation**

Call `client.chat.completions.create(..., stream=True)`, record the monotonic start time, and
iterate chunks in a `try/finally` that invokes the stream's `close()` method when available.
Before processing each chunk, check `cancelled()` and the absolute deadline. Append non-null text
content and invoke `on_text_delta` once per delta. Aggregate tool deltas by index, preserving the
first non-empty ID and concatenating name/argument fragments. At the end, require every tool call
to have an ID and convert the synthesized message through the same project response converter as
Task 2. Map SDK stream errors and cleanup failures without leaking secrets; preserve the primary
provider/cancellation/timeout error if cleanup also fails.

- [ ] **Step 4: Run streaming GREEN and full adapter regressions**

Run:

```bash
uv run pytest tests/adapters/llm/test_openai_compatible.py -q
uv run pytest tests/adapters/llm -q
```

Expected: all SDK ordinary and streaming adapter tests pass, including cleanup and absolute
deadline tests.

- [ ] **Step 5: Commit streaming support**

Inspect the complete adapter diff before staging so the pre-existing schema-filter and deadline
behavior remains present alongside SDK chunk aggregation. Stage only the adapter and its focused
fixtures/tests:

```bash
git add src/coding613/adapters/llm/openai_compatible.py tests/adapters/llm/sdk_fakes.py \
  tests/adapters/llm/test_openai_compatible.py
git commit -m "feat: stream chat completions through OpenAI SDK"
```

## Task 4: Credentialed Composition, Documentation, And Final Verification

**Files:**
- Modify: `src/coding613/adapters/llm/credentialed.py`
- Modify: `src/coding613/application/composition.py`
- Modify: `tests/adapters/llm/test_credentialed.py`
- Modify: `tests/application/test_composition.py`
- Modify: `README.md`
- Modify: `AGENT_LOG.md`
- Modify: `PLAN.md`
- Modify: `SPEC_PROCESS.md`
- Modify: `DELIVERY_STATUS.md`

**Interfaces:**
- Consumes: Task 1 `SDKClientFactory`, Task 2 synchronous provider, and Task 3 streaming provider.
- Produces: configured local services that construct the official SDK lazily and evidence proving
  the migration is complete without altering user-owned changes.

- [ ] **Step 1: Add failing credential/composition tests**

Update the factory fixtures to receive `(api_key, base_url, timeout)` and return `FakeSDKClient`.
Assert lazy lookup and one-time client creation:

```python
def test_configured_composition_uses_sdk_factory_without_persisting_key(tmp_path: Path) -> None:
    secret_store = _SecretStore("sk-composition-secret")
    captures: list[tuple[str, str, float]] = []

    def factory(api_key: str, base_url: str, timeout: float) -> FakeSDKClient:
        captures.append((api_key, base_url, timeout))
        return FakeSDKClient(completion=empty_completion())

    services = build_services(tmp_path, credential_store=secret_store, client_factory=factory)
    run = services.run_service.create_run(RunRequest(task="use configured provider"))
    services.run_service.resume(run.id)

    assert captures == [("sk-composition-secret", "https://api.example.test/v1", 60.0)]
    assert all("sk-composition-secret" not in event.model_dump_json() for event in services.list_events(run.id))
```

Add an assertion that the default factory creates an `OpenAI` client with `api_key`, `base_url`,
timeout, and `max_retries=0` by monkeypatching the adapter's imported `OpenAI` constructor; no
network call is made.

- [ ] **Step 2: Run credential/composition RED**

Run:

```bash
uv run pytest tests/adapters/llm/test_credentialed.py tests/application/test_composition.py -q
```

Expected: FAIL because the current factory still receives HTTP headers and the composition test
expects an `Authorization` header rather than SDK constructor arguments.

- [ ] **Step 3: Implement lazy official SDK construction and composition wiring**

Define the default factory using the official `OpenAI` constructor with `max_retries=0`. Pass the
secret as `api_key`, not as an application-visible header. Cache the resulting SDK-backed provider
after the first successful construction, close it through the existing provider `close()` path,
and preserve generic `ProviderCredentialError` wrapping for reader/factory failures. Update
composition type imports and tests without changing its provider injection behavior.

- [ ] **Step 4: Update user-facing provider documentation**

Add a concise README sentence under Provider Configuration: chat/tool requests use the official
OpenAI Python SDK, while `base_url` keeps OpenAI-compatible endpoints supported; keys still belong
in the OS keyring and are never written to `harness.toml`.

- [ ] **Step 5: Run all focused GREEN checks**

Run:

```bash
uv run pytest tests/adapters/llm tests/application/test_composition.py tests/application/test_context.py tests/application/test_loop.py -q
uv run ruff check src/coding613/adapters/llm src/coding613/application/composition.py tests/adapters/llm tests/application/test_composition.py
uv run mypy src/coding613/adapters/llm src/coding613/application/composition.py
uv lock --check
git diff --check
```

Expected: all focused tests, lint, type checks, lock validation, and whitespace checks pass. If
the independently owned `tmp/cube` tree affects collection, use the repository-approved
`uv run pytest -q --ignore=tmp` boundary and record that limitation rather than changing `tmp`.

- [ ] **Step 6: Run the complete offline verification**

Run:

```bash
uv run pytest -q --ignore=tmp
uv run ruff check .
uv run mypy src
uv lock --check
git diff --check
```

Expected: the full harness suite passes without network access or a real provider. Preserve the
known non-blocking warning if it remains; do not describe a command as passing unless it ran.

- [ ] **Step 7: Record evidence and commit the final task**

Append the actual timestamp, RED/GREEN counts, focused/full commands, commits, reviewer findings,
and any user-owned dirty paths to `AGENT_LOG.md`. Update the SDK row in `PLAN.md` and
`DELIVERY_STATUS.md` with the final commit and fresh verification. Stage only migration files and
records, verify `git diff --cached --name-only`, then commit:

```bash
git add src/coding613/adapters/llm/credentialed.py \
  src/coding613/application/composition.py tests/adapters/llm/test_credentialed.py \
  tests/application/test_composition.py README.md AGENT_LOG.md PLAN.md \
  SPEC_PROCESS.md DELIVERY_STATUS.md
git commit -m "refactor: complete OpenAI SDK provider migration"
```

## Review And Handoff Gates

After each task, perform a spec-compliance review first, then a code-quality review. Resolve every
Critical finding before continuing. The final handoff must identify the migration commits, fresh
verification output, any remaining user-owned dirty paths, and the fact that no real provider call
was made. Only after all tests and static checks pass may the branch be finished through the
repository's `finishing-a-development-branch` workflow.
