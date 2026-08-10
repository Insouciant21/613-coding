# OpenAI SDK LLM Adapter Design

## Goal

Replace the hand-written HTTP and SSE implementation for chat and tool-calling model requests
with the official OpenAI Python SDK while preserving the harness-owned `LLMProvider` boundary,
deterministic agent loop, governance, feedback, credential, and offline-test behavior.

## Scope

This change covers synchronous and streamed chat completions used by the coding agent. It does not
move the agent loop, tool dispatch, policy, validation, feedback classification, memory, or stop
logic into the SDK. It also does not migrate the separate embedding adapter.

The existing OpenAI-compatible configuration remains valid: callers provide `base_url`, `model`,
credential reference, and timeout metadata. The implementation uses the official SDK with a
custom `base_url`, so compatible providers remain supported when they implement the Chat
Completions contract.

## Selected Approach

Use the official synchronous `OpenAI` client and `client.chat.completions.create(...)` for both
ordinary and streamed calls. This preserves the current message and tool-call contract with less
protocol churn than moving to the Responses API.

Alternatives rejected for this migration:

- Responses API: it would require a wider context, tool, and streaming-event redesign and reduce
  compatibility with existing configured endpoints.
- SDK transport with custom JSON/SSE parsing: it would technically add the SDK without removing
  the protocol-maintenance burden that motivated the change.

## Architecture

`coding613.ports.llm.LLMProvider` and `StreamingLLMProvider` remain the only application-facing
interfaces. The adapter owns conversion in both directions:

1. Convert `ModelContext` and `ToolDefinition` values to SDK Chat Completions parameters.
2. Invoke the injected SDK client.
3. Convert SDK completion messages or streamed chunks to `LLMResponse`, `ToolCall`, and
   `FinishAction` values.
4. Map SDK exceptions to the existing provider error taxonomy.

The adapter must not expose SDK response objects outside `coding613.adapters.llm`. Application,
domain, TUI, and CLI code continue to depend only on project-owned models and ports.

## Client And Credential Lifecycle

The credentialed wrapper continues to read the API key lazily on the first model call. It creates
one SDK client with the key, configured base URL, timeout, and `max_retries=0`, then reuses the
same client for ordinary and streamed calls. Disabling SDK retries keeps one harness model call
aligned with one provider request and preserves deterministic budget and audit semantics.

The key remains confined to client construction. It must not enter configuration objects,
domain state, events, logs, prompts, SQLite, LanceDB, subprocess arguments, or worker artifacts.
`close()` closes the cached SDK client without returning credential material.

Client construction remains injectable. Production uses the official `OpenAI` client; unit tests
use fakes and never require a key, network access, or a real model.

## Request Mapping

Each request passes the configured model, ordered context messages, and function tools to Chat
Completions. When `ModelContext.messages` is empty, the task remains the fallback user message.

Tool definitions keep the existing name and description. Local schema metadata such as `$id` is
removed from the provider payload without mutating the authoritative `ToolDefinition`. The
versioned schema remains available to the harness for local validation and audit.

## Response And Streaming Mapping

For ordinary completions, the adapter reads the first choice message, converts text content to a
string, validates each function call ID/name/JSON argument object, and maps `finish` to
`FinishAction`. Provider tool-call IDs remain in `provider_metadata`.

For streaming completions, the adapter iterates SDK chunks and:

- forwards each text delta exactly once;
- aggregates tool calls by SDK index;
- concatenates split function names and JSON arguments in order;
- requires a provider-issued call ID;
- validates the completed tool call through the same conversion path as a normal completion;
- returns the final project-owned `LLMResponse`.

The existing cooperative cancellation callback is checked before and during iteration. The
adapter also retains an injected monotonic clock and an absolute stream deadline, independent of
per-read SDK timeouts. A cancelled stream raises `ProviderCancelledError`; an expired deadline
raises `ProviderTimeoutError`. The SDK stream is closed on success, cancellation, timeout, parse
failure, or provider failure.

## Error Mapping

SDK failures map deterministically to the existing public exceptions:

- SDK authentication errors become `ProviderAuthenticationError`;
- SDK rate-limit errors become `ProviderRateLimitError`;
- SDK timeout errors become `ProviderTimeoutError`;
- SDK connection and other API transport/status errors become `ProviderHTTPError`;
- missing choices, malformed content, incomplete tool calls, or invalid JSON arguments become
  `ProviderResponseError`.

Exception messages remain generic and must not include response bodies, headers, API keys, or
other provider secrets.

## Dependencies And Compatibility

Add the official `openai` package as a bounded runtime dependency through `uv` and regenerate
`uv.lock`. Keep `httpx` because the embedding adapter still uses it directly and the SDK itself
uses it internally.

The configuration provider value remains `openai-compatible`; it describes the endpoint contract,
not the adapter implementation. No compatibility alias for the old implementation is introduced.
The production chat path must instantiate and call the official SDK rather than posting directly
through `httpx`.

## Testing

TDD begins with focused failing tests that prove the desired SDK boundary. Tests inject fake SDK
clients and typed-enough fake response/chunk values to cover:

- ordinary message and tool-call mapping;
- `finish` mapping and provider call IDs;
- `$id` removal without input mutation;
- streamed text and split tool-call aggregation;
- cancellation, absolute deadline, and stream cleanup;
- authentication, rate-limit, timeout, connection, status, and malformed-response errors;
- lazy one-time credential lookup, SDK client reuse, timeout/base URL/retry configuration, and
  secret-free failures;
- composition constructing the SDK-backed provider;
- absence of direct chat-completions HTTP posting in the production adapter.

After the focused suite passes, run the relevant application/composition regressions, the full
offline suite excluding the independent `tmp` repository, Ruff, mypy, lock verification, and diff
checks. No real provider request is required for acceptance.

## Acceptance Criteria

The migration is complete when:

1. Production chat and tool calls use the official OpenAI Python SDK.
2. No production adapter performs hand-written `/chat/completions` HTTP or SSE parsing.
3. Existing `LLMProvider` and streaming behavior remain compatible with the agent loop.
4. Keyring laziness and secret non-persistence remain enforced.
5. Existing error, cancellation, timeout, and tool-validation semantics have deterministic tests.
6. The SDK client and all core dependencies remain injectable and the suite runs offline.
7. Focused and full required verification passes and delivery records contain fresh evidence.
