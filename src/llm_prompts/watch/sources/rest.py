"""Conditional GitHub REST requests through the gh CLI."""

from __future__ import annotations

import re
from typing import NamedTuple

from ...network import run_with_retries
from ..core.source import WatchError


class Response(NamedTuple):
    """A response's status code, lowercase header names and body."""

    code: int
    headers: dict[str, str]
    body: str


def conditional_get(path: str, etag: str | None) -> Response:
    """GET path, asking for a 304 when etag still matches."""
    conditional = ["-H", f"If-None-Match: {etag}"] if etag else []
    try:
        result = run_with_retries(
            ["gh", "api", "-i", path, *conditional], capture_output=True, text=True
        )
    except OSError:
        raise WatchError("gh is not installed.") from None
    head, _, body = result.stdout.partition("\n\n")
    status_line, *header_lines = head.splitlines() or [""]
    status = re.match(r"HTTP/\S+ (\d+)", status_line)
    headers = {
        name.lower(): value.strip()
        for name, _, value in (line.partition(":") for line in header_lines)
    }
    return Response(int(status[1]) if status else 0, headers, body)
