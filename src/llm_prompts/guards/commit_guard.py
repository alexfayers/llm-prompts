"""Cline-hooks plugin that blocks a commit or push until the tests passed on the same files."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from cline_hooks.core.plugin import HookResult, HooksPlugin
from cline_hooks.core.vocabulary import CanonicalHook, CanonicalTool, PluginScope
from cline_hooks.handlers.commands import (
    ParsedCommand,
    extract_commands,
    is_git_push,
    is_read_only_git,
)
from cline_hooks.handlers.search_scope import effective_cwd

from .. import home
from .gate import guards_active
from .receipts import ReceiptStore, tree_fingerprint

if TYPE_CHECKING:
    import logging

TEST_COMMAND_ENV = "PI_CONTEXT_TEST_CMD"
_PROMPTS = Path(__file__).parent.parent / "prompts"
_UNCHAINED = re.compile(r";|\||\n|(?<!&)&(?!&)")
_READ_ONLY_AFTER_TEST = frozenset({"echo", "printf", "true", "pwd", "ls", "cat"})
_IN_PROGRESS = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD")


class _Match(TypedDict):
    pattern: str
    file: NotRequired[str]


class _Gate(TypedDict):
    command: NotRequired[str]
    pattern: NotRequired[str | list[str]]
    all: NotRequired[list[str]]
    any: NotRequired[list[str]]
    match: NotRequired[_Match]


def _parse(command: str) -> list[ParsedCommand] | None:
    """Return the commands of a shell line, or None where it does not parse."""
    import bashlex  # type: ignore[import-untyped]
    import bashlex.errors  # type: ignore[import-untyped]

    try:
        return extract_commands(bashlex.parse(command))
    except bashlex.errors.ParsingError:
        return None


def _repo(directory: str) -> tuple[Path, Path] | None:
    """Return the top level and git directory of the repo holding the directory, or None."""
    result = subprocess.run(
        ["git", "-C", directory, "rev-parse", "--show-toplevel", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = result.stdout.splitlines()
    return (
        (Path(lines[0]), Path(lines[1]))
        if result.returncode == 0 and len(lines) == 2
        else None
    )


@dataclass(frozen=True)
class _TestRun:
    """What counts as a repo's test run, or the block a broken gate gives."""

    label: str
    command: list[str] | None = None
    patterns: tuple[re.Pattern[str], ...] = ()
    error: str | None = None

    def matches(self, words: list[str]) -> bool:
        """Report whether the words are the command, or match a pattern in full."""
        if self.command is not None:
            return words == self.command
        return any(regex.fullmatch(shlex.join(words)) for regex in self.patterns)


def _from_command(command: str) -> _TestRun:
    """Return the test run of an exact command."""
    return _TestRun(f"`{command}`", shlex.split(command))


def _from_gate(gate: _Gate, source: Path) -> _TestRun:
    """Return the test run of a gate from the source file, with an error where a pattern does not compile."""
    if "command" in gate:
        return _from_command(gate["command"])
    pattern = gate.get("pattern", [])
    regexes = [pattern] if isinstance(pattern, str) else pattern
    compiled = []
    for regex in regexes:
        try:
            compiled.append(re.compile(regex))
        except re.error as error:
            return _TestRun(
                "",
                error=f"MUST fix the test gate pattern `{regex}` in {source}: {error}.",
            )
    return _TestRun(
        "a command matching " + " or ".join(f"`{regex}`" for regex in regexes),
        patterns=tuple(compiled),
    )


def _detected_gate(toplevel: Path) -> _TestRun | None:
    """Return the test run of the gate overlay, then core, test-gates.json detects, or None."""
    from ..install import _discover_overlay_paths
    from ..overlay_merge import TEST_GATES, merged_test_gates

    gates = [
        (cast("_Gate", gate), root / TEST_GATES)
        for root in [*_discover_overlay_paths(quiet=True), _PROMPTS]
        for gate in merged_test_gates([root])
    ]
    for gate, source in gates:
        if "command" not in gate and "pattern" not in gate:
            continue
        every = gate.get("all", [])
        some = gate.get("any")
        match = gate.get("match")
        if not all((toplevel / name).exists() for name in every):
            continue
        if some is not None and not any((toplevel / name).exists() for name in some):
            continue
        file = match and (
            match.get("file")
            or next(
                (n for n in [*every, *(some or [])] if (toplevel / n).exists()), None
            )
        )
        if match and not (
            file
            and re.search(
                match["pattern"],
                (toplevel / file).read_text(encoding="utf-8", errors="replace"),
                re.MULTILINE,
            )
        ):
            continue
        return _from_gate(gate, source)
    return None


