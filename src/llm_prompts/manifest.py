"""Manifest tracking for installed files."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, TypedDict

from . import home
from .jsonfile import write_json_atomic


def manifest_path() -> Path:
    """Return the path of the installed agents manifest."""
    return home.config_dir() / "installed.json"


def rendered_rules_dir() -> Path:
    """Return the directory that caches rendered rules."""
    return home.config_dir() / "rendered-rules"


class ClaudePermissionState(TypedDict):
    """Permission rules llm-prompts manages in one Claude Code settings file, by list name.

    ``pending`` rules are about to be written. They count as owned only while the file
    still has the content whose SHA-256 is ``digest``.
    """

    owned: dict[str, list[str]]
    pending: dict[str, list[str]]
    digest: NotRequired[str]


class AgentManifest(TypedDict, total=False):
    """Manifest entry for a single agent."""

    files: list[str]
    agent_config: str
    packages: list[str]
    pi_installed_packages: list[str]
    skills: list[str]
    mcp_permissions: list[str]
    pi_rule_roles: dict[str, list[str]]
    pi_seeded_keys: dict[str, list[str]]
    claude_permissions: dict[str, ClaudePermissionState]
    installed_at: str


def _save(agents: dict[str, AgentManifest]) -> None:
    """Write the manifest through a scratch file and a rename."""
    write_json_atomic(manifest_path(), {"agents": agents})


def read_manifest() -> dict[str, AgentManifest]:
    """Read the installed agents manifest.

    Returns:
        Mapping of agent name to manifest entry.
    """
    if not manifest_path().exists():
        return {}
    try:
        data = json.loads(manifest_path().read_text(encoding="utf-8"))
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
    pi_installed_packages: list[str] | None = None,
    skills: list[str] | None = None,
    mcp_permissions: list[str] | None = None,
    pi_rule_roles: dict[str, list[str]] | None = None,
    pi_seeded_keys: dict[str, list[str]] | None = None,
    claude_permissions: dict[str, ClaudePermissionState] | None = None,
) -> None:
    """Write or update the manifest for an agent.

    Args:
        agent_name: Agent that was installed.
        files: List of installed file paths.
        agent_config: Path to agent config that was patched, if any.
        packages: Agent packages llm-prompts manages in the agent's settings, if any.
        pi_installed_packages: Names of the npm packages llm-prompts installed into pi, if any.
        skills: Agent skill dirs llm-prompts manages in the agent's settings, if any.
        mcp_permissions: Agent MCP permission rule keys llm-prompts manages, if any.
        pi_rule_roles: Roles each pi rule is selected for, by rule filename, if any.
        pi_seeded_keys: Dotted seed keys already offered, by seed file path, if any.
        claude_permissions: Permission rules llm-prompts manages, by resolved Claude Code settings path, if any.
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
    if pi_installed_packages is not None:
        entry["pi_installed_packages"] = pi_installed_packages
    if skills is not None:
        entry["skills"] = skills
    if mcp_permissions is not None:
        entry["mcp_permissions"] = mcp_permissions
    if pi_rule_roles is not None:
        entry["pi_rule_roles"] = pi_rule_roles
    if pi_seeded_keys is not None:
        entry["pi_seeded_keys"] = pi_seeded_keys
    if claude_permissions is not None:
        entry["claude_permissions"] = claude_permissions

    agents[agent_name] = entry

    _save(agents)


def record_claude_permissions(
    claude_permissions: dict[str, ClaudePermissionState] | None,
) -> None:
    """Save the Claude Code permission rules llm-prompts manages, keeping the rest of the entry.

    Args:
        claude_permissions: Rules by settings path, or None to forget them.
    """
    agents = read_manifest()
    entry = agents.setdefault(
        "claude-code",
        {"files": [], "installed_at": datetime.now(tz=UTC).isoformat()},
    )
    if claude_permissions is None:
        entry.pop("claude_permissions", None)
    else:
        entry["claude_permissions"] = claude_permissions
    _save(agents)


def delete_agent(
    agent_name: str,
    *,
    claude_permissions: dict[str, ClaudePermissionState] | None = None,
) -> None:
    """Remove an agent's entry from the manifest in one write.

    Args:
        agent_name: Agent whose manifest entry to remove.
        claude_permissions: Records to leave in a new entry for the agent, to retry cleanup.
    """
    agents = read_manifest()
    if agent_name not in agents:
        return
    if claude_permissions:
        agents[agent_name] = {
            "files": [],
            "installed_at": datetime.now(tz=UTC).isoformat(),
            "claude_permissions": claude_permissions,
        }
    else:
        del agents[agent_name]
    _save(agents)


def read_rendered_rule(agent_name: str, name: str) -> str | None:
    """Read a rule's cached rendered text for an agent.

    Args:
        agent_name: Agent the rule was rendered for.
        name: Rule's destination name.

    Returns:
        The cached rendered text, or None if not cached.
    """
    path = rendered_rules_dir() / agent_name / name
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
    agent_dir = rendered_rules_dir() / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    for name, text in rules.items():
        (agent_dir / name).write_text(text, encoding="utf-8")


def delete_rendered_rules(agent_name: str) -> None:
    """Delete an agent's entire cached rule set.

    Args:
        agent_name: Agent whose cached rules to delete.
    """
    agent_dir = rendered_rules_dir() / agent_name
    if agent_dir.exists():
        shutil.rmtree(agent_dir)
