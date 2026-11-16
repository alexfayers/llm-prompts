"""Cline-hooks plugin that blocks shell patterns the rule text no longer states under pi."""

from __future__ import annotations

import re

from cline_hooks.core.plugin import HooksPlugin, hookimpl
from cline_hooks.handlers.commands import CommandRule, ParsedCommand

from .gate import guards_active

_PORT_MESSAGE = "MUST NOT kill processes by port - kill a specific PID."
_DASH_LETTERS = re.compile(r"(?<!\S)-([a-zA-Z]+)")
_VOLUME_MESSAGE = (
    "MUST NOT delete a Docker volume to reset state - it may hold pre-existing data. "
    "Delete only the specific test rows, or confirm the volume is disposable and ask the user."
)


def _sets_errexit(cmd: ParsedCommand, _all: list[ParsedCommand]) -> bool:
    """Report `set -e` (also combined, like `-euo`) or `set -o errexit`."""
    short = any(flag[1:2] != "-" and "e" in flag[1:] for flag in cmd.flags)
    return short or ("-o" in cmd.flags and "errexit" in cmd.args)


def _lists_pids_by_port(text: str) -> bool:
    """Report options that, together, list the PIDs on a port: `-t` and `-i`."""
    return {"t", "i"} <= set("".join(_DASH_LETTERS.findall(text)))


def _kill_of_lsof(cmd: ParsedCommand, _all: list[ParsedCommand]) -> bool:
    """Report a kill whose argument is an `lsof` that lists PIDs by port."""
    return any("lsof" in arg and _lists_pids_by_port(arg) for arg in cmd.args)


def _lsof_into_kill(cmd: ParsedCommand, all_commands: list[ParsedCommand]) -> bool:
    """Report an `lsof` that lists PIDs by port in a line that also kills."""
    kills = any(
        c.name == "kill" or (c.name == "xargs" and "kill" in c.args)
        for c in all_commands
    )
    return kills and _lists_pids_by_port(" ".join(cmd.flags))


def _removes_volumes(cmd: ParsedCommand, _all: list[ParsedCommand]) -> bool:
    """Report `docker compose down` with `-v` or `--volumes`, and `docker volume rm|prune`."""
    compose_down = (
        cmd.name == "docker-compose" or "compose" in cmd.args
    ) and "down" in cmd.args
    return (compose_down and bool({"-v", "--volumes"} & set(cmd.flags))) or (
        "volume" in cmd.args and bool({"rm", "remove", "prune"} & set(cmd.args))
    )


class ShellRules(HooksPlugin):
    """Contributes command rules for `set -e`, kill by port and Docker volume removal."""

    @hookimpl
    def command_rules(self) -> list[CommandRule]:
        """Return the rules where the guards are active, else none."""
        if not guards_active():
            return []
        return [
            CommandRule(
                command="set", message="MUST NOT use set -e.", validator=_sets_errexit
            ),
            CommandRule(
                command="fuser", blocked_flags=frozenset({"-k"}), message=_PORT_MESSAGE
            ),
            CommandRule(command="kill", message=_PORT_MESSAGE, validator=_kill_of_lsof),
            CommandRule(
                command="lsof", message=_PORT_MESSAGE, validator=_lsof_into_kill
            ),
            CommandRule(
                command="docker", message=_VOLUME_MESSAGE, validator=_removes_volumes
            ),
            CommandRule(
                command="docker-compose",
                message=_VOLUME_MESSAGE,
                validator=_removes_volumes,
            ),
        ]
