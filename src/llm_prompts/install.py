"""Install Cline and Copilot rules, workflows, skills, and prompts."""

from dataclasses import dataclass
from importlib.resources import files
import os
from pathlib import Path
import shutil
import sys
from typing import ClassVar, Literal

from .render_template import find_unreplaced_variables, render_template

LogLevel = Literal["debug", "info", "warn", "error", "success"]

_COLORS: dict[LogLevel, str] = {
    "debug": "\033[0;90m",
    "info": "\033[0;37m",
    "warn": "\033[0;33m",
    "error": "\033[0;31m",
    "success": "\033[0;32m",
}
_SYMBOLS: dict[LogLevel, str] = {
    "debug": "[.]",
    "info": "[>]",
    "warn": "[!]",
    "error": "[x]",
    "success": "[+]",
}
_PLAIN_SYMBOLS: dict[LogLevel, str] = {
    "debug": "[.]",
    "info": "[*]",
    "warn": "[-]",
    "error": "[!]",
    "success": "[+]",
}


_verbose = False


def log(level: LogLevel, message: str) -> None:
    """Log a message with appropriate formatting.

    Args:
        level: Log level.
        message: Message to print.
    """
    if level == "debug" and not _verbose:
        return
    if sys.stderr.isatty():
        print(f"{_COLORS[level]}{_SYMBOLS[level]} {message}\033[0;0m", file=sys.stderr)
    else:
        print(f"{_PLAIN_SYMBOLS[level]} {message}", file=sys.stderr)


def _vscode_user_dir() -> Path:
    """Return the VS Code user directory for the current platform.

    Returns:
        Path to the VS Code user directory.
    """
    home = Path.home()
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Code" / "User"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Code" / "User"
    return home / ".config" / "Code" / "User"


def _get_dirs() -> dict[str, dict[str, Path] | Path]:
    """Build destination directories used during installation.

    Returns:
        Mapping of installation destination names to paths.
    """
    home = Path.home()
    cline_base = (
        (home / "Cline") if sys.platform == "linux" else (home / "Documents" / "Cline")
    )
    cline_merged = home / ".cline_merged"
    vscode_user = _vscode_user_dir()
    return {
        "agents": home / ".agents",
        "cline_symlinks": {
            "rules": cline_base / "Rules",
            "workflows": cline_base / "Workflows",
        },
        "cline": {
            "rules": cline_merged / "rules",
            "workflows": cline_merged / "workflows",
        },
        "copilot": {
            "rules": home / ".copilot" / "instructions",
            "workflows": vscode_user / "prompts",
        },
        "kiro": {
            "rules": home / ".kiro" / "steering",
            "workflows": home / ".kiro" / "prompts",
        },
    }


def _read_text(path: Path) -> str:
    """Read UTF-8 text from disk.

    Args:
        path: Path to read.

    Returns:
        File content.
    """
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    """Write UTF-8 text to disk.

    Args:
        path: Destination path.
        content: Text to write.
    """
    path.write_text(content, encoding="utf-8")


def _discover_overlay_paths() -> list[Path]:
    """Discover overlay directories from installed packages via entry_points.

    Packages declare an ``llm_prompts`` entry point group where each entry
    point value is the package name. The prompts directory is resolved via
    ``importlib.resources.files(<package>) / "prompts"``.

    Returns:
        List of overlay directory paths from installed packages.
    """
    from importlib.metadata import entry_points

    paths: list[Path] = []
    for ep in entry_points(group="llm_prompts"):
        try:
            overlay_path = Path(str(files(ep.value) / "prompts"))
            if overlay_path.is_dir():
                log("info", f"[overlay] Discovered '{ep.name}' at {overlay_path}")
                paths.append(overlay_path)
            else:
                log(
                    "warn", f"[overlay] '{ep.name}' path does not exist: {overlay_path}"
                )
        except Exception as e:
            log("error", f"[overlay] Failed to load '{ep.name}': {e}")
    return paths


def _install_rendered(
    src: Path, dest: Path, vars_path: Path, target: str, label: str
) -> None:
    """Render and install a templated file.

    Args:
        src: Source template path.
        dest: Destination file path.
        vars_path: Variables JSON path.
        target: Render target.
        label: Log label for this file.
    """
    try:
        output = render_template(str(src), str(vars_path), target)
    except Exception as e:
        log("error", f"Failed to render {label}: {e}")
        return

    for var in find_unreplaced_variables(output):
        log("warn", f"Unreplaced variable '{{{{{var}}}}}' in {label}")

    if dest.exists():
        if _read_text(dest) == output:
            log("debug", f"{label} is up to date. Skipping.")
            return
        action = "Updated"
    else:
        action = "Installed"

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_text(dest, output)
        log("success", f"{action} {label}")
    except Exception as e:
        log("error", f"Failed to install {label}: {e}")
        if dest.exists():
            dest.unlink()


