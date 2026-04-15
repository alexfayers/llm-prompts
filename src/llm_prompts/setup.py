"""Setup command for installing llm-prompts and related tools."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

_CONFIG_DIR = Path.home() / ".config" / "llm-prompts"
CONFIG_PATH = _CONFIG_DIR / "config.toml"

_DEFAULT_CONFIG = """\
# llm-prompts setup configuration
# Run `llm-prompts setup` to install all tools with their overlays.

# Each [[tools]] entry is a package to install.
# `source` can be:
#   - A git URL (e.g. "git+https://github.com/user/repo.git")
#   - A PyPI package name (e.g. "llm-prompts")
#   - A local path (~/git/pkg or /abs/path) - installed as editable
#
# `overlays_for` lists which other tools this package plugs into.
# `standalone` = true means the tool also gets its own install (e.g. it has a CLI).

[[tools]]
name = "llm-prompts"
source = "git+https://github.com/alexfayers/llm-prompts.git"

# [[tools]]
# name = "mcp-memory"
# source = "git+https://github.com/alexfayers/mcp-memory.git"
# standalone = true
# overlays_for = ["llm-prompts"]
"""


def _is_local_path(source: str) -> bool:
    """Check if a source string refers to a local path."""
    return source.startswith(("~/", "/", "./", "../"))


def has_remote_sources() -> bool:
    """Check if any configured tool uses a non-local source."""
    tools = _load_config()
    return any(not _is_local_path(str(t.get("source", ""))) for t in tools)


def _expand(path_str: str) -> Path:
    """Expand ~ and resolve a path string."""
    return Path(path_str).expanduser().resolve()


def _detect_installer() -> str:
    """Detect the best available installer."""
    for name in ("uv", "pipx", "pip"):
        if shutil.which(name):
            return name
    print("No installer found. Install uv, pipx, or pip.", file=sys.stderr)
    sys.exit(1)


def _build_commands(
    tools: list[dict[str, object]], installer: str
) -> list[tuple[str, list[str], list[str] | None]]:
    """Build install commands for all core tools.

    Returns list of (tool_name, install_cmd, upgrade_cmd_or_None) tuples.
    """
    overlay_map: dict[str, list[dict[str, object]]] = {}
    for tool in tools:
        for target in tool.get("overlays_for", []):
            overlay_map.setdefault(str(target), []).append(tool)

    cores = [t for t in tools if not t.get("overlays_for") or t.get("standalone")]

    commands: list[tuple[str, list[str], list[str] | None]] = []
    for core in cores:
        name = str(core["name"])
        source = str(core["source"])
        overlays = overlay_map.get(name, [])
        install_cmd = _build_install_cmd(installer, source, overlays)
        upgrade_cmd = _build_upgrade_cmd(installer, name, source, overlays)
        commands.append((name, install_cmd, upgrade_cmd))

    return commands


def _source_args(installer: str, source: str, *, editable: bool) -> list[str]:
    """Build the source arguments for an installer."""
    local = _is_local_path(source)
    path = str(_expand(source)) if local else source

    if installer == "uv":
        if local and editable:
            return ["--editable", path]
        if local:
            return ["--with-editable", path]
        if editable:
            return [path]
        return ["--with", path]

    if installer == "pipx":
        if editable:
            if local:
                return ["--editable", path]
            return [path]
        if local:
            return ["--pip-args", f"--editable {path}"]
        return ["--pip-args", path]

    # pip
    if local:
        return ["--editable", path]
    return [path]


def _build_install_cmd(
    installer: str, core_source: str, overlays: list[dict[str, object]]
) -> list[str]:
    """Build a full install command."""
    if installer == "uv":
        cmd = ["uv", "tool", "install"]
        cmd.extend(_source_args(installer, core_source, editable=True))
        for overlay in overlays:
            src = str(overlay["source"])
            if _is_local_path(src):
                cmd.extend(["--with-editable", str(_expand(src))])
            else:
                cmd.extend(["--with", src])
        cmd.extend(["--reinstall", "--force"])
        return cmd

    if installer == "pipx":
        cmd = ["pipx", "install"]
        if _is_local_path(core_source):
            cmd.extend(["--editable", str(_expand(core_source))])
        else:
            cmd.append(core_source)
        cmd.append("--force")
        # pipx uses inject for extras
        return cmd

    # pip
    cmd = ["pip", "install"]
    cmd.extend(_source_args(installer, core_source, editable=True))
    for overlay in overlays:
        cmd.extend(_source_args(installer, str(overlay["source"]), editable=False))
    return cmd


def _build_upgrade_cmd(
    installer: str,
    name: str,
    core_source: str,
    overlays: list[dict[str, object]],
) -> list[str] | None:
    """Build a targeted upgrade command, or None if not supported."""
    if installer != "uv":
        return None
    remote_packages: list[str] = []
    if not _is_local_path(core_source):
        remote_packages.append(name)
    for overlay in overlays:
        if not _is_local_path(str(overlay["source"])):
            remote_packages.append(str(overlay["name"]))
    cmd = ["uv", "tool", "upgrade", name]
    for pkg in remote_packages:
        cmd.extend(["--reinstall-package", pkg])
    return cmd


def _load_config() -> list[dict[str, object]]:
    """Load and return the tools list from config."""
    if not CONFIG_PATH.exists():
        print(
            f"Config not found at {CONFIG_PATH}\n"
            f"Run `llm-prompts setup --init` to create one.",
            file=sys.stderr,
        )
        sys.exit(1)
    config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    tools = config.get("tools", [])
    if not isinstance(tools, list) or not tools:
        print("Config must contain at least one [[tools]] entry.", file=sys.stderr)
        sys.exit(1)
    return tools


def _validate_paths(tools: list[dict[str, object]]) -> list[str]:
    """Validate that all local source paths exist. Returns list of errors."""
    errors: list[str] = []
    for tool in tools:
        source = str(tool.get("source", ""))
        if _is_local_path(source) and not _expand(source).is_dir():
            errors.append(f"[{tool.get('name')}] Path does not exist: {source}")
    return errors


def init_config() -> None:
    """Create a starter config file."""
    if CONFIG_PATH.exists():
        print(f"Config already exists at {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_DEFAULT_CONFIG, encoding="utf-8")
    print(f"Created {CONFIG_PATH}")
    print("Edit it to add your tools and overlay paths, then run `llm-prompts setup`.")


def run_setup(tool_filter: str | None = None, *, dry_run: bool = False) -> None:
    """Install all configured tools with their overlays."""
    tools = _load_config()
    errors = _validate_paths(tools)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        sys.exit(1)

    installer = _detect_installer()
    commands = _build_commands(tools, installer)

    if tool_filter:
        commands = [(n, i, u) for n, i, u in commands if n == tool_filter]
        if not commands:
            print(f"No tool named '{tool_filter}' in config.", file=sys.stderr)
            sys.exit(1)

    failed: list[str] = []
    for name, install_cmd, upgrade_cmd in commands:
        if upgrade_cmd:
            if dry_run:
                print(f"\n[{name}] {' '.join(upgrade_cmd)}")
                print(f"[{name}] (fallback) {' '.join(install_cmd)}")
                continue
            print(f"\n[{name}] {' '.join(upgrade_cmd)}")
            result = subprocess.run(
                upgrade_cmd, check=False, capture_output=True, text=True
            )
            if result.returncode == 0:
                if "Nothing to upgrade" not in result.stdout:
                    print(result.stdout, end="")
                continue
            print(result.stdout, end="")
            print(f"[{name}] Upgrade failed, falling back to full install...")

        print(f"\n[{name}] {' '.join(install_cmd)}")
        if not dry_run:
            result = subprocess.run(install_cmd, check=False)
            if result.returncode != 0:
                failed.append(name)

    if failed:
        print(f"\nFailed: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)
    if not dry_run and commands:
        print("\nAll tools installed successfully.")
