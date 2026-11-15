"""Tool-name overrides for pi, which runs the Herdr herdsman extension unless configured otherwise."""

from __future__ import annotations

import functools
import shutil
import tomllib

from .setup import config_path

HERDSMAN_OVERRIDES: dict[str, str] = {
    "TOOL_AGENT": "delegate_agent",
    "TOOL_STEER": "steer_agent",
    "TOOL_AGENT_RESULT": "inspect_agent",
    "TOOL_WORKFLOW": "",
}

DEFAULT_PI_RUNTIME = "herdsman"

PI_CONTEXT_OVERRIDES: dict[str, str] = {
    "TOOL_AGENT": "fork",
    "TOOL_STEER": "fork_steer",
    "TOOL_AGENT_RESULT": "result_fetch",
    "TOOL_WORKFLOW": "",
}

PI_RUNTIME_OVERRIDES: dict[str, dict[str, str]] = {
    "herdsman": HERDSMAN_OVERRIDES,
    "pi-context": PI_CONTEXT_OVERRIDES,
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


@functools.cache
def _parse_pi_runtime(config_text: str) -> tuple[str, str | None]:
    """Parse the ``[pi] runtime`` setting out of the config file's text.

    Args:
        config_text: Contents of ``config.toml``, empty when it does not exist.

    Returns:
        The runtime to use, and what is wrong with the setting, if anything.
    """
    try:
        config = tomllib.loads(config_text)
    except tomllib.TOMLDecodeError:
        return DEFAULT_PI_RUNTIME, "config.toml is not valid TOML"
    pi = config.get("pi", {})
    if not isinstance(pi, dict):
        return DEFAULT_PI_RUNTIME, "[pi] in config.toml is not a table"
    runtime = pi.get("runtime", DEFAULT_PI_RUNTIME)
    if not isinstance(runtime, str) or runtime not in PI_RUNTIME_OVERRIDES:
        return DEFAULT_PI_RUNTIME, f"Unknown [pi] runtime '{runtime}'"
    return runtime, None


def _pi_runtime_setting() -> tuple[str, str | None]:
    """Return the runtime and setting problem for the current ``config.toml``."""
    path = config_path()
    return _parse_pi_runtime(path.read_text(encoding="utf-8") if path.exists() else "")


def pi_runtime() -> str:
    """Return the configured pi runtime.

    Returns:
        The ``[pi] runtime`` config value, or ``herdsman`` when unset or unusable.
    """
    return _pi_runtime_setting()[0]


def pi_runtime_problem() -> str | None:
    """Return what is wrong with the ``[pi] runtime`` setting, or None when it is usable."""
    return _pi_runtime_setting()[1]


def pi_runtime_variables(variables: dict[str, str]) -> dict[str, str]:
    """Add the pi runtime's variables to a render's variables.

    Args:
        variables: Template variables for the render.

    Returns:
        The variables with ``PI_RUNTIME`` and the runtime's tool names when the
        target is pi, else unchanged.
    """
    if variables.get("AGENT") != "pi":
        return variables
    runtime = pi_runtime()
    return {**variables, "PI_RUNTIME": runtime, **PI_RUNTIME_OVERRIDES[runtime]}