def _install_linked(src: Path, dest: Path, label: str) -> None:
    """Install a file by copying source content to destination.

    Args:
        src: Source file path.
        dest: Destination file path.
        label: Log label for this file.
    """
    if dest.exists() and not dest.is_symlink():
        if _read_text(dest) == _read_text(src):
            log("debug", f"{label} is up to date. Skipping.")
            return
        action = "Updated"
    else:
        if dest.is_symlink() and dest.resolve() == src.resolve():
            log("debug", f"{label} is up to date. Skipping.")
            return
        action = "Installed" if not dest.exists() else "Updated"

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        _write_text(dest, _read_text(src))
        log("success", f"{action} {label}")
    except Exception as e:
        log("error", f"Failed to install {label}: {e}")


@dataclass
class _Agent:
    """Agent installation configuration."""

    name: str
    root_dir: Path
    dirs: dict

    def vars_path(self) -> Path:
        """Return the path to the agent's variables JSON file."""
        return self.root_dir / self.name / "vars.json"

    def agent_src(self, subdir: str) -> Path:
        """Return the path to agent-specific source files for a content subdir."""
        return self.root_dir / self.name / subdir

    def dest_dir(self, subdir: str) -> Path:
        """Return the destination directory for a content subdir."""
        return self.dirs[self.name][subdir]

    def dest_name(self, src: Path, subdir: str) -> str:
        """Return the destination filename for a source file."""
        return src.name


class _CopilotAgent(_Agent):
    """Copilot agent with format-specific destination naming."""

    _SUFFIXES: ClassVar[dict[str, str]] = {
        "rules": "instructions",
        "workflows": "prompt",
    }

    def dest_name(self, src: Path, subdir: str) -> str:
        return f"{src.stem}.{self._SUFFIXES[subdir]}.md"


def _check_unmanaged(
    dest_dir: Path, managed: set[str], label: str, *, is_dir: bool = False
) -> None:
    """Warn about files or directories in dest_dir that are not in the managed set.

    Args:
        dest_dir: Destination directory to inspect.
        managed: Set of filenames/directory names that were installed.
        label: Human-readable label for log messages.
        is_dir: If True, check subdirectories; otherwise check files.
    """
    if not dest_dir.exists():
        return
    kind = "directory" if is_dir else "file"
    for item in sorted(dest_dir.iterdir()):
        if is_dir and not item.is_dir():
            continue
        if not is_dir and not item.is_file():
            continue
        if item.name not in managed:
            log("warn", f"Non-managed {kind} in {label}: {item.name}")


def _install_content(
    agent: _Agent,
    subdir: str,
    shared_src: Path,
    overlay_srcs: list[Path],
    overlay_agent_srcs: list[Path],
) -> set[str]:
    """Install shared and agent-specific content for one agent and content type.

    Args:
        agent: Agent configuration.
        subdir: Content subdirectory name (e.g. 'rules' or 'workflows').
        shared_src: Base shared source directory.
        overlay_srcs: Overlay shared source directories in priority order (first wins).
        overlay_agent_srcs: Overlay agent-specific source directories in priority order.

    Returns:
        Set of destination filenames that were installed.
    """
    dest_dir = agent.dest_dir(subdir)
    vars_path = agent.vars_path()
    target = agent.name

    log("info", f"[{target}] Installing {subdir}...")
    dest_dir.mkdir(parents=True, exist_ok=True)

    installed: set[str] = set()

    for overlay_src in overlay_srcs:
        if overlay_src.exists():
            for src in sorted(overlay_src.glob("*.md")):
                name = agent.dest_name(src, subdir)
                if name not in installed:
                    _install_rendered(
                        src, dest_dir / name, vars_path, target, f"{subdir}/{name}"
                    )
                    installed.add(name)

    for src in sorted(shared_src.glob("*.md")):
        name = agent.dest_name(src, subdir)
        if name not in installed:
            _install_rendered(
                src, dest_dir / name, vars_path, target, f"{subdir}/{name}"
            )
            installed.add(name)

    agent_src = agent.agent_src(subdir)
    if agent_src.exists():
        for src in sorted(agent_src.glob("*.md")):
            if not (shared_src / src.name).exists():
                name = src.name
                _install_linked(src, dest_dir / name, f"{subdir}/{name}")
                installed.add(name)

    for overlay_agent_src in overlay_agent_srcs:
        if overlay_agent_src.exists():
            for src in sorted(overlay_agent_src.glob("*.md")):
                name = agent.dest_name(src, subdir)
                if name not in installed:
                    _install_rendered(
                        src, dest_dir / name, vars_path, target, f"{subdir}/{name}"
                    )
                    installed.add(name)

    return installed