def _test_gate(toplevel: Path) -> _TestRun | None:
    """Return the repo's test run: the env setting as a command, else the detected gate's, else None."""
    configured = os.environ.get(TEST_COMMAND_ENV)
    return _from_command(configured) if configured else _detected_gate(toplevel)


def _gate_words(words: list[str]) -> list[str]:
    """Drop a leading `timeout [options] <duration>` from the words."""
    if words[0] == "timeout":
        return [word for word in words[1:] if not word.startswith("-")][1:]
    return words


def _dirty(toplevel: Path) -> bool:
    """Report whether the repo has uncommitted or untracked changes."""
    status = subprocess.run(
        ["git", "-C", str(toplevel), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(status.stdout.strip())


def _git_verb(cmd: ParsedCommand) -> str | None:
    """Return `commit` or `push` where the command is a git commit or push, else None."""
    if cmd.name != "git" or is_read_only_git(cmd):
        return None
    if is_git_push([cmd]):
        return "push"
    return "commit" if "commit" in cmd.args else None


def _git_directory(commands: list[ParsedCommand], index: int, roots: list[str]) -> str:
    """Return the directory the command at ``index`` runs git in, following each ``-C``, ``--work-tree`` and ``--git-dir`` option before the subcommand, as git does."""
    directory = effective_cwd(commands, index, roots[0] if roots else os.getcwd())
    words = iter(commands[index].words)
    for word in words:
        if not word.startswith("-"):
            break
        option, _, attached = word.partition("=")
        if option in ("-C", "-c", "--git-dir", "--work-tree") and not attached:
            attached = next(words, "")
        if word.startswith("-C") and option != "-C":
            option, attached = "-C", word[2:]
        if option == "-C" or option == "--work-tree":
            directory = os.path.join(
                directory, os.path.expandvars(os.path.expanduser(attached))
            )
        elif option == "--git-dir":
            directory = os.path.dirname(
                os.path.join(
                    directory, os.path.expandvars(os.path.expanduser(attached))
                )
            )
    return directory


class CommitGuard(HooksPlugin):
    """Records passing test runs and blocks a commit or push without one on the current files."""

    def on_hook(
        self, hook_name: str, *, logger: logging.Logger, **kwargs: object
    ) -> HookResult | None:
        """Dispatch a shell event to the receipt recording or the commit check."""
        if not guards_active():
            return None
        if hook_name == PluginScope.PRE_SHELL:
            return self._check(
                cast("str", kwargs.get("command") or ""),
                cast("list[str]", kwargs.get("workspace_roots") or []),
            )
        if (
            hook_name == CanonicalHook.POST_TOOL_USE
            and kwargs.get("tool_name") == CanonicalTool.SHELL
            and kwargs.get("success")
        ):
            self._record(
                cast("dict[str, str]", kwargs.get("parameters") or {}),
                cast("list[str]", kwargs.get("workspace_roots") or []),
            )
        return None

    def _record(self, parameters: dict[str, str], workspace_roots: list[str]) -> None:
        """Store a receipt where a passing call's result shows the repo's test command passed: it ran last, or every step was joined by `&&` and only read-only steps that write no file follow it."""
        line = parameters.get("command", "")
        commands = _parse(line) if "action" not in parameters else None
        steps = [index for index, cmd in enumerate(commands or []) if cmd.name != "cd"]
        if commands is None or not steps:
            return
        decided = steps if not _UNCHAINED.search(line) else steps[-1:]
        for index in decided:
            cmd = commands[index]
            if cmd.piped_from or any(other.piped_from is cmd for other in commands):
                continue
            if any(
                later.name not in _READ_ONLY_AFTER_TEST
                or any(target != "/dev/null" for target in later.redirect_outputs)
                for later in commands[index + 1 :]
            ):
                continue
            repo = _repo(
                effective_cwd(
                    commands,
                    index,
                    workspace_roots[0] if workspace_roots else os.getcwd(),
                )
            )
            gate = repo and _test_gate(repo[0])
            if repo and gate and gate.matches(_gate_words([cmd.name, *cmd.words])):
                ReceiptStore().record(repo[0], tree_fingerprint(repo[0]))
                return

    def _check(self, command: str, workspace_roots: list[str]) -> HookResult | None:
        """Return a block for a git commit or push in a repo whose tests have not passed on its current files."""
        commands = _parse(command)
        for index, cmd in enumerate(commands or []):
            verb = _git_verb(cmd)
            if verb is None or commands is None:
                continue
            repo = _repo(_git_directory(commands, index, workspace_roots))
            gate = repo and _test_gate(repo[0])
            if (
                not repo
                or not gate
                or any((repo[1] / marker).exists() for marker in _IN_PROGRESS)
            ):
                continue
            if verb == "push" and _dirty(repo[0]):
                return HookResult(
                    block="MUST commit or stash all changes before git push."
                )
            if gate.error:
                return HookResult(block=gate.error)
            if not ReceiptStore().fresh(repo[0], tree_fingerprint(repo[0])):
                return HookResult(
                    block=f"MUST run {gate.label} and see it pass on the current files before git {verb}."
                )
        return None


_PRIMARY_BLOCKED = {
    "commit",
    "reset",
    "cherry-pick",
    "rebase",
    "revert",
    "am",
    "merge",
    "pull",
    "stash",
    "push",
}
_FF_ONLY = {"merge", "pull"}
_STASH_ALLOWED = {"list", "show", "push", "save"}
_PRIMARY_MESSAGE = (
    "MUST NOT change the primary checkout. Work in a worktree:"
    " `git worktree add -b <login>/<slug> ../<repo>-worktrees/<slug> origin/main`."
    " To land it, rebase it onto main there, then run `git merge --ff-only <branch>` here,"
    " then `git worktree remove <path> && git branch -d <branch>`."
    " In llm-prompts, cline-hooks and mcp-memory, land with `llm-prompts contribute sync`."
    " If this change is intentional, run the exact same command again to proceed."
)


def _primary_verb(cmd: ParsedCommand) -> str | None:
    """Return the verb of a git or gh call that changes a checkout's branch, else None."""
    if cmd.name == "gh":
        return "pr create" if cmd.words[:2] == ["pr", "create"] else None
    if cmd.name != "git" or is_read_only_git(cmd):
        return None
    verb = next((word for word in cmd.words if word in _PRIMARY_BLOCKED), None)
    if verb in _FF_ONLY and "--ff-only" in cmd.words:
        return None
    if verb == "stash" and not {"pop", "apply"} & set(cmd.words):
        return None
    if verb is None and cmd.words[:1] == ["branch"] and _forces(cmd.words[1:]):
        return "branch --force"
    return verb


def _forces(words: list[str]) -> bool:
    """Whether the options force a branch move: ``--force`` or a short-option group holding ``f``."""
    return any(
        word == "--force" or (word[:1] == "-" and word[1:2] != "-" and "f" in word)
        for word in words
    )


def _is_primary(directory: str) -> Path | None:
    """Return the top level of the repo holding the directory where it is the primary checkout, else None."""
    result = subprocess.run(
        [
            "git",
            "-C",
            directory,
            "rev-parse",
            "--show-toplevel",
            "--absolute-git-dir",
            "--git-common-dir",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = result.stdout.splitlines()
    if result.returncode != 0 or len(lines) != 3:
        return None
    toplevel, git_dir, common = (
        Path(lines[0]),
        Path(lines[1]),
        Path(directory, lines[2]).resolve(),
    )
    if git_dir != common or any((git_dir / marker).exists() for marker in _IN_PROGRESS):
        return None
    return toplevel


class PrimaryCheckoutGuard(HooksPlugin):
    """Blocks agent changes to a repo's primary checkout, so work happens in worktrees; the exact same command again proceeds."""

    def on_hook(
        self, hook_name: str, *, logger: logging.Logger, **kwargs: object
    ) -> HookResult | None:
        """Block a branch-changing git or gh call in a primary checkout, once per exact command."""
        if hook_name != PluginScope.PRE_SHELL:
            return None
        command = cast("str", kwargs.get("command") or "")
        roots = cast("list[str]", kwargs.get("workspace_roots") or [])
        commands = _parse(command) or []
        for index, cmd in enumerate(commands):
            if _primary_verb(cmd) is None:
                continue
            toplevel = _is_primary(_git_directory(commands, index, roots))
            if toplevel is None:
                continue
            retries = ReceiptStore(home.config_dir() / "primary-blocks.json")
            if retries.fresh(toplevel, command):
                retries.record(toplevel, "")
                return None
            retries.record(toplevel, command)
            return HookResult(block=_PRIMARY_MESSAGE)
        return None
