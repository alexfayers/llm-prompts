"""CLI entry point for llm-prompts."""

from __future__ import annotations

import argparse
import contextlib
import io
import shutil
import subprocess
import sys
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from .setup import (
    _GIT_TIMEOUT,
    _extract_git_url,
    _format_update_message,
    _remote_commit_subjects,
    _remote_head,
)

if TYPE_CHECKING:
    from .manifest import AgentManifest
    from .size_guard import Artifact

_AGENTS = ("cline", "copilot", "kiro", "claude-code", "codex")
_MEMORY_TOOL = "mcp-memory"


def _get_root_dir() -> Path:
    """Return the llm-prompts package data directory."""
    return Path(str(files("llm_prompts") / "prompts"))


def _collect_sources(agent: str) -> dict[str, Path]:
    """Collect source files for an agent, respecting overlay priority.

    Returns a dict mapping destination filename to source path. Overlays
    take priority over shared sources, and agent-specific sources are
    added if they don't exist in shared.
    """
    from .install import _discover_overlay_paths

    root = _get_root_dir()

    with contextlib.redirect_stderr(io.StringIO()):
        overlay_dirs = _discover_overlay_paths()

    sources: dict[str, Path] = {}

    for subdir in ("rules", "workflows"):
        # Overlay sources (highest priority)
        for overlay_dir in overlay_dirs:
            overlay_src = overlay_dir / "shared" / subdir
            if overlay_src.is_dir():
                for f in sorted(overlay_src.glob("*.md")):
                    sources.setdefault(f"{subdir}/{f.name}", f)

        # Shared sources
        shared_src = root / "shared" / subdir
        if shared_src.is_dir():
            for f in sorted(shared_src.glob("*.md")):
                sources.setdefault(f"{subdir}/{f.name}", f)

        # Agent-specific sources (only if not in shared)
        agent_src = root / agent / subdir
        if agent_src.is_dir():
            for f in sorted(agent_src.glob("*.md")):
                sources.setdefault(f"{subdir}/{f.name}", f)

        # Overlay agent-specific sources
        for overlay_dir in overlay_dirs:
            overlay_agent_src = overlay_dir / agent / subdir
            if overlay_agent_src.is_dir():
                for f in sorted(overlay_agent_src.glob("*.md")):
                    sources.setdefault(f"{subdir}/{f.name}", f)

    # Skills
    for skill_src in [d / "shared" / "skills" for d in overlay_dirs] + [
        root / "shared" / "skills"
    ]:
        if skill_src.is_dir():
            for skill_dir in sorted(skill_src.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if skill_file.is_file():
                    sources.setdefault(f"skills/{skill_dir.name}", skill_file)

    # Agents (claude-code only)
    if agent == "claude-code":
        for agents_src in [d / "claude-code" / "agents" for d in overlay_dirs] + [
            root / "claude-code" / "agents"
        ]:
            if agents_src.is_dir():
                for f in sorted(agents_src.glob("*.md")):
                    sources.setdefault(f"agents/{f.name}", f)

    return sources


def _print_sources(agent: str) -> None:
    """Print source file paths for an agent."""
    sources = _collect_sources(agent)
    if not sources:
        print(f"No sources found for agent '{agent}'.")
        return

    current_section = ""
    for key in sorted(sources):
        section = key.split("/")[0]
        if section != current_section:
            if current_section:
                print()
            print(f"{section}:")
            current_section = section
        print(f"  {sources[key]}")


def _size_guard_roots() -> list[Path]:
    """Return this package's own prompts dir plus every discovered overlay's.

    Used by the `check` subcommand, which measures the full checked union a
    real install would see - unlike the pytest suite, which is confined to
    this package's own root (see `size_guard`'s module docstring).
    """
    from .install import _discover_overlay_paths

    with contextlib.redirect_stderr(io.StringIO()):
        overlay_dirs = _discover_overlay_paths()
    return [_get_root_dir(), *overlay_dirs]


def _print_parked_state(artifacts: list[Artifact]) -> None:
    """Print one visibility line per metric with artifacts still over final.

    Args:
        artifacts: Every measured artifact from a `size_guard.check()` run.
    """
    from .size_guard import parked_state_lines

    for line in parked_state_lines(artifacts):
        print(line)


def _run_size_check() -> None:
    """Run the prompt-size guard against the full checked union and report."""
    from .size_guard import check as run_size_check

    result = run_size_check(_size_guard_roots())
    print(result.report)
    if not result.passed:
        sys.exit(1)
    _print_parked_state(result.artifacts)
    for line in result.stale:
        print(line)


def _get_installed_commit(package_name: str) -> str | None:
    """Get the installed commit hash from direct_url.json in a uv tool env."""
    import json

    uv_tools = Path.home() / ".local" / "share" / "uv" / "tools"
    dist_name = package_name.replace("-", "_")

    search_dirs = [uv_tools / package_name, uv_tools / "llm-prompts"]
    for tools_dir in search_dirs:
        if not tools_dir.is_dir():
            continue
        for dist_info in tools_dir.rglob(f"{dist_name}-*.dist-info/direct_url.json"):
            try:
                data = json.loads(dist_info.read_text(encoding="utf-8"))
                vcs_info = data.get("vcs_info", {})
                commit_id = vcs_info.get("commit_id")
                if commit_id:
                    return commit_id
            except (OSError, json.JSONDecodeError):
                continue
    return None


def _remote_source_messages(name: str, source: str) -> list[str]:
    """Return update-availability messages for a remote git source.

    Returns:
        Message lines describing available updates, or an empty list.
    """
    git_url = _extract_git_url(source)
    if not git_url:
        return []

    installed_commit = _get_installed_commit(name)
    if not installed_commit:
        return [f"[{name}] not installed (run `llm-prompts setup` first)"]

    remote_commit = _remote_head(git_url, None)
    if remote_commit is None or remote_commit == installed_commit:
        return []

    subjects = _remote_commit_subjects(git_url, installed_commit, remote_commit)
    return _format_update_message(name, subjects, installed_commit, remote_commit)


def _local_source_messages(name: str, source: str) -> list[str]:
    """Return update-availability messages for a local-path git source.

    Returns:
        Message lines describing available updates, or an empty list.
    """
    from .setup import _expand

    repo = _expand(source)
    if not (repo / ".git").is_dir():
        return []

    subprocess.run(
        ["git", "-C", str(repo), "fetch", "--quiet"],
        check=False,
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", "HEAD..@{u}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    )
    if result.returncode != 0:
        return []

    count = int(result.stdout.strip())
    if count == 0:
        return []

    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--pretty=format:%s", "HEAD..@{u}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    )
    subjects = log.stdout.splitlines() if log.returncode == 0 else None
    return _format_update_message(name, subjects)


