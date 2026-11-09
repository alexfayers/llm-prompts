"""OS sandbox policy, selection and command wrapping."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from llm_prompts.benchmark import paths


class SandboxMissing(RuntimeError):
    """Neither sandbox-exec nor bwrap is available."""


@dataclass(frozen=True)
class SandboxPolicy:
    writable: tuple[Path, ...]
    denied_ports: tuple[int, ...] = ()
    mount: tuple[Path, Path] | None = None
    read_only: tuple[Path, ...] = ()


def _kind() -> str:
    if shutil.which("sandbox-exec"):
        return "macos"
    if shutil.which("bwrap"):
        return "linux"
    raise SandboxMissing(
        "No OS sandbox found: install sandbox-exec (macOS) or bwrap (Linux),"
        " or pass --no-os-sandbox to run without one."
    )


def require(enabled: bool) -> None:
    """Raise SandboxMissing when the sandbox is enabled but no OS sandbox exists."""
    if enabled:
        _kind()


def remaps_paths() -> bool:
    """Return whether the sandbox can show a directory at another path."""
    try:
        return _kind() == "linux"
    except SandboxMissing:
        return False


def wrap(argv: Sequence[str], policy: SandboxPolicy) -> list[str]:
    """Return `argv` prefixed with the available OS sandbox."""
    if _kind() == "macos":
        return [
            "sandbox-exec",
            "-p",
            macos_profile(policy.writable, policy.denied_ports, policy.read_only),
            *argv,
        ]
    return bwrap_argv(argv, policy)


HOST_SKILL_SUBDIRS = (".pi/agent/skills", ".claude/skills")


def hidden_skill_dirs(writable: Sequence[Path]) -> list[str]:
    """Return the host's user skill dirs, or none when the cell's writable paths contain the host home."""
    home = paths.live_home().resolve()
    if any(path.resolve() in (home, *home.parents) for path in writable):
        return []
    return [str(home / sub) for sub in HOST_SKILL_SUBDIRS]


LINUX_TEMP_DIRS = ("/tmp", "/var/tmp")


def _temp_dirs() -> list[str]:
    """Return the host temp dirs and the cell work dir, outermost first, that hold other cells' roots."""
    dirs = {Path(tempfile.gettempdir()).resolve(), paths.work_dir().resolve()}
    dirs.update(Path(path) for path in LINUX_TEMP_DIRS if Path(path).exists())
    return [str(path) for path in sorted(dirs, key=lambda path: len(path.parts))]


def bwrap_argv(command: Sequence[str], policy: SandboxPolicy) -> list[str]:
    """Return the bwrap command that runs `command` with fresh empty temp dirs and only the policy's paths writable.

    The sandbox cannot filter ports on Linux, so `policy.denied_ports` has no effect there.
    """
    binds = [str(path.resolve()) for path in policy.writable]
    read_only = [str(path.resolve()) for path in policy.read_only]
    mount = (
        [
            "--bind",
            str(policy.mount[0]),
            str(policy.mount[1]),
            "--chdir",
            str(policy.mount[1] / "workspace"),
        ]
        if policy.mount
        else []
    )
    return [
        "bwrap",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--die-with-parent",
        "--unshare-pid",
        *(arg for path in _temp_dirs() for arg in ("--tmpfs", path)),
        *(arg for path in binds for arg in ("--bind", path, path)),
        *mount,
        *(arg for path in read_only for arg in ("--ro-bind", path, path)),
        *(
            arg
            for path in hidden_skill_dirs(policy.writable)
            for arg in ("--tmpfs", path)
        ),
        "--",
        *command,
    ]


MACOS_TEMP_DIRS = ("/private/tmp", "/private/var/folders", "/dev")


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def macos_profile(
    writable: Sequence[Path],
    denied_ports: Sequence[int],
    read_only: Sequence[Path] = (),
) -> str:
    """Return a macOS sandbox profile that allows writes only to ``writable``, except under ``read_only``, and blocks ``denied_ports``."""
    paths = [str(path.resolve()) for path in writable]
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny file-write*)",
        "(deny signal)",
        "(allow signal (target same-sandbox))",
    ]
    lines.append("(allow file-write*")
    lines.extend(f"  (subpath {_quote(path)})" for path in (*MACOS_TEMP_DIRS, *paths))
    lines.append(")")
    lines.extend(
        f"(deny file-write* (subpath {_quote(str(path.resolve()))}))"
        for path in read_only
    )
    lines.extend(
        f"(deny file-read* (subpath {_quote(path)}))"
        for path in hidden_skill_dirs(writable)
    )
    lines.extend(
        f'(deny network-outbound (remote tcp "localhost:{port}"))'
        for port in denied_ports
    )
    return "\n".join(lines) + "\n"
