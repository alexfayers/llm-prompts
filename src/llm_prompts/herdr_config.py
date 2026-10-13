"""Merge llm-prompts' settings into the user's Herdr ``config.toml``."""

from __future__ import annotations

import copy
import os
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

BACKUP_SUFFIX = ".bak-pi-notify"
_AGENTS_PATH = ("ui", "sound", "agents")
_AGENTS_HEADER_LINE = f"[{'.'.join(_AGENTS_PATH)}]"
_AGENTS_HEADER = re.compile(
    rf"^{re.escape(_AGENTS_HEADER_LINE)}[ \t]*(#.*)?$", re.MULTILINE
)


class HerdrConfigError(ValueError):
    """The Herdr config cannot take the setting without changing something else."""


def herdr_config_path() -> Path:
    """Return Herdr's config file.

    Returns:
        ``$HERDR_CONFIG_PATH`` where set, else ``~/.config/herdr/config.toml``.
    """
    override = os.environ.get("HERDR_CONFIG_PATH")
    return (
        Path(override).expanduser()
        if override
        else Path.home() / ".config" / "herdr" / "config.toml"
    )


def _parse(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise HerdrConfigError(f"not valid TOML: {error}") from error


def _agents(config: dict[str, Any]) -> dict[str, Any]:
    """Return the ``[ui.sound.agents]`` table, empty where absent."""
    table: dict[str, Any] = config
    for key in _AGENTS_PATH:
        child = table.get(key, {})
        if not isinstance(child, dict):
            raise HerdrConfigError(f"`{key}` is not a table")
        table = child
    return table


def mute_agent_sound(config_path: Path, agent: str) -> bool:
    """Set ``[ui.sound.agents] <agent> = "off"`` in a Herdr config where absent.

    Everything else in the file, comments included, is left as written. The
    original is copied to ``<config_path>.bak-pi-notify`` before a change.

    Args:
        config_path: Path to Herdr's ``config.toml``.
        agent: Herdr agent name to mute.

    Returns:
        True when the file changed.

    Raises:
        HerdrConfigError: The file is not valid TOML or cannot take the key safely.
    """
    original = config_path.read_text(encoding="utf-8")
    before = _parse(original)
    if agent in _agents(before):
        return False
    entry = f'{agent} = "off"'
    header = _AGENTS_HEADER.search(original)
    if header:
        updated = f"{original[: header.end()]}\n{entry}{original[header.end() :]}"
    else:
        gap = ("" if original.endswith("\n") else "\n") + "\n" if original else ""
        updated = f"{original}{gap}{_AGENTS_HEADER_LINE}\n{entry}\n"
    expected = copy.deepcopy(before)
    table = expected
    for key in _AGENTS_PATH:
        table = table.setdefault(key, {})
    table[agent] = "off"
    if _parse(updated) != expected:
        raise HerdrConfigError(f"cannot add `{entry}` to {_AGENTS_HEADER_LINE}")
    shutil.copy2(config_path, config_path.with_name(config_path.name + BACKUP_SUFFIX))
    config_path.write_text(updated, encoding="utf-8")
    return True