class _PullOutcome(NamedTuple):
    """The result of pulling one tool source."""

    name: str
    changed: bool
    messages: list[str]


def _pull_one_local_source(name: str, source: str) -> _PullOutcome:
    """Pull upstream changes for a single local-path tool source.

    Args:
        name: The source name, used in the messages.
        source: The configured source string.

    Returns:
        Whether the source moved, and message lines describing the pull outcome.
    """
    from .setup import _expand, _is_local_path

    unchanged = _PullOutcome(name, False, [])
    if not _is_local_path(source):
        return unchanged
    repo = _expand(source)
    if not (repo / ".git").is_dir():
        return unchanged
    subprocess.run(
        ["git", "-C", str(repo), "fetch", "--quiet"],
        check=False,
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", "HEAD..@{u}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT,
    )
    if result.returncode != 0:
        return unchanged
    count = int(result.stdout.strip())
    if count == 0:
        return unchanged
    pull = subprocess.run(
        ["git", "-C", str(repo), "pull", "--ff-only", "--quiet"],
        check=False,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )
    if pull.returncode == 0:
        return _PullOutcome(name, True, [f"[{name}] pulled {count} new commit(s)"])
    rebase = subprocess.run(
        ["git", "-C", str(repo), "rebase", "--quiet", "@{u}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )
    if rebase.returncode == 0:
        return _PullOutcome(
            name,
            True,
            [f"[{name}] rebased local commits onto {count} new commit(s)"],
        )
    subprocess.run(
        ["git", "-C", str(repo), "rebase", "--abort"],
        check=False,
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    return _PullOutcome(
        name,
        False,
        [
            f"[{name}] {count} new commit(s) available but rebase failed",
            f"  {rebase.stderr.strip()}",
        ],
    )


def _pull_local_sources() -> set[str]:
    """Pull upstream changes for all local-path tool sources in parallel.

    Returns:
        The names of the tool sources that actually moved.
    """
    from functools import partial

    from .setup import CONFIG_PATH, _load_config, _run_parallel_ordered

    if not CONFIG_PATH.exists():
        return set()

    pulls: list[Callable[[], _PullOutcome]] = [
        partial(
            _pull_one_local_source,
            str(tool.get("name", "")),
            str(tool.get("source", "")),
        )
        for tool in _load_config()
    ]

    changed: set[str] = set()
    for outcome in _run_parallel_ordered(pulls):
        for line in outcome.messages:
            print(line)
        if outcome.changed:
            changed.add(outcome.name)
    return changed


def _collect_update_messages() -> list[str]:
    """Collect update-availability messages across all configured tool sources.

    Returns:
        Message lines describing available updates, in config order.
    """
    from functools import partial

    from .plugins import _load_plugins, plugin_source_messages
    from .setup import CONFIG_PATH, _is_local_path, _load_config, _run_parallel_ordered

    if not CONFIG_PATH.exists():
        return []

    checks: list[Callable[[], list[str]]] = []
    for tool in _load_config():
        name = str(tool.get("name", ""))
        source = str(tool.get("source", ""))
        if _is_local_path(source):
            checks.append(partial(_local_source_messages, name, source))
        else:
            checks.append(partial(_remote_source_messages, name, source))
    for plugin in _load_plugins():
        checks.append(partial(plugin_source_messages, plugin))

    messages: list[str] = []
    for result in _run_parallel_ordered(checks):
        messages.extend(result)
    return messages


def _check_for_updates() -> bool:
    """Check configured tool sources for available upstream changes.

    Returns:
        True if any updates are available.
    """
    messages = _collect_update_messages()
    for message in messages:
        print(message)
    if not messages:
        print("All tools are up to date.")
    return bool(messages)


def _auto_migrate_memory_db() -> None:
    """Consolidate a split mcp-memory database onto the default path.

    TODO(remove later): transitional self-heal for machines whose service was set up with a
    custom --db-path, which the hook plugin does not inherit (it reads the default). Idempotent
    - a no-op once the DB is already at the default. Remove once all machines are migrated.
    """
    binary = shutil.which("mcp-memory")
    if binary:
        subprocess.run([binary, "migrate-db"], check=False)


def _reconfigure_agents(
    manifest: dict[str, AgentManifest], *, memory_changed: bool
) -> None:
    """Re-apply hook, memory and agent-config wiring for every installed agent.

    Args:
        manifest: The installed-agent manifest.
        memory_changed: Whether the mcp-memory source moved, gating the memory wiring.
    """
    from .install import (
        patch_kiro_agent_config,
        try_allow_update_claude_code,
        try_install_hooks,
        try_install_hooks_claude_code,
        try_install_memory,
        try_install_memory_claude_code,
        try_install_memory_codex,
    )

    if "claude-code" in manifest:
        try_install_hooks_claude_code()
        if memory_changed:
            try_install_memory_claude_code()
        try_allow_update_claude_code()

    if "codex" in manifest and memory_changed:
        try_install_memory_codex()

    for entry in manifest.values():
        agent_config = entry.get("agent_config")
        if agent_config:
            patch_kiro_agent_config(agent_config)
            try_install_hooks(agent_config)
            if memory_changed:
                try_install_memory(agent_config)


def _restart_memory_service() -> None:
    """Restart the mcp-memory background service if installed."""
    binary = shutil.which("mcp-memory")
    if binary:
        subprocess.run([binary, "restart"], check=False)
        print("Restarted mcp-memory service.")


def main() -> None:
    """Run the llm-prompts CLI."""
    parser = argparse.ArgumentParser(
        prog="llm-prompts",
        description="Manage LLM prompt rules, workflows, and skills.",
    )
    subparsers = parser.add_subparsers(dest="command")
    install_parser = subparsers.add_parser(
        "install",
        help="Install rules, workflows, and skills. Auto-updates remote sources first.",
    )
    install_parser.add_argument(
        "agent",
        choices=[*_AGENTS, "all"],
        help="Agent to install for, or 'all'.",
    )
    install_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show debug output."
    )
    install_parser.add_argument(
        "--no-update",
        action="store_true",
        help="Skip running setup before installing.",
    )
    install_parser.add_argument(
        "--agent-config",
        metavar="PATH",
        help="Kiro agent JSON to patch with resource entries.",
    )
    source_parser = subparsers.add_parser(
        "source", help="Show source file locations for an agent."
    )
    source_parser.add_argument(
        "agent",
        choices=_AGENTS,
        help="Agent to show sources for.",
    )
    setup_parser = subparsers.add_parser(
        "setup", help="Install all configured tools with their overlay packages."
    )
    setup_parser.add_argument(
        "--init", action="store_true", help="Create a starter config file."
    )
    setup_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show commands without running them.",
    )
    setup_parser.add_argument(
        "tool", nargs="?", help="Install only this tool (by name from config)."
    )
    update_parser = subparsers.add_parser(
        "update",
        help="Update all installed agents and restart services.",
    )
    update_parser.add_argument(
        "--check",
        action="store_true",
        help="Report available updates without applying them.",
    )
    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Remove installed rules, workflows, skills, and agent config patches.",
    )
    uninstall_parser.add_argument(
        "agent",
        choices=[*_AGENTS, "all"],
        help="Agent to uninstall, or 'all'.",
    )
    uninstall_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show debug output."
    )
    subparsers.add_parser(
        "check",
        help="Check prompt sizes against size_limits.py's thresholds.",
    )

    args = parser.parse_args()

    if args.command == "install":
        if not args.no_update:
            from .setup import (
                CONFIG_PATH,
                detect_stale_local_tools,
                has_remote_sources,
                run_setup,
            )

            stale = detect_stale_local_tools()
            if CONFIG_PATH.exists() and (has_remote_sources() or stale):
                run_setup(force_reinstall=stale or None)
                result = subprocess.run(
                    [sys.argv[0], "install", args.agent]
                    + (["--verbose"] if args.verbose else [])
                    + (
                        ["--agent-config", args.agent_config]
                        if args.agent_config
                        else []
                    )
                    + ["--no-update"],
                    check=False,
                )
                sys.exit(result.returncode)

        from .install import main as install_main

        agent_names = list(_AGENTS) if args.agent == "all" else [args.agent]
        install_main(agent_names, verbose=args.verbose)

        if "claude-code" in agent_names:
            from .install import (
                try_allow_update_claude_code,
                try_install_hooks_claude_code,
                try_install_memory_claude_code,
            )

            try_install_hooks_claude_code()
            try_install_memory_claude_code()
            try_allow_update_claude_code()

        if "codex" in agent_names:
            from .install import try_install_memory_codex

            try_install_memory_codex()

        if args.agent_config:
            from .install import (
                patch_kiro_agent_config,
                try_install_hooks,
                try_install_memory,
            )
            from .manifest import read_manifest, write_manifest

            patch_kiro_agent_config(args.agent_config)
            try_install_hooks(args.agent_config)
            try_install_memory(args.agent_config)

            for name in agent_names:
                existing = read_manifest().get(name, {})
                write_manifest(
                    name,
                    existing.get("files", []),
                    agent_config=args.agent_config,
                )
    elif args.command == "source":
        _print_sources(args.agent)
    elif args.command == "setup":
        from .setup import init_config, run_setup

        if args.init:
            init_config()
        else:
            run_setup(args.tool, dry_run=args.dry_run)
    elif args.command == "update":
        if args.check:
            _check_for_updates()
            sys.exit(0)

        from .manifest import read_manifest
        from .setup import (
            CONFIG_PATH,
            detect_stale_local_tools,
            has_remote_sources,
            run_setup,
        )

        manifest = read_manifest()
        if not manifest:
            print(
                "No installed agents found. Run `llm-prompts install <agent>` first.",
                file=sys.stderr,
            )
            sys.exit(1)

        changed_sources = _pull_local_sources()

        from .plugins import pull_plugin_sources

        pull_plugin_sources()

        memory_commit = _get_installed_commit(_MEMORY_TOOL)
        stale = detect_stale_local_tools()
        if CONFIG_PATH.exists() and (has_remote_sources() or stale):
            run_setup(force_reinstall=stale or None)
        if _get_installed_commit(_MEMORY_TOOL) != memory_commit:
            changed_sources.add(_MEMORY_TOOL)

        from .install import main as install_main

        install_main(list(manifest))

        memory_changed = _MEMORY_TOOL in changed_sources
        if changed_sources:
            _reconfigure_agents(manifest, memory_changed=memory_changed)
        if memory_changed:
            _auto_migrate_memory_db()
            _restart_memory_service()
    elif args.command == "uninstall":
        from .install import uninstall

        uninstall(None if args.agent == "all" else [args.agent], verbose=args.verbose)
    elif args.command == "check":
        _run_size_check()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
