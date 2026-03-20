#!/usr/bin/env python
"""Install Cline and Copilot rules, workflows, skills, and prompts."""

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

try:
    from render_template import render_template
except ModuleNotFoundError:
    from scripts.render_template import render_template


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


def log(level: LogLevel, message: str) -> None:
    """Log a message with appropriate formatting.

    Args:
        level: Log level.
        message: Message to print.
    """
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
    elif sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Code" / "User"
    else:
        return home / ".config" / "Code" / "User"


def _get_dirs() -> dict[str, Path]:
    """Build destination directories used during installation.

    Returns:
        Mapping of installation destination names to paths.
    """
    home = Path.home()
    cline_base = (home / "Cline") if sys.platform == "linux" else (home / "Documents" / "Cline")
    cline_merged = home / ".cline_merged"
    vscode_user = _vscode_user_dir()
    return {
        "agents": home / ".agents",
        "cline_rules": cline_base / "Rules",
        "cline_rules_merged": cline_merged / "rules",
        "cline_workflows": cline_base / "Workflows",
        "cline_workflows_merged": cline_merged / "workflows",
        "copilot_instructions": home / ".copilot" / "instructions",
        "copilot_prompts": vscode_user / "prompts",
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


def _install_rendered(src: Path, dest: Path, vars_path: Path, target: str, label: str) -> None:
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
class _Section:
    label_type: str
    shared_src: Path
    agent_src: Path
    dest_dir: Path
    vars_path: Path
    target: str
    dest_name: Callable[[Path], str]


def _install_section(section: _Section) -> None:
    """Install one content section.

    Args:
        section: Section configuration.
    """
    log("info", f"[{section.target}] Installing {section.label_type}s...")
    section.dest_dir.mkdir(parents=True, exist_ok=True)

    for src in sorted(section.shared_src.glob("*.md")):
        dest_filename = section.dest_name(src)
        _install_rendered(src, section.dest_dir / dest_filename, section.vars_path, section.target, f"{section.label_type} '{dest_filename}'")

    if section.agent_src.exists():
        for src in sorted(section.agent_src.glob("*.md")):
            if (section.shared_src / src.name).exists():
                continue
            _install_linked(src, section.dest_dir / src.name, f"{section.label_type} '{src.name}'")


def _install_skills(skills_src: Path, agents_dir: Path) -> None:
    """Install Cline skills as symlinks in the agents directory.

    Args:
        skills_src: Source skills directory.
        agents_dir: Agents destination directory.
    """
    if not skills_src.exists():
        return
    log("info", "[cline] Installing skills...")
    for skill_path in sorted(skills_src.iterdir()):
        if not skill_path.is_dir():
            continue
        skill_name = skill_path.name
        skill_dest = agents_dir / "skills" / skill_name
        try:
            if skill_dest.is_symlink() and skill_dest.resolve() == skill_path.resolve():
                log("debug", f"Skill '{skill_name}' is up to date. Skipping.")
                continue
            already_existed = skill_dest.exists()
            if already_existed:
                if skill_dest.is_symlink():
                    skill_dest.unlink()
                else:
                    shutil.rmtree(skill_dest)
            skill_dest.parent.mkdir(parents=True, exist_ok=True)
            skill_dest.symlink_to(skill_path)
            log("success", f"{'Updated' if already_existed else 'Installed'} skill: {skill_name}")
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


def main() -> None:
    """Run the installation workflow."""
    script_dir = Path(__file__).parent
    root_dir = script_dir.parent
    dirs = _get_dirs()

    cline_vars = root_dir / "cline" / "vars.json"
    copilot_vars = root_dir / "copilot" / "vars.json"

    _install_skills(root_dir / "cline" / "skills", dirs["agents"])

    for section in [
        _Section(
            label_type="rule",
            shared_src=root_dir / "shared" / "rules",
            agent_src=root_dir / "cline" / "rules",
            dest_dir=dirs["cline_rules_merged"],
            vars_path=cline_vars,
            target="cline",
            dest_name=lambda p: p.name,
        ),
        _Section(
            label_type="workflow",
            shared_src=root_dir / "shared" / "workflows",
            agent_src=root_dir / "cline" / "workflows",
            dest_dir=dirs["cline_workflows_merged"],
            vars_path=cline_vars,
            target="cline",
            dest_name=lambda p: p.name,
        ),
        _Section(
            label_type="instruction",
            shared_src=root_dir / "shared" / "rules",
            agent_src=root_dir / "copilot" / "instructions",
            dest_dir=dirs["copilot_instructions"],
            vars_path=copilot_vars,
            target="copilot",
            dest_name=lambda p: f"{p.stem}.instructions.md",
        ),
        _Section(
            label_type="prompt",
            shared_src=root_dir / "shared" / "workflows",
            agent_src=root_dir / "copilot" / "prompts",
            dest_dir=dirs["copilot_prompts"],
            vars_path=copilot_vars,
            target="copilot",
            dest_name=lambda p: f"{p.stem}.prompt.md",
        ),
    ]:
        _install_section(section)

    log("info", "[cline] Symlinking rules and workflows...")
    _symlink_dir(dirs["cline_rules_merged"], dirs["cline_rules"])
    _symlink_dir(dirs["cline_workflows_merged"], dirs["cline_workflows"])


if __name__ == "__main__":
    main()