def _install_skills(skills_src: Path, agents_dir: Path, managed: set[str]) -> None:
    """Install Cline skills as symlinks in the agents directory.

    Args:
        skills_src: Source skills directory.
        agents_dir: Agents destination directory.
        managed: Set to accumulate installed skill names into.
    """
    if not skills_src.exists():
        return
    log("info", "[shared] Installing skills...")
    for skill_path in sorted(skills_src.iterdir()):
        if not skill_path.is_dir():
            continue
        if not (skill_path / "SKILL.md").is_file():
            continue
        skill_name = skill_path.name
        skill_dest = agents_dir / "skills" / skill_name
        try:
            if skill_dest.is_symlink() and skill_dest.resolve() == skill_path.resolve():
                log("debug", f"Skill '{skill_name}' is up to date. Skipping.")
                managed.add(skill_name)
                continue
            already_existed = skill_dest.exists() or skill_dest.is_symlink()
            if already_existed:
                if skill_dest.is_symlink():
                    skill_dest.unlink()
                else:
                    shutil.rmtree(skill_dest)
            skill_dest.parent.mkdir(parents=True, exist_ok=True)
            skill_dest.symlink_to(skill_path)
            managed.add(skill_name)
            log(
                "success",
                f"{'Updated' if already_existed else 'Installed'} skill: {skill_name}",
            )
        except Exception as e:
            log("error", f"Failed to install skill '{skill_name}': {e}")


def _symlink_dir(source: Path, dest: Path) -> None:
    """Replace a directory with a symlink to source.

    Args:
        source: Source directory.
        dest: Destination symlink path.
    """
    if dest.is_symlink() and dest.resolve() == source.resolve():
        log("debug", "Directory symlink is up to date. Skipping.")
        return

    try:
        if dest.exists():
            if dest.is_symlink():
                dest.unlink()
            else:
                shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(source)
    except Exception as e:
        log("error", f"Failed to symlink {source} to {dest}: {e}")


def main(agent_names: list[str] | None = None, *, verbose: bool = False) -> None:
    """Run the installation workflow.

    Args:
        agent_names: Agents to install for. None means all.
        verbose: Show debug-level output.
    """
    global _verbose  # noqa: PLW0603
    _verbose = verbose
    root_dir = Path(str(files("llm_prompts") / "prompts"))
    dirs = _get_dirs()

    overlay_dirs = _discover_overlay_paths()

    all_agents: dict[str, _Agent] = {
        "cline": _Agent(name="cline", root_dir=root_dir, dirs=dirs),
        "copilot": _CopilotAgent(name="copilot", root_dir=root_dir, dirs=dirs),
        "kiro": _Agent(name="kiro", root_dir=root_dir, dirs=dirs),
    }
    targets = agent_names or list(all_agents)

    if "cline" in targets:
        managed_skills: set[str] = set()
        _install_skills(root_dir / "shared" / "skills", dirs["agents"], managed_skills)
        for overlay_dir in overlay_dirs:
            _install_skills(
                overlay_dir / "shared" / "skills", dirs["agents"], managed_skills
            )
        _check_unmanaged(
            dirs["agents"] / "skills", managed_skills, "skills", is_dir=True
        )

    if "kiro" in targets:
        managed_kiro_skills: set[str] = set()
        _install_skills(
            root_dir / "shared" / "skills",
            dirs["kiro"]["rules"].parent,
            managed_kiro_skills,
        )
        for overlay_dir in overlay_dirs:
            _install_skills(
                overlay_dir / "shared" / "skills",
                dirs["kiro"]["rules"].parent,
                managed_kiro_skills,
            )
        _check_unmanaged(
            dirs["kiro"]["rules"].parent / "skills",
            managed_kiro_skills,
            "kiro skills",
            is_dir=True,
        )

    for name in targets:
        agent = all_agents[name]
        for subdir in ["rules", "workflows"]:
            overlay_srcs = [d / "shared" / subdir for d in overlay_dirs]
            overlay_agent_srcs = [d / agent.name / subdir for d in overlay_dirs]
            installed = _install_content(
                agent=agent,
                subdir=subdir,
                shared_src=root_dir / "shared" / subdir,
                overlay_srcs=overlay_srcs,
                overlay_agent_srcs=overlay_agent_srcs,
            )
            _check_unmanaged(
                agent.dest_dir(subdir), installed, f"{agent.name} {subdir}"
            )

    if "cline" in targets:
        log("info", "[cline] Symlinking rules and workflows...")
        cline_symlinks: dict[str, Path] = dirs["cline_symlinks"]
        for subdir, symlink_dest in cline_symlinks.items():
            _symlink_dir(dirs["cline"][subdir], symlink_dest)


def get_managed_dirs() -> list[Path]:
    """Return directories managed by llm-prompts installation.

    These are directories where ``llm-prompts install`` writes files.
    External tools can use this to guard against direct edits.

    Returns:
        Sorted list of managed directory paths.
    """
    dirs = _get_dirs()
    managed: set[Path] = set()
    for key, value in dirs.items():
        if key == "agents":
            managed.add(Path(str(value)) / "skills")
        elif isinstance(value, dict):
            for subdir_path in value.values():
                managed.add(Path(str(subdir_path)))
            if key in ("cline", "kiro"):
                parent = next(iter(value.values())).parent
                managed.add(parent / "skills")
    return sorted(managed)


if __name__ == "__main__":
    main()
