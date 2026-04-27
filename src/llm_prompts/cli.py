"""CLI entry point for llm-prompts."""

from __future__ import annotations

import argparse
import contextlib
import io
from importlib.resources import files
from pathlib import Path
import subprocess
import sys

_AGENTS = ("cline", "copilot", "kiro")


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
    for skill_src in [root / "shared" / "skills"] + [
        d / "shared" / "skills" for d in overlay_dirs
    ]:
        if skill_src.is_dir():
            for skill_dir in sorted(skill_src.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if skill_file.is_file():
                    sources.setdefault(f"skills/{skill_dir.name}", skill_file)

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


def _check_for_updates() -> bool:
    """Check configured tool sources for available upstream changes.

    Returns:
        True if any updates are available.
    """
    from .setup import CONFIG_PATH, _expand, _is_local_path, _load_config

    if not CONFIG_PATH.exists():
        return False

    tools = _load_config()
    has_updates = False

    for tool in tools:
        name = str(tool.get("name", ""))
        source = str(tool.get("source", ""))
        if not _is_local_path(source):
            continue
        repo = _expand(source)
        if not (repo / ".git").is_dir():
            continue
        # Fetch silently to update remote refs
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "--quiet"],
            check=False,
            capture_output=True,
        )
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD..@{u}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        count = int(result.stdout.strip())
        if count > 0:
            print(f"[{name}] {count} new commit(s) available")
            has_updates = True

    if not has_updates:
        print("All tools are up to date.")
    return has_updates


def _restart_memory_service() -> None:
    """Restart the mcp-memory background service if installed."""
    if sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.mcp-memory.plist"
        if plist.exists():
            uid = subprocess.run(
                ["id", "-u"], capture_output=True, text=True, check=False
            ).stdout.strip()
            subprocess.run(
                ["launchctl", "kickstart", "-k", f"gui/{uid}/com.mcp-memory"],
                check=False,
            )
            print("Restarted mcp-memory service.")
    else:
        unit = Path("/etc/systemd/system/mcp-memory.service")
        if unit.exists():
            subprocess.run(["sudo", "systemctl", "restart", "mcp-memory"], check=False)
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

    args = parser.parse_args()

    if args.command == "install":
        if not args.no_update:
            from .setup import CONFIG_PATH, has_remote_sources, run_setup

            if CONFIG_PATH.exists() and has_remote_sources():
                run_setup()
                result = subprocess.run(
                    [sys.argv[0], "install", args.agent]
                    + (["--verbose"] if args.verbose else [])
                    + (
                        ["--agent-config", args.agent_config]
                        if args.agent_config
                        else []
                    )
                    + ["--no-update"],
                )
                sys.exit(result.returncode)

        from .install import main as install_main

        agent_names = list(_AGENTS) if args.agent == "all" else [args.agent]
        install_main(agent_names, verbose=args.verbose)

        if args.agent_config:
            from .install import (
                patch_kiro_agent_config,
                try_install_hooks,
                try_install_memory,
            )
            from .manifest import write_manifest, read_manifest

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
        from .setup import CONFIG_PATH, has_remote_sources, run_setup

        manifest = read_manifest()
        if not manifest:
            print(
                "No installed agents found. Run `llm-prompts install <agent>` first.",
                file=sys.stderr,
            )
            sys.exit(1)

        if CONFIG_PATH.exists() and has_remote_sources():
            run_setup()

        from .install import main as install_main

        install_main(list(manifest))

        for name, entry in manifest.items():
            agent_config = entry.get("agent_config")
            if agent_config:
                from .install import (
                    patch_kiro_agent_config,
                    try_install_hooks,
                    try_install_memory,
                )

                patch_kiro_agent_config(agent_config)
                try_install_hooks(agent_config)
                try_install_memory(agent_config)

        _restart_memory_service()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
