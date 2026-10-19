"""Tool-name overrides for pi, which always runs the Herdr herdsman extension."""

from __future__ import annotations

import shutil

HERDSMAN_OVERRIDES: dict[str, str] = {
    "TOOL_AGENT": "delegate_agent",
    "TOOL_STEER": "steer_agent",
    "TOOL_AGENT_RESULT": "inspect_agent",
    "TOOL_WORKFLOW": "",
}

HERDSMAN_DISABLED_DEFINITIONS: tuple[str, ...] = (
    "generalist",
    "implementer",
    "researcher",
    "scout",
)

HERDSMAN_BUNDLED_RESETS: dict[str, dict[str, list[str] | bool]] = {
    "reviewer": {"agents": [], "noSkills": False, "tools": ["*"]},
}


def herdr_available() -> bool:
    """Report whether the ``herdr`` command is on PATH.

    Returns:
        True when the ``herdr`` command is available.
    """
    return shutil.which("herdr") is not None


def is_herdsman(variables: dict[str, str]) -> bool:
    """Report whether the render targets pi, which always runs as herdsman.

    Args:
        variables: Template variables for the render.

    Returns:
        True when the target is pi.
    """
    return variables.get("AGENT") == "pi"
