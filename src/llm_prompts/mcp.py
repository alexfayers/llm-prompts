"""Find the MCP tools that agents opted in with ``mcp_read_only`` must not see."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from functools import cache
from typing import Any, NamedTuple
from urllib.request import Request, urlopen

from .render_template import frontmatter_list

_TIMEOUT_SECONDS = 5
_HASH_SUFFIX_LENGTH = 9


class McpNaming(NamedTuple):
    """How a frontend names MCP tools: characters it replaces and its length limit."""

    invalid: str
    limit: int


PI_NAMING = McpNaming(r"[^A-Za-z0-9_]", 64)
CLAUDE_NAMING = McpNaming(r"[^A-Za-z0-9_-]", 128)

McpSources = list[tuple[str | None, dict[str, Any]]]


def _post(
    url: str, method: str, params: dict[str, Any], headers: dict[str, str]
) -> tuple[dict[str, Any], str | None]:
    """POST a JSON-RPC message (a notification where ``method`` says so) to an MCP endpoint.

    Returns:
        The reply (empty for a notification) and the ``Mcp-Session-Id`` response header.
    """
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
    if not method.startswith("notifications/"):
        message["id"] = method
    request = Request(
        url,
        json.dumps(message).encode(),
        {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **headers,
        },
    )
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        body = response.read().decode()
        session = response.headers.get("Mcp-Session-Id")
    payloads = (
        [body]
        if body.startswith("{")
        else [
            line.removeprefix("data:")
            for line in body.splitlines()
            if line.startswith("data:")
        ]
    )
    replies = (json.loads(payload) for payload in payloads)
    return next((r for r in replies if r.get("id") == message.get("id")), {}), session


def _tools(url: str) -> list[dict[str, Any]]:
    """List every tool an MCP HTTP server offers, following pagination."""
    reply, session = _post(
        url,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "llm-prompts", "version": "0"},
        },
        {},
    )
    headers = {"MCP-Protocol-Version": reply["result"]["protocolVersion"]}
    if session:
        headers["Mcp-Session-Id"] = session
    _post(url, "notifications/initialized", {}, headers)
    tools: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        reply, _ = _post(
            url, "tools/list", {"cursor": cursor} if cursor else {}, headers
        )
        tools += reply["result"]["tools"]
        cursor = reply["result"].get("nextCursor")
        if not cursor:
            return tools


def _tool_name(server: str, tool: str, naming: McpNaming) -> str:
    """Return a frontend's name for an MCP tool, ``mcp__<server>__<tool>`` sanitised."""
    return re.sub(naming.invalid, "_", f"mcp__{server}__{tool}")


def _server_pattern(server: str, naming: McpNaming) -> str:
    """Return the exclusion pattern matching every tool of an MCP server.

    Frontends cut an over-long tool name and add a hash suffix, so the prefix is
    cut to what survives.
    """
    prefix = _tool_name(server, "", naming)
    return f"{prefix[: naming.limit - _HASH_SUFFIX_LENGTH]}*"


def _namespaces(server: str, sources: McpSources) -> dict[str, Any]:
    """Return a server's config entries by tool namespace.

    A plugin's server is namespaced ``plugin_<plugin>_<server>``.
    """
    return {
        server if plugin is None else f"plugin_{plugin}_{server}": found[server]
        for plugin, found in sources
        if server in found
    } or {server: {}}


def _excluded_tools(
    namespace: str,
    entry: dict[str, Any],
    naming: McpNaming,
    warn: Callable[[str], None],
) -> tuple[str, ...]:
    """Return a frontend's names for an MCP server's tools lacking ``readOnlyHint``.

    Returns every tool of the server, after ``warn``, where its tools cannot be listed.
    """
    tools: list[dict[str, Any]] = []
    if entry.get("url") and not entry.keys() & {"headers", "oauth"}:
        try:
            tools = _tools(entry["url"])
            names = [_tool_name(namespace, tool["name"], naming) for tool in tools]
        except (OSError, ValueError, KeyError, TypeError):
            tools = []
    if not tools or any(len(name) > naming.limit for name in names):
        warn(
            f"Could not read MCP server {namespace}'s tool annotations; agents with mcp_read_only exclude all its tools."
        )
        return (_server_pattern(namespace, naming),)
    return tuple(
        name
        for name, tool in zip(names, tools, strict=True)
        if tool.get("annotations", {}).get("readOnlyHint") is not True
    )


def exclusions_resolver(
    naming: McpNaming,
    read_sources: Callable[[], McpSources],
    strict: bool,
    warn: Callable[[str], None],
) -> Callable[[str], Sequence[str]]:
    """Return a per-run resolver of the MCP tools the ``mcp_read_only`` servers hide.

    Where not ``strict``, no server is queried and all its tools are hidden.
    """

    def resolve(servers: str) -> tuple[str, ...]:
        return tuple(
            tool
            for server in frontmatter_list(servers)
            for namespace, entry in _namespaces(server, read_sources()).items()
            for tool in (
                _excluded_tools(namespace, entry, naming, warn)
                if strict
                else (_server_pattern(namespace, naming),)
            )
        )

    return cache(resolve) if strict else resolve
