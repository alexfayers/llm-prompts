"""How overlay layers combine with core: merged seed JSON and agent definitions."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from functools import reduce
from pathlib import Path
from typing import Any

from .render_template import _read_text, split_frontmatter


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge ``overlay`` over ``base``, combining nested dicts and replacing other values."""
    return {
        **base,
        **{
            key: deep_merge(base[key], value)
            if isinstance(value, dict) and isinstance(base.get(key), dict)
            else value
            for key, value in overlay.items()
        },
    }


def merged_seed_text(layers: Sequence[Path]) -> str:
    """Return a seed file's text: JSON layers deep merged, otherwise the top layer's text.

    Args:
        layers: The seed file in each layer holding it, lowest priority first.
    """
    if len(layers) == 1 or layers[0].suffix != ".json":
        return _read_text(layers[-1])
    merged = reduce(deep_merge, (json.loads(_read_text(path)) for path in layers))
    return json.dumps(merged, indent=2, ensure_ascii=False) + "\n"


_KEY_LINE = re.compile(r"^([A-Za-z_][\w-]*):")
_Block = tuple[str | None, list[str]]


def _frontmatter_blocks(lines: Sequence[str]) -> list[_Block]:
    """Group frontmatter lines into keyed blocks; template lines get no key."""
    blocks: list[_Block] = []
    for line in lines:
        key = _KEY_LINE.match(line)
        if key:
            blocks.append((key.group(1), [line]))
        elif blocks and blocks[-1][0] and (not line.strip() or line[0] in " \t"):
            blocks[-1][1].append(line)
        else:
            blocks.append((None, [line]))
    return blocks


def _merge_tools(base_line: str, overlay_line: str) -> str:
    """Append the overlay ``tools`` tokens to the base ones, skipping duplicates."""
    base, overlay = (
        line.partition(":")[2].strip() for line in (base_line, overlay_line)
    )
    tokens = dict.fromkeys(
        token
        for value in (base, overlay)
        for token in (t.strip(" []'\"") for t in value.split(","))
        if token
    )
    joined = ", ".join(tokens)
    return f"tools: [{joined}]" if base.startswith("[") else f"tools: {joined}"


def merge_agent_text(base: str, overlay: str) -> str:
    """Merge an overlay agent definition over a base one.

    The overlay's frontmatter keys replace the base's and add new ones, except
    ``tools``, whose tokens are appended without duplicates. A non-blank
    overlay body replaces the base body.
    """
    base_lines, base_body = split_frontmatter(base) or ([], base)
    overlay_lines, overlay_body = split_frontmatter(overlay) or ([], overlay)
    blocks = _frontmatter_blocks(base_lines)
    for key, lines in _frontmatter_blocks(overlay_lines):
        indexes = [i for i, (k, _) in enumerate(blocks) if key and k == key]
        if not indexes:
            blocks.append((key, lines))
            continue
        if key == "tools":
            lines = [_merge_tools(blocks[indexes[0]][1][0], lines[0])]
        blocks[indexes[0]] = (key, lines)
        for index in reversed(indexes[1:]):
            del blocks[index]
    frontmatter = "".join(f"{line}\n" for _, lines in blocks for line in lines)
    body = overlay_body if overlay_body.strip() else base_body
    return f"---\n{frontmatter}---\n{body}" if frontmatter else body
