"""Manifest tracking for installed files."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import TypedDict

from .setup import _CONFIG_DIR


MANIFEST_PATH = _CONFIG_DIR / "installed.json"


class AgentManifest(TypedDict, total=False):
    """Manifest entry for a single agent."""

    files: list[str]
    agent_config: str
    installed_at: str


def read_manifest() -> dict[str, AgentManifest]:
    """Read the installed agents manifest.

    Returns:
        Mapping of agent name to manifest entry.
    """
    if not MANIFEST_PATH.exists():
        return {}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return data.get("agents", {})
    except (json.JSONDecodeError, KeyError):
        return {}


def write_manifest(
    agent_name: str,
    files: list[str],
    *,
    agent_config: str | None = None,
) -> None:
    """Write or update the manifest for an agent.

    Args:
        agent_name: Agent that was installed.
        files: List of installed file paths.
        agent_config: Path to agent config that was patched, if any.
    """
    agents = read_manifest()

    entry: AgentManifest = {
        "files": sorted(files),
        "installed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    if agent_config:
        entry["agent_config"] = agent_config

    agents[agent_name] = entry

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps({"agents": agents}, indent=2) + "\n",
        encoding="utf-8",
    )
