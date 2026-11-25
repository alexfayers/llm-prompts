"""Cline-hooks plugin that blocks or corrects shell patterns the rule text no longer states under pi."""

from __future__ import annotations

import logging
import re
from typing import Any, cast

from cline_hooks.core.plugin import HookResult, HooksPlugin, hookimpl
from cline_hooks.core.vocabulary import PluginScope
from cline_hooks.handlers.commands import CommandRule, ParsedCommand

from .gate import guards_active

_PORT_MESSAGE = "MUST NOT kill processes by port - kill a specific PID."
_DASH_LETTERS = re.compile(r"(?<!\S)-([a-zA-Z]+)")
_VOLUME_MESSAGE = (
    "MUST NOT delete a Docker volume to reset state - it may hold pre-existing data. "
    "Delete only the specific test rows, or confirm the volume is disposable and ask the user."
)


_SET_OPTIONS = re.compile(r"[-+][a-zA-Z]+")
_LITERAL_WORD = re.compile(r"[\w./:=@%+,^-]+")
_BARE_SET_MESSAGE = "MUST NOT use set -e. MUST NOT pass `set` only words that may expand to nothing - it prints every shell variable."
_ERREXIT_NOTE = "Removed `-e` from `set`: MUST NOT use set -e."


def _sets_errexit_option(cmd: ParsedCommand, _all: list[ParsedCommand]) -> bool:
    """Report `set -o errexit`, also grouped like `-eo errexit`."""
    return "errexit" in cmd.args and any(
        flag[1:2] != "-" and "o" in flag[1:] for flag in cmd.flags
    )


class _MaybeBareSet(Exception):
    """A `set -e` whose remaining words may expand to nothing, so it would print every shell variable."""


def _set_edits(command: Any) -> list[tuple[int, int, str]]:
    """Return the (start, end, text) edits that take `-e` out of a parsed `set` command, else none."""
    words = [part for part in command.parts if part.kind == "word"]
    if not words or words[0].word != "set":
        return []
    edits: list[tuple[int, int, str]] = []
    kept = 0
    sets_something = False
    arguments = iter(words[1:])
    for word in arguments:
        if not _SET_OPTIONS.fullmatch(word.word):
            rest = [word, *arguments]
            kept += len(rest)
            sets_something |= any(_LITERAL_WORD.fullmatch(w.word) for w in rest)
            break
        letters = word.word[1:]
        stripped = letters.replace("e", "") if word.word[0] == "-" else letters
        if stripped != letters:
            edits.append((*word.pos, f"-{stripped}" if stripped else ""))
        kept += bool(stripped)
        sets_something |= bool(stripped) or stripped == letters
        if "o" in letters:
            value = next(arguments, None)
            kept += value is not None
    if not edits:
        return []
    if kept and not sets_something:
        raise _MaybeBareSet
    if not kept:
        edits.append((*words[0].pos, "true"))
    return edits


def _all_set_edits(node: Any) -> list[tuple[int, int, str]]:
    """Return the `-e` removals of every `set` command under the parsed node."""
    edits = _set_edits(node) if node.kind == "command" else []
    children = [
        *(getattr(node, "parts", None) or []),
        *(getattr(node, "list", None) or []),
        *([node.command] if getattr(node, "command", None) else []),
        *([node.output] if getattr(node, "output", None) else []),
    ]
    return edits + [edit for child in children for edit in _all_set_edits(child)]


def _without_errexit(command: str) -> str | None:
    """Return the shell line without `-e` in its `set` commands, or None where it has none.

    Raises:
        _MaybeBareSet: A `set -e` would be left with only words that may expand to nothing.
    """
    import bashlex  # type: ignore[import-untyped]
    import bashlex.errors  # type: ignore[import-untyped]

    try:
        edits = [
            edit for node in bashlex.parse(command) for edit in _all_set_edits(node)
        ]
    except (bashlex.errors.ParsingError, NotImplementedError):
        return None
    for start, end, text in sorted(edits, reverse=True):
        if not text:
            start = len(command[:start].rstrip(" \t"))
        command = command[:start] + text + command[end:]
    return command if edits else None


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
    """Contributes command rules for `set -o errexit`, kill by port and Docker volume removal, and drops `-e` from `set`."""

    def on_hook(
        self, hook_name: str, *, logger: logging.Logger, **kwargs: object
    ) -> HookResult | None:
        """Return the shell line without `-e` in its `set` calls, where the guards are active."""
        if hook_name != PluginScope.PRE_SHELL or not guards_active():
            return None
        try:
            fixed = _without_errexit(cast("str", kwargs.get("command") or ""))
        except _MaybeBareSet:
            return HookResult(block=_BARE_SET_MESSAGE)
        if fixed is None:
            return None
        return HookResult(updated_input={"command": fixed}, notes=[_ERREXIT_NOTE])

    @hookimpl
    def command_rules(self) -> list[CommandRule]:
        """Return the rules where the guards are active, else none."""
        if not guards_active():
            return []
        return [
            CommandRule(
                command="set",
                message="MUST NOT use set -o errexit.",
                validator=_sets_errexit_option,
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
