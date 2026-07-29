"""Claude-plugin git sources: tracked checkouts and skill discovery."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
import subprocess
import tomllib
from typing import Any

from .setup import (
    _CONFIG_DIR,
    _GIT_TIMEOUT,
    _extract_git_url,
    _remote_update_message,
    _run_parallel_ordered,
)

_PLUGIN_DIR = _CONFIG_DIR / "plugin-sources"


def _load_plugins() -> list[dict[str, Any]]:
    """Load the plugins list from config.

    Returns:
        The ``[[plugins]]`` entries, or an empty list if config or the key is
        absent. Independent of the ``[[tools]]`` list, which is optional here.
    """
    from .setup import CONFIG_PATH

    if not CONFIG_PATH.exists():
        return []
    config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    plugins = config.get("plugins", [])
    if not isinstance(plugins, list):
        return []
    return plugins


def _validate_plugins(plugins: list[dict[str, Any]]) -> list[str]:
    """Validate plugin entries.

    Args:
        plugins: Parsed ``[[plugins]]`` entries.

    Returns:
        Human-readable error strings; an empty list means all entries are valid.
    """
    errors: list[str] = []
    for plugin in plugins:
        name = str(plugin.get("name", "")).strip()
        if not name:
            errors.append(f"Plugin entry missing a name: {plugin}")
        source = str(plugin.get("source", ""))
        if not source or _extract_git_url(source) is None:
            errors.append(f"[{name}] plugin source must be a git URL: {source}")
    return errors


def _checkout_dir(name: str) -> Path:
    """Return the on-disk checkout directory for a plugin.

    Args:
        name: The plugin name.

    Returns:
        The path where the plugin's git checkout lives.
    """
    return _PLUGIN_DIR / name


def ensure_cloned(plugin: dict[str, Any]) -> Path | None:
    """Clone a plugin source if not already present, then checkout its ref.

    Args:
        plugin: A ``[[plugins]]`` entry with ``name``, ``source``, optional ``ref``.

    Returns:
        The checkout path, or ``None`` if git is unavailable or an operation
        failed (non-fatal: a broken plugin must not abort the whole install).
    """
    from .install import log

    name = str(plugin["name"])
    dest = _checkout_dir(name)
    if (dest / ".git").is_dir():
        return dest

    if shutil.which("git") is None:
        log("warn", f"[{name}] git not available; skipping clone")
        return None

    url = _extract_git_url(str(plugin["source"]))
    if url is None:
        log("error", f"[{name}] plugin source is not a git URL: {plugin.get('source')}")
        return None

    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", url, str(dest)],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    )
    if result.returncode != 0:
        log("error", f"[{name}] clone failed: {result.stderr.strip()}")
        return None

    ref = plugin.get("ref")
    if ref:
        checkout = subprocess.run(
            ["git", "-C", str(dest), "checkout", str(ref)],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT,
        )
        if checkout.returncode != 0:
            log(
                "error",
                f"[{name}] checkout of ref '{ref}' failed: {checkout.stderr.strip()}",
            )
            return None

    return dest


def _reset_target(checkout: Path, ref: str | None) -> str:
    """Determine the git ref to reset a checkout to.

    Args:
        checkout: The plugin checkout directory.
        ref: An explicit branch/tag/SHA, or ``None`` to track the remote default.

    Returns:
        The ref to pass to ``git reset --hard``.
    """
    if ref:
        return str(ref)
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--abbrev-ref", "origin/HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return "@{u}"


def _pull_one_plugin_source(plugin: dict[str, Any]) -> list[str]:
    """Refresh a single cloned plugin checkout to its upstream tip.

    Uses ``git fetch`` + ``git reset --hard`` (never pull/rebase) so the checkout
    survives upstream force-pushes and history rewrites. All git failures are
    non-fatal: a message is returned rather than raised.

    Args:
        plugin: A ``[[plugins]]`` entry with ``name``, ``source``, optional ``ref``.

    Returns:
        Message lines describing the update outcome, or an empty list when the
        checkout is missing or already up to date.
    """
    name = str(plugin.get("name", ""))
    checkout = _checkout_dir(name)
    if not (checkout / ".git").is_dir():
        return []

    before = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    ).stdout.strip()

    subprocess.run(
        ["git", "-C", str(checkout), "fetch", "--quiet"],
        check=False,
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    target = _reset_target(checkout, plugin.get("ref"))
    reset = subprocess.run(
        ["git", "-C", str(checkout), "reset", "--hard", target, "--quiet"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    )
    if reset.returncode != 0:
        return [f"[{name}] update failed: {reset.stderr.strip()}"]

    after = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    ).stdout.strip()
    if before != after:
        return [f"[{name}] updated to {after}"]
    return []


def pull_plugin_sources() -> None:
    """Refresh every cloned plugin checkout to its upstream tip, in parallel.

    All git failures are non-fatal: a note is printed and the other plugins are
    still processed. See :func:`_pull_one_plugin_source` for the per-checkout
    fetch/reset semantics.
    """
    from functools import partial

    pulls: list[Callable[[], list[str]]] = [
        partial(_pull_one_plugin_source, plugin) for plugin in _load_plugins()
    ]
    for result in _run_parallel_ordered(pulls):
        for line in result:
            print(line)


def plugin_source_messages(plugin: dict[str, Any]) -> list[str]:
    """Return update-availability messages for a plugin checkout.

    Args:
        plugin: A ``[[plugins]]`` entry with ``name``, ``source``, optional ``ref``.

    Returns:
        Message lines describing an available update, or an empty list.
    """
    name = str(plugin.get("name", ""))
    checkout = _checkout_dir(name)
    if not (checkout / ".git").is_dir():
        return [f"[{name}] not cloned (run `llm-prompts update`)"]

    git_url = _extract_git_url(str(plugin.get("source", "")))
    if git_url is None:
        return []

    local = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    )
    if local.returncode != 0:
        return []

    return _remote_update_message(
        name, local.stdout.strip(), git_url, plugin.get("ref")
    )


_IGNORED_COMPONENTS = ("commands", "agents", "hooks", ".mcp.json", ".lsp.json")


def discover_skills(checkout: Path, subset: list[str] | None) -> list[tuple[str, Path]]:
    """Discover skill directories within a plugin checkout.

    Args:
        checkout: The plugin's checkout directory.
        subset: Optional list of skill names to keep; ``None`` or empty keeps all.

    Returns:
        ``(name, directory)`` pairs, one per discovered skill. A skill's name is
        its leaf directory name, or the checkout name when ``SKILL.md`` sits at
        the checkout root.

    Raises:
        ValueError: If a name in ``subset`` matches no discovered skill.
    """
    from .install import log

    skills: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add(name: str, skill_dir: Path) -> None:
        if name in seen:
            log(
                "warn",
                f"Duplicate skill name '{name}' in {checkout.name}; skipping {skill_dir}",
            )
            return
        seen.add(name)
        skills.append((name, skill_dir))

    if (checkout / "SKILL.md").is_file():
        add(checkout.name, checkout)

    skills_dir = checkout / "skills"
    if skills_dir.is_dir():
        for skill_file in sorted(skills_dir.rglob("SKILL.md")):
            add(skill_file.parent.name, skill_file.parent)

    if not skills:
        log("warn", f"No skills (SKILL.md) found in {checkout.name}")

    for component in _IGNORED_COMPONENTS:
        if (checkout / component).exists():
            log(
                "warn",
                f"{checkout.name} contains '{component}', which is not yet supported",
            )

    if subset:
        available = {name for name, _ in skills}
        missing = [name for name in subset if name not in available]
        if missing:
            raise ValueError(
                f"Unknown skill name(s) {missing} for plugin '{checkout.name}'. "
                f"Available: {sorted(available)}"
            )
        skills = [(name, path) for name, path in skills if name in subset]

    return skills
