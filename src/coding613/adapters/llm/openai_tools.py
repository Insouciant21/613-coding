"""Responses API hosted-tool definitions.

The harness still owns the agent loop and local tool dispatch.  This module
only builds the low-level payloads accepted by ``responses.create`` for tools
that OpenAI executes on the provider side.  Client-side shell and patch work
remain local tools so policy, approvals, and repository boundaries cannot be
bypassed by a hosted runner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from coding613.config import LLMConfig
from coding613.ports.llm import ToolDefinition

_ALIASES = {
    "websearch": "web_search",
    "web-search": "web_search",
    "websearch_preview": "web_search_preview",
    "web-search-preview": "web_search_preview",
    "code-interpreter": "code_interpreter",
    "file-search": "file_search",
    "image-generation": "image_generation",
}

_SUPPORTED = frozenset(
    {
        "web_search",
        "web_search_preview",
        "file_search",
        "code_interpreter",
        "image_generation",
        "mcp",
        "tool_search",
    }
)

_CLIENT_SIDE_ONLY = frozenset(
    {"shell", "local_shell", "apply_patch", "computer_use_preview"}
)
_EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def build_responses_tools(config: LLMConfig) -> tuple[ToolDefinition, ...]:
    """Build configured hosted Responses tools for one effective provider.

    Non-Responses providers receive no hosted definitions.  Unknown names and
    missing required options fail during composition rather than producing a
    provider request that can never work.
    """

    if config.api != "responses":
        return ()
    definitions: list[ToolDefinition] = []
    for requested in config.responses_tools:
        name = _ALIASES.get(requested, requested)
        if name in _CLIENT_SIDE_ONLY:
            raise ValueError(
                f"Responses hosted tool {name!r} requires client-side output handling; "
                "use the local run_command/apply_patch tools"
            )
        if name not in _SUPPORTED:
            supported = ", ".join(sorted(_SUPPORTED))
            raise ValueError(f"unsupported Responses tool {requested!r}; use: {supported}")
        options = config.responses_tool_options.get(requested)
        if options is None:
            options = config.responses_tool_options.get(name, {})
        definitions.append(_build_one(name, options))
    return tuple(definitions)


def _build_one(name: str, options: Mapping[str, Any]) -> ToolDefinition:
    if not isinstance(options, Mapping):
        raise TypeError(f"Responses tool options for {name} must be a table")
    if name == "web_search":
        payload = _pick(
            {"type": "web_search", "search_context_size": "medium"},
            options,
            {"search_context_size", "user_location", "filters"},
        )
        _choice(payload, "search_context_size", {"low", "medium", "high"})
        return _hosted(name, "Search the web using OpenAI's hosted web search", payload)
    if name == "web_search_preview":
        payload = _pick(
            {"type": "web_search_preview", "search_context_size": "medium"},
            options,
            {"search_context_size", "search_content_types", "user_location"},
        )
        _choice(payload, "search_context_size", {"low", "medium", "high"})
        return _hosted(name, "Search the web using the Responses preview search tool", payload)
    if name == "file_search":
        vector_store_ids = options.get("vector_store_ids")
        if not isinstance(vector_store_ids, (list, tuple)) or not vector_store_ids:
            raise ValueError("file_search requires non-empty vector_store_ids")
        if not all(isinstance(item, str) and item.strip() for item in vector_store_ids):
            raise ValueError("file_search vector_store_ids must be non-empty strings")
        payload = _pick(
            {"type": "file_search", "vector_store_ids": list(vector_store_ids)},
            options,
            {"filters", "max_num_results", "ranking_options"},
        )
        return _hosted(name, "Search configured OpenAI vector stores", payload)
    if name == "code_interpreter":
        container = options.get("container", {"type": "auto"})
        if not isinstance(container, (str, dict)):
            raise ValueError("code_interpreter container must be a string or table")
        return _hosted(
            name,
            "Execute bounded Python code in the provider-hosted interpreter",
            {"type": "code_interpreter", "container": container},
        )
    if name == "image_generation":
        payload = _pick({"type": "image_generation"}, options, {
            "action", "background", "input_fidelity", "model", "moderation",
            "output_compression", "output_format", "partial_images", "quality", "size",
        })
        return _hosted(name, "Generate or edit an image with OpenAI", payload)
    if name == "mcp":
        label = options.get("server_label")
        url = options.get("server_url")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("mcp requires server_label")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise ValueError("mcp requires an HTTP(S) server_url")
        payload = _pick(
            {"type": "mcp", "server_label": label, "server_url": url},
            options,
            {"authorization", "headers", "allowed_tools", "require_approval", "server_description"},
        )
        return _hosted(name, "Call a configured remote Model Context Protocol server", payload)
    if name == "tool_search":
        payload = _pick({"type": "tool_search", "execution": "server"}, options, {"description", "parameters"})
        _choice(payload, "execution", {"server", "client"})
        if payload["execution"] == "client":
            raise ValueError("client tool_search requires a client-side search protocol")
        return _hosted(name, "Search the provider's deferred tool catalogue", payload)
    raise AssertionError(f"unhandled Responses tool: {name}")


def _hosted(name: str, description: str, payload: dict[str, Any]) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        input_schema=_EMPTY_SCHEMA,
        transport="responses_hosted",
        provider_payload=payload,
    )


def _pick(
    base: dict[str, Any], options: Mapping[str, Any], allowed: set[str]
) -> dict[str, Any]:
    unknown = set(options) - allowed - set(base)
    if unknown:
        raise ValueError(f"unsupported options: {', '.join(sorted(unknown))}")
    result = dict(base)
    result.update({key: options[key] for key in allowed if key in options})
    return result


def _choice(payload: Mapping[str, Any], key: str, values: set[str]) -> None:
    value = payload.get(key)
    if value not in values:
        raise ValueError(f"{key} must be one of: {', '.join(sorted(values))}")


__all__ = ["build_responses_tools"]
