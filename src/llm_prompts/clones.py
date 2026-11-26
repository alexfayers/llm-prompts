"""Replace git-sourced tools with local clones, so edits to a tool's rules survive updates."""

from __future__ import annotations

import base64
import csv
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from . import home
from .exit_reason import ExitReason
from .setup import (
    GIT_TIMEOUT,
    _dist_infos,
    _extract_git_url,
    _inline_ref,
    _normalize_origin,
    config_path,
    package_name,
    release_version,
)

CLONE_TIMEOUT = 2 * GIT_TIMEOUT
_MAX_EDITS_SHOWN = 3


def clones_dir() -> Path:
    """Return the directory holding one clone per migrated tool."""
    return home.user_home() / ".llm-prompts"


def _tilde(path: Path) -> str:
    """Return ``path`` as ``~/...`` when it is under the user's home directory."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=GIT_TIMEOUT,
    )


def _warn(name: str, message: str) -> None:
    print(f"[{name}] {message}", file=sys.stderr)


def _keep_git_source(name: str, reason: str) -> None:
    _warn(name, f"{reason}. Keeping its git source.")


def _edited_files(dist_info: Path) -> list[str]:
    """Return the files of an installed package that differ from the hashes in its RECORD."""
    edited = []
    for path, digest in (
        row[:2]
        for row in csv.reader(
            (dist_info / "RECORD").read_text(encoding="utf-8").splitlines()
        )
        if len(row) >= 2
    ):
        algorithm, _, expected = digest.partition("=")
        file = dist_info.parent / path
        if (
            algorithm != "sha256"
            or path.startswith("..")
            or "__pycache__" in file.parts
        ):
            continue
        try:
            actual = base64.urlsafe_b64encode(
                hashlib.sha256(file.read_bytes()).digest()
            )
        except OSError:
            edited.append(path)
            continue
        if actual.rstrip(b"=").decode() != expected:
            edited.append(path)
    return edited


def _installed_edits(owner: dict[str, Any], tool: dict[str, Any]) -> list[str]:
    """Return the files of the tool's copy in the shared env owned by ``owner`` that were edited after the install."""
    for dist_info in _dist_infos(package_name(owner), package_name(tool)):
        try:
            return _edited_files(dist_info)
        except (OSError, csv.Error, ValueError):
            continue
    return []


def _same_origin(clone: Path, git_url: str) -> bool:
    """Return whether ``clone`` is a git repository whose origin is ``git_url``."""
    result = _git(clone, "remote", "get-url", "origin")
    return result.returncode == 0 and _normalize_origin(
        result.stdout.strip()
    ) == _normalize_origin(git_url)


def _is_taken(path: Path) -> bool:
    """Return whether ``path`` holds anything beyond an empty directory."""
    return path.exists() and not (path.is_dir() and not any(path.iterdir()))


def _clone(name: str, git_url: str, dest: Path) -> bool:
    """Clone ``git_url`` to ``dest`` at its highest release tag, and return whether it worked."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["git", "clone", "--quiet", git_url, str(dest)],
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True,
            text=True,
            check=False,
            timeout=CLONE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        _keep_git_source(name, f"clone took longer than {CLONE_TIMEOUT} seconds")
        return False
    except OSError:
        _keep_git_source(name, "clone failed")
        return False
    if result.returncode != 0:
        _keep_git_source(name, "clone failed")
        return False
    releases = {
        version: tag
        for tag in _git(dest, "tag", "--list", "v*").stdout.split()
        if (version := release_version(tag))
    }
    if releases:
        _git(dest, "reset", "--hard", "--quiet", releases[max(releases)])
    return True


def _repoint(text: str, name: str, source: str) -> str | None:
    """Return the config ``text`` with tool ``name``'s source set to ``source``, or ``None`` if only a change to anything else would do it."""
    blocks = re.split(r"(?m)^(?=\[)", text)
    for index, block in enumerate(blocks):
        if block.startswith("[[tools]]") and re.search(
            rf"""(?m)^name\s*=\s*["']{re.escape(name)}["']\s*(?:#.*)?$""", block
        ):
            blocks[index], count = re.subn(
                r"""(?m)^(source\s*=\s*)(?:"(?:[^"\\\n]|\\.)*"|'[^'\n]*')""",
                lambda match: f'{match[1]}"{source}"',
                block,
                count=1,
            )
            if count:
                return _checked("".join(blocks), text, name, source)
    return None


