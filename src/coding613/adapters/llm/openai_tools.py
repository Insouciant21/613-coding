"""Responses API hosted-tool definitions.

The harness still owns the agent loop and local tool dispatch. This module
builds the low-level payloads accepted by ``responses.create`` for both
provider-hosted tools and client-side Responses protocols. Client-side shell
and patch calls are translated back into governed local actions by the adapter;
policy, approvals, and repository boundaries remain authoritative.
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
    "computer-use": "computer_use_preview",
    "computer-use-preview": "computer_use_preview",
    "local-shell": "local_shell",
    "apply-patch": "apply_patch",
    "programmatic-tool-calling": "programmatic_tool_calling",
    "custom-tool": "custom",
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
        "computer_use_preview",
        "computer",
        "shell",
        "local_shell",
        "apply_patch",
        "custom",
        "namespace",
        "programmatic_tool_calling",
    }
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
        allowed_callers = options.get("allowed_callers")
        if allowed_callers is not None:
            _callers(allowed_callers)
        code_payload: dict[str, Any] = {"type": "code_interpreter", "container": container}
        if allowed_callers is not None:
            code_payload["allowed_callers"] = list(allowed_callers)
        return _hosted(
            name,
            "Execute bounded Python code in the provider-hosted interpreter",
            code_payload,
        )
    if name == "image_generation":
        payload = _pick({"type": "image_generation"}, options, {
            "action", "background", "input_fidelity", "model", "moderation",
            "input_image_mask", "output_compression", "output_format", "partial_images",
            "quality", "size",
        })
        return _hosted(name, "Generate or edit an image with OpenAI", payload)
    if name == "mcp":
        label = options.get("server_label")
        url = options.get("server_url")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("mcp requires server_label")
        connector = options.get("connector_id")
        if url is not None and (
            not isinstance(url, str) or not url.startswith(("https://", "http://"))
        ):
            raise ValueError("mcp server_url must be an HTTP(S) URL")
        if url is None and not isinstance(connector, str):
            raise ValueError("mcp requires server_url or connector_id")
        base: dict[str, Any] = {"type": "mcp", "server_label": label}
        if url is not None:
            base["server_url"] = url
        if connector is not None:
            base["connector_id"] = connector
        payload = _pick(
            base,
            options,
            {
                "authorization",
                "headers",
                "allowed_tools",
                "allowed_callers",
                "require_approval",
                "server_description",
                "defer_loading",
                "tunnel_id",
            },
        )
        return _hosted(name, "Call a configured remote Model Context Protocol server", payload)
    if name == "tool_search":
        payload = _pick(
            {"type": "tool_search", "execution": "server"},
            options,
            {"description", "parameters"},
        )
        _choice(payload, "execution", {"server", "client"})
        return _hosted(name, "Search the provider's deferred tool catalogue", payload)
    if name == "shell":
        environment = options.get("environment", {"type": "local"})
        if not isinstance(environment, dict):
            raise ValueError("shell environment must be a table")
        payload = _pick(
            {"type": "shell", "environment": dict(environment)},
            options,
            {"allowed_callers"},
        )
        _callers(payload.get("allowed_callers"))
        return _hosted(name, "Execute governed shell commands through Responses", payload)
    if name == "local_shell":
        payload = _pick({"type": "local_shell"}, options, {"allowed_callers"})
        _callers(payload.get("allowed_callers"))
        return _hosted(name, "Execute a governed command in the local repository", payload)
    if name == "apply_patch":
        payload = _pick({"type": "apply_patch"}, options, {"allowed_callers"})
        _callers(payload.get("allowed_callers"))
        return _hosted(name, "Apply a governed repository patch through Responses", payload)
    if name == "computer_use_preview":
        payload = _pick(
            {
                "type": "computer_use_preview",
                "display_width": 1280,
                "display_height": 720,
                "environment": "linux",
            },
            options,
            {"display_width", "display_height", "environment"},
        )
        _positive_int(payload, "display_width")
        _positive_int(payload, "display_height")
        _choice(payload, "environment", {"windows", "mac", "linux", "ubuntu", "browser"})
        return _hosted(name, "Control a configured computer with screenshot feedback", payload)
    if name == "computer":
        return _hosted(name, "Control a configured computer with screenshot feedback", {"type": "computer"})
    if name == "programmatic_tool_calling":
        return _hosted(
            name,
            "Compose and execute multiple configured tools programmatically",
            {"type": "programmatic_tool_calling"},
        )
    if name == "custom":
        custom_name = options.get("name")
        description = options.get("description", "")
        custom_format = options.get("format", {"type": "text"})
        if not isinstance(custom_name, str) or not custom_name.strip():
            raise ValueError("custom requires a non-empty name")
        if not isinstance(description, str):
            raise ValueError("custom description must be a string")
        if not isinstance(custom_format, dict):
            raise ValueError("custom format must be a table")
        payload = _pick(
            {
                "type": "custom",
                "name": custom_name,
                "description": description,
                "format": dict(custom_format),
            },
            options,
            {"allowed_callers", "defer_loading"},
        )
        _callers(payload.get("allowed_callers"))
        return _hosted(custom_name, "Invoke a configured custom Responses tool", payload)
    if name == "namespace":
        namespace_name = options.get("name")
        description = options.get("description")
        tools = options.get("tools")
        if not isinstance(namespace_name, str) or not namespace_name.strip():
            raise ValueError("namespace requires a non-empty name")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("namespace requires a non-empty description")
        if not isinstance(tools, list) or not tools or not all(isinstance(item, dict) for item in tools):
            raise ValueError("namespace requires a non-empty tools array")
        payload = {
            "type": "namespace",
            "name": namespace_name,
            "description": description,
            "tools": [dict(item) for item in tools],
        }
        return _hosted(namespace_name, "Expose a configured Responses tool namespace", payload)
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


def _callers(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) and item in {"direct", "programmatic"}
        for item in value
    ):
        raise ValueError("allowed_callers must contain only direct or programmatic")


def _positive_int(payload: Mapping[str, Any], key: str) -> None:
    value = payload.get(key)
    if type(value) is not int or value <= 0:
        raise ValueError(f"{key} must be a positive integer")


__all__ = ["build_responses_tools"]
