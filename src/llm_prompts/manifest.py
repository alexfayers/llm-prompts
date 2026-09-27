"""Manifest tracking for installed files."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from typing import TypedDict

from .setup import _CONFIG_DIR

MANIFEST_PATH = _CONFIG_DIR / "installed.json"
RENDERED_RULES_DIR = _CONFIG_DIR / "rendered-rules"


class AgentManifest(TypedDict, total=False):
    """Manifest entry for a single agent."""

    files: list[str]
    agent_config: str
    packages: list[str]
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
        agents: dict[str, AgentManifest] = data.get("agents", {})
        return agents
    except (json.JSONDecodeError, KeyError):
        return {}


def write_manifest(
    agent_name: str,
    files: list[str],
    *,
    agent_config: str | None = None,
    packages: list[str] | None = None,
) -> None:
    """Write or update the manifest for an agent.

    Args:
        agent_name: Agent that was installed.
        files: List of installed file paths.
        agent_config: Path to agent config that was patched, if any.
        packages: Agent packages llm-prompts manages in the agent's settings, if any.
    """
    agents = read_manifest()

    entry: AgentManifest = {
        "files": sorted(files),
        "installed_at": datetime.now(tz=UTC).isoformat(),
    }
    if agent_config:
        entry["agent_config"] = agent_config
    if packages is not None:
        entry["packages"] = packages

    agents[agent_name] = entry

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps({"agents": agents}, indent=2) + "\n",
        encoding="utf-8",
    )


def delete_agent(agent_name: str) -> None:
    """Remove an agent's entry from the manifest.

    Args:
        agent_name: Agent whose manifest entry to remove.
    """
    agents = read_manifest()
    if agent_name not in agents:
        return
    del agents[agent_name]
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps({"agents": agents}, indent=2) + "\n",
        encoding="utf-8",
    )


def read_rendered_rule(agent_name: str, name: str) -> str | None:
    """Read a rule's cached rendered text for an agent.

    Args:
        agent_name: Agent the rule was rendered for.
        name: Rule's destination name.

    Returns:
        The cached rendered text, or None if not cached.
    """
    path = RENDERED_RULES_DIR / agent_name / name
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_rendered_rules(agent_name: str, rules: dict[str, str]) -> None:
    """Replace an agent's entire cached rule set.

    Args:
        agent_name: Agent to cache rendered rules for.
        rules: Mapping of rule destination name to rendered text.
    """
    delete_rendered_rules(agent_name)
    agent_dir = RENDERED_RULES_DIR / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    for name, text in rules.items():
        (agent_dir / name).write_text(text, encoding="utf-8")


def delete_rendered_rules(agent_name: str) -> None:
    """Delete an agent's entire cached rule set.

    Args:
        agent_name: Agent whose cached rules to delete.
    """
    agent_dir = RENDERED_RULES_DIR / agent_name
    if agent_dir.exists():
        shutil.rmtree(agent_dir)