def _checked(edited: str, original: str, name: str, source: str) -> str | None:
    """Return ``edited`` if it parses as ``original`` with only tool ``name``'s source changed, else ``None``."""
    try:
        expected = tomllib.loads(original)
        actual = tomllib.loads(edited)
    except tomllib.TOMLDecodeError:
        return None
    for tool in expected.get("tools", []):
        if tool.get("name") == name:
            tool["source"] = source
    return edited if actual == expected else None


def _write_config(text: str) -> None:
    """Replace the config file with ``text`` atomically, keeping its permissions."""
    descriptor, temp = tempfile.mkstemp(dir=config_path().parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        shutil.copymode(config_path(), temp)
        Path(temp).replace(config_path())
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _migratable(tool: dict[str, Any]) -> bool:
    """Return whether ``tool`` has a git source that follows releases."""
    source = str(tool.get("source", ""))
    return (
        _extract_git_url(source) is not None
        and not tool.get("ref")
        and not _inline_ref(source)
    )


def block_on_installed_edits(
    tools: list[dict[str, Any]], *, dry_run: bool = False
) -> None:
    """Warn of each tool whose installed copy has edits, and stop the run before it reinstalls them away.

    A reinstall of the env every tool shares replaces every installed copy, so one tool with edits stops the whole run.
    Only git-sourced tools are checked: they are the ones a release or a migration changes.

    Args:
        tools: The configured tools.
        dry_run: Warn only, because a dry run changes nothing.

    Raises:
        ExitReason: When a tool has edits and ``dry_run`` is false.
    """
    if not any(_extract_git_url(str(tool.get("source", ""))) for tool in tools):
        return
    found = False
    for tool in tools:
        if edits := _installed_edits(tools[0], tool):
            shown = ", ".join(edits[:_MAX_EDITS_SHOWN])
            more = len(edits) - _MAX_EDITS_SHOWN
            _warn(
                str(tool["name"]),
                f"its installed copy has edits a reinstall would discard ({shown}{f', and {more} more' if more > 0 else ''}). "
                "Move them into a clone of its repository and point its source at the clone, then rerun setup.",
            )
            found = True
    if found and not dry_run:
        raise ExitReason("installed_edits")


def migrate(tools: list[dict[str, Any]], *, dry_run: bool = False) -> bool:
    """Clone each git-sourced tool into the clones directory and point its config ``source`` at the clone.

    A tool is left on its git source when it follows a ref, when the clone's folder holds anything but a clone of the same repository,
    or when the clone or the config edit fails. An existing clone is reused as it is.

    Args:
        tools: The configured tools.
        dry_run: Print what would change without cloning or editing the config.

    Returns:
        True if the config file changed.
    """
    if not any(_migratable(tool) for tool in tools):
        return False
    text = config_path().read_bytes().decode("utf-8")
    changed = False
    for tool in tools:
        if not _migratable(tool):
            continue
        name, source = str(tool["name"]), str(tool["source"])
        git_url = str(_extract_git_url(source))
        dest = clones_dir() / name
        new_source = _tilde(dest)
        if dry_run:
            print(f'[{name}] would clone it to {dest} and set source = "{new_source}"')
            continue
        if _is_taken(dest):
            if not _same_origin(dest, git_url):
                _keep_git_source(name, f"{dest} is not a clone of its repository")
                continue
            print(f"[{name}] reusing the clone at {dest}")
        elif _clone(name, git_url, dest):
            print(f"[{name}] cloned it to {dest}")
        else:
            continue
        if (repointed := _repoint(text, name, new_source)) is None:
            _keep_git_source(name, f"could not edit its source line in {config_path()}")
            continue
        text, changed = repointed, True
        print(f'[{name}] set source = "{new_source}" in {config_path()}')
    if changed:
        _write_config(text)
    return changed
