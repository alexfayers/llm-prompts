"""Install Cline and Copilot rules, workflows, skills, and prompts."""

from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
import json
import os
from pathlib import Path
import shutil
import sys
from typing import ClassVar, Literal

from .render_template import (
    find_unreplaced_variables,
    normalize_whitespace,
    parse_frontmatter,
    render_template,
    strip_gating_keys,
)

LogLevel = Literal["debug", "info", "warn", "error", "success"]

# Frontmatter keys consumed by the installer's own gating logic
# (_passes_requires_gate, _excluded_targets). These are stripped from
# agent-specific files before install so they never leak into the installed copy.
_GATING_FRONTMATTER_KEYS = {"requires_env", "requires_command", "exclude_targets"}

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


def _get_dirs() -> dict[str, dict[str, Path]]:
    """Build destination directories used during installation.

    Returns:
        Mapping of agent names to their content directories.
    """
    home = Path.home()
    cline_merged = home / ".cline_merged"
    vscode_user = _vscode_user_dir()
    return {
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
        "claude-code": {
            "rules": home / ".claude" / "rules",
            "workflows": home / ".claude" / "commands",
            "agents": home / ".claude" / "agents",
        },
        "codex": {
            "rules": home / ".codex",
            "workflows": home / ".codex" / "prompts",
            "skills": home / ".codex" / "skills",
        },
    }


def _skills_parent(dirs: dict[str, dict[str, Path]], agent: str) -> Path:
    """Return the directory whose ``skills`` subdir holds an agent's skills.

    Agents with an explicit ``skills`` destination (e.g. codex) use its parent;
    others derive it from the ``rules`` directory's parent.

    Args:
        dirs: Destination directory mapping from ``_get_dirs``.
        agent: Agent name.

    Returns:
        Parent directory that contains the agent's ``skills`` subdirectory.
    """
    agent_dirs = dirs[agent]
    if "skills" in agent_dirs:
        return agent_dirs["skills"].parent
    return agent_dirs["rules"].parent


def _get_cline_extra_dirs() -> tuple[Path, dict[str, Path]]:
    """Return the Cline agents dir and symlink targets.

    Returns:
        Tuple of (agents_dir, symlink_targets).
    """
    home = Path.home()
    cline_base = (
        (home / "Cline") if sys.platform == "linux" else (home / "Documents" / "Cline")
    )
    agents = home / ".agents"
    symlinks = {
        "rules": cline_base / "Rules",
        "workflows": cline_base / "Workflows",
    }
    return agents, symlinks


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


def _env_var_set(name: str) -> bool:
    """Check whether an env var is set in the process env or Claude Code settings.

    Args:
        name: Environment variable name.

    Returns:
        True if the variable has a truthy value in ``os.environ`` or in the
        ``env`` block of ``~/.claude/settings.json``.
    """
    if os.environ.get(name):
        return True
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return False
    try:
        settings = json.loads(_read_text(settings_path))
    except (json.JSONDecodeError, OSError):
        return False
    return bool(settings.get("env", {}).get(name))


def _passes_requires_gate(src: Path) -> bool:
    """Check a source file's ``requires_*`` frontmatter gates, if present.

    Args:
        src: Source file path.

    Returns:
        True if the file has no ``requires_env``/``requires_command`` keys, or
        every present gate is satisfied (env var set / command on PATH); False
        if the file should be skipped.
    """
    try:
        content = _read_text(src)
    except OSError:
        return True
    _, frontmatter = parse_frontmatter(content)
    required_env = frontmatter.get("requires_env")
    if required_env and not _env_var_set(required_env):
        return False
    required_command = frontmatter.get("requires_command")
    if required_command and shutil.which(required_command) is None:
        return False
    return True


def _excluded_targets(src: Path) -> set[str]:
    """Return the set of agent names a source file opts out of installing to.

    Parses the flat, comma-separated ``exclude_targets`` frontmatter key.

    Args:
        src: Source file path.

    Returns:
        Set of agent names to skip; empty if the key is absent.
    """
    try:
        content = _read_text(src)
    except OSError:
        return set()
    _, frontmatter = parse_frontmatter(content)
    raw = frontmatter.get("exclude_targets", "")
    return {name.strip() for name in raw.split(",") if name.strip()}


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

    _write_if_changed(dest, output, label)


def _write_if_changed(dest: Path, output: str, label: str) -> None:
    """Write output to dest only if it differs, logging the action taken.

    Args:
        dest: Destination file path.
        output: Content to write.
        label: Log label for this file.
    """
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
    src_content = strip_gating_keys(_read_text(src), _GATING_FRONTMATTER_KEYS)
    if dest.exists() and not dest.is_symlink():
        if _read_text(dest) == src_content:
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
        _write_text(dest, src_content)
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

    def install_rules(
        self,
        shared_src: Path,
        overlay_srcs: list[Path],
        overlay_agent_srcs: list[Path],
    ) -> set[str]:
        """Install rule content, returning the destination filenames written.

        Args:
            shared_src: Base shared rules source directory.
            overlay_srcs: Overlay shared rules directories in priority order.
            overlay_agent_srcs: Overlay agent-specific rules directories.

        Returns:
            Set of destination filenames that were installed.
        """
        return _install_content(
            self, "rules", shared_src, overlay_srcs, overlay_agent_srcs
        )


class _CopilotAgent(_Agent):
    """Copilot agent with format-specific destination naming."""

    _SUFFIXES: ClassVar[dict[str, str]] = {
        "rules": "instructions",
        "workflows": "prompt",
    }

    def dest_name(self, src: Path, subdir: str) -> str:
        return f"{src.stem}.{self._SUFFIXES[subdir]}.md"


class _CodexAgent(_Agent):
    """Codex agent that concatenates all rules into a single AGENTS.md file."""

    AGENTS_MD: ClassVar[str] = "AGENTS.md"

    def install_rules(
        self,
        shared_src: Path,
        overlay_srcs: list[Path],
        overlay_agent_srcs: list[Path],
    ) -> set[str]:
        dest_dir = self.dest_dir("rules")
        vars_path = self.vars_path()

        log("info", f"[{self.name}] Installing rules...")
        collected = _collect_content_srcs(
            self, "rules", shared_src, overlay_srcs, overlay_agent_srcs
        )

        bodies: list[str] = []
        for _, src in sorted((name, src) for name, src, _ in collected):
            try:
                bodies.append(render_template(str(src), str(vars_path), self.name))
            except Exception as e:
                log("error", f"Failed to render rules/{src.name}: {e}")

        output = normalize_whitespace("\n\n".join(bodies))
        for var in find_unreplaced_variables(output):
            log("warn", f"Unreplaced variable '{{{{{var}}}}}' in {self.AGENTS_MD}")

        dest_dir.mkdir(parents=True, exist_ok=True)
        _write_if_changed(dest_dir / self.AGENTS_MD, output, self.AGENTS_MD)
        return {self.AGENTS_MD}


_CODEX_DOC_LIMIT = 32768
_CODEX_DOC_LIMIT_RAISED = 65536


def _ensure_codex_doc_limit(config_path: Path, agents_md_path: Path) -> None:
    """Raise Codex's project_doc_max_bytes when AGENTS.md would be truncated.

    Codex truncates instruction files at ``project_doc_max_bytes`` (default
    32768). When the generated ``AGENTS.md`` exceeds that and the config does not
    already set the key, insert it before the first table header so the full file
    is loaded.

    Args:
        config_path: Path to ``~/.codex/config.toml``.
        agents_md_path: Path to the generated ``AGENTS.md``.
    """
    import tomllib

    if not agents_md_path.exists() or not config_path.exists():
        return
    if agents_md_path.stat().st_size <= _CODEX_DOC_LIMIT:
        return

    text = _read_text(config_path)
    try:
        if "project_doc_max_bytes" in tomllib.loads(text):
            return
    except tomllib.TOMLDecodeError:
        log("warn", f"Could not parse {config_path}; skipping doc-limit update.")
        return

    lines = text.splitlines(keepends=True)
    new_line = f"project_doc_max_bytes = {_CODEX_DOC_LIMIT_RAISED}\n"
    insert_at = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith("[")),
        len(lines),
    )
    lines.insert(insert_at, new_line)
    _write_text(config_path, "".join(lines))
    log("success", f"Set project_doc_max_bytes = {_CODEX_DOC_LIMIT_RAISED} in config.")


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


def _collect_content_srcs(
    agent: _Agent,
    subdir: str,
    shared_src: Path,
    overlay_srcs: list[Path],
    overlay_agent_srcs: list[Path],
) -> list[tuple[str, Path, bool]]:
    """Collect content sources in overlay-priority order, first-wins per dest name.

    Args:
        agent: Agent configuration.
        subdir: Content subdirectory name (e.g. 'rules' or 'workflows').
        shared_src: Base shared source directory.
        overlay_srcs: Overlay shared source directories in priority order (first wins).
        overlay_agent_srcs: Overlay agent-specific source directories in priority order.

    Returns:
        List of (dest_name, source_path, is_agent_specific) tuples. Agent-specific
        sources are copied verbatim; the rest are rendered.
    """
    collected: list[tuple[str, Path, bool]] = []
    seen: set[str] = set()

    def add(src: Path, name: str, *, agent_specific: bool) -> None:
        if name in seen:
            return
        if not _passes_requires_gate(src):
            log("debug", f"Skipping {name}: requires gate not satisfied.")
            return
        collected.append((name, src, agent_specific))
        seen.add(name)

    for overlay_src in overlay_srcs:
        if overlay_src.exists():
            for src in sorted(overlay_src.glob("*.md")):
                add(src, agent.dest_name(src, subdir), agent_specific=False)

    for src in sorted(shared_src.glob("*.md")):
        add(src, agent.dest_name(src, subdir), agent_specific=False)

    agent_src = agent.agent_src(subdir)
    if agent_src.exists():
        for src in sorted(agent_src.glob("*.md")):
            if not (shared_src / src.name).exists():
                add(src, src.name, agent_specific=True)

    for overlay_agent_src in overlay_agent_srcs:
        if overlay_agent_src.exists():
            for src in sorted(overlay_agent_src.glob("*.md")):
                add(src, agent.dest_name(src, subdir), agent_specific=False)

    return collected


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

    collected = _collect_content_srcs(
        agent, subdir, shared_src, overlay_srcs, overlay_agent_srcs
    )
    for name, src, agent_specific in collected:
        if agent_specific:
            _install_linked(src, dest_dir / name, f"{subdir}/{name}")
        else:
            _install_rendered(
                src, dest_dir / name, vars_path, target, f"{subdir}/{name}"
            )

    return {name for name, _, _ in collected}


def _resolve_priority_sources(
    candidate_dirs: list[Path],
    list_children: Callable[[Path], list[Path]],
    dest_name: Callable[[Path], str],
    gate: Callable[[Path], bool] | None = None,
) -> list[tuple[str, Path]]:
    """Resolve name collisions across candidate dirs, first-occurrence wins.

    Args:
        candidate_dirs: Source directories in priority order (first wins).
        list_children: Returns the candidate source paths within a dir.
        dest_name: Maps a source path to its destination name.
        gate: Optional predicate; a source returning False is skipped.

    Returns:
        (dest_name, source_path) tuples, deduped first-wins, in encounter order.
    """
    resolved: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for directory in candidate_dirs:
        if not directory.exists():
            continue
        for src in list_children(directory):
            name = dest_name(src)
            if name in seen:
                continue
            if gate is not None and not gate(src):
                continue
            resolved.append((name, src))
            seen.add(name)
    return resolved


def _install_symlink(source: Path, dest: Path, label: str, managed: set[str]) -> None:
    """Install ``source`` as a symlink at ``dest``, replacing any existing entry.

    Idempotent: an already-correct symlink is left untouched. A pre-existing
    regular file/dir at ``dest`` is replaced. Records ``dest.name`` in ``managed``.

    Args:
        source: Source path the symlink should point to.
        dest: Destination symlink path.
        label: Human-readable artifact label used in log messages.
        managed: Set to accumulate the installed destination name into.
    """
    name = dest.name
    try:
        if dest.is_symlink() and dest.resolve() == source.resolve():
            log("debug", f"{label} '{name}' is up to date. Skipping.")
            managed.add(name)
            return
        already_existed = dest.exists() or dest.is_symlink()
        if already_existed:
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            else:
                shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(source)
        managed.add(name)
        log(
            "success",
            f"{'Updated' if already_existed else 'Installed'} {label}: {name}",
        )
    except Exception as e:
        log("error", f"Failed to install {label} '{name}': {e}")


def _install_skills(
    candidate_dirs: list[Path], skills_parent: Path, agent_name: str
) -> set[str]:
    """Install skills as symlinks, overlay dirs overriding base on name collision.

    Args:
        candidate_dirs: Source skills directories in priority order (first wins).
        skills_parent: Parent directory whose ``skills`` subdir receives symlinks.
        agent_name: Target agent name, used to apply the requires-gate and
            ``exclude_targets`` checks.

    Returns:
        Set of installed skill names.
    """
    dest_root = skills_parent / "skills"

    def gate(skill_path: Path) -> bool:
        skill_md = skill_path / "SKILL.md"
        if not skill_md.is_file():
            return False
        if not _passes_requires_gate(skill_md):
            log(
                "debug",
                f"Skipping skill '{skill_path.name}': requires gate not satisfied.",
            )
            return False
        if agent_name in _excluded_targets(skill_md):
            log(
                "debug",
                f"Skipping skill '{skill_path.name}': excluded for {agent_name}.",
            )
            return False
        return True

    log("info", "[shared] Installing skills...")
    managed: set[str] = set()
    resolved = _resolve_priority_sources(
        candidate_dirs,
        lambda d: [p for p in sorted(d.iterdir()) if p.is_dir()],
        lambda p: p.name,
        gate,
    )
    for name, src in resolved:
        _install_symlink(src, dest_root / name, "skill", managed)
    return managed


def _install_plugin_skills(
    skill_pairs: list[tuple[str, Path]],
    skills_parent: Path,
    agent_name: str,
    already_managed: set[str],
) -> set[str]:
    """Install plugin-source skills as symlinks, lowest priority.

    Plugin skills never overwrite a built-in/overlay skill of the same name, and
    a duplicate name across plugins resolves in config order (first wins).

    Args:
        skill_pairs: ``(name, source_dir)`` pairs from plugin discovery, in
            config order.
        skills_parent: Parent directory whose ``skills`` subdir receives symlinks.
        agent_name: Target agent name, for the requires-gate and
            ``exclude_targets`` checks.
        already_managed: Skill names already installed this run (built-in or
            overlay); a plugin skill colliding with one is skipped.

    Returns:
        Set of installed plugin skill names.
    """
    dest_root = skills_parent / "skills"
    managed: set[str] = set()
    seen: set[str] = set()
    for name, src_dir in skill_pairs:
        if name in already_managed:
            log("warn", f"Plugin skill '{name}' shadowed by existing skill, skipping")
            continue
        if name in seen:
            log("warn", f"Duplicate plugin skill '{name}' skipped (config order wins)")
            continue
        seen.add(name)
        skill_md = src_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        if not _passes_requires_gate(skill_md):
            log(
                "debug", f"Skipping plugin skill '{name}': requires gate not satisfied."
            )
            continue
        if agent_name in _excluded_targets(skill_md):
            log("debug", f"Skipping plugin skill '{name}': excluded for {agent_name}.")
            continue
        _install_symlink(src_dir, dest_root / name, "plugin skill", managed)
    return managed


def _install_agents(candidate_dirs: list[Path], agents_dir: Path) -> set[str]:
    """Install Claude Code subagent definitions as symlinks.

    Overlay dirs override base on filename collision (first wins).

    Args:
        candidate_dirs: Source agent directories in priority order (first wins).
        agents_dir: Destination agents directory (e.g. ~/.claude/agents).

    Returns:
        Set of installed agent filenames.
    """
    log("info", "[claude-code] Installing agents...")
    managed: set[str] = set()
    resolved = _resolve_priority_sources(
        candidate_dirs,
        lambda d: sorted(d.glob("*.md")),
        lambda p: p.name,
    )
    for name, src in resolved:
        _install_symlink(src, agents_dir / name, "agent", managed)
    return managed


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


def _kiro_resources() -> list[str]:
    """Return the resource URIs that llm-prompts installs for Kiro.

    Returns:
        List of resource URI strings for steering files and skills.
    """
    dirs = _get_dirs()
    steering = dirs["kiro"]["rules"]
    skills = steering.parent / "skills"
    return [
        f"file://{steering}/**/*.md",
        f"skill://{skills}/**/SKILL.md",
    ]


def patch_kiro_agent_config(agent_config_path: str) -> None:
    """Patch a Kiro agent config JSON file with llm-prompts resource entries.

    Merges resource URIs for installed steering files and skills into the
    agent config's ``resources`` array, avoiding duplicates.

    Args:
        agent_config_path: Path to the agent JSON file to patch.
    """
    config_path = Path(agent_config_path)
    if not config_path.exists():
        log("error", f"{config_path} does not exist")
        sys.exit(1)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    existing: list[str] = config.get("resources", [])
    new_resources = _kiro_resources()

    added = 0
    for resource in new_resources:
        if resource not in existing:
            existing.append(resource)
            added += 1

    config["resources"] = existing
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    if added:
        log("success", f"Patched {config_path} with {added} resource(s).")
    else:
        log("info", f"{config_path} already has all resource entries.")


def try_install_hooks(agent_config_path: str) -> None:
    """Patch a Kiro agent config with cline-hooks entries if available.

    Args:
        agent_config_path: Path to the agent JSON file to patch.
    """
    import shutil
    import subprocess

    binary = shutil.which("cline-hook")
    if not binary:
        log("debug", "cline-hook not found on PATH, skipping hook injection.")
        return
    subprocess.run([binary, "install", "kiro", agent_config_path], check=False)


def try_install_hooks_claude_code() -> None:
    """Patch Claude Code settings with cline-hooks entries if available."""
    import shutil
    import subprocess

    binary = shutil.which("cline-hook")
    if not binary:
        log(
            "debug",
            "cline-hook not found on PATH, skipping Claude Code hook injection.",
        )
        return
    subprocess.run([binary, "install", "claude-code"], check=False)


def try_allow_update_claude_code() -> None:
    """Add Bash(llm-prompts update *) to Claude Code permissions.allow."""
    import json

    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    allow: list[str] = settings.setdefault("permissions", {}).setdefault("allow", [])
    rule = "Bash(llm-prompts update *)"
    if rule not in allow:
        allow.append(rule)
        settings_path.write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8"
        )
        log("success", "Added Bash(llm-prompts update *) to Claude Code permissions.")


def _memory_service_exists() -> bool:
    """Check whether the mcp-memory background service is installed."""
    if sys.platform == "darwin":
        return (
            Path.home() / "Library" / "LaunchAgents" / "com.mcp-memory.plist"
        ).exists()
    return Path("/etc/systemd/system/mcp-memory.service").exists()


def try_install_memory(agent_config_path: str) -> None:
    """Patch Kiro agent config with memory MCP server and set up service if needed.

    Args:
        agent_config_path: Agent JSON to patch with memory server and @memory allowedTools.
    """
    import shutil
    import subprocess

    binary = shutil.which("mcp-memory")
    if not binary:
        log("debug", "mcp-memory not found on PATH, skipping MCP config injection.")
        return
    subprocess.run([binary, "install", "kiro", agent_config_path], check=False)
    if not _memory_service_exists():
        subprocess.run([binary, "setup-service"], check=False)


def try_install_memory_claude_code() -> None:
    """Add mcp-memory to Claude Code if available."""
    import shutil
    import subprocess

    binary = shutil.which("mcp-memory")
    if not binary:
        log("debug", "mcp-memory not found on PATH, skipping Claude Code MCP setup.")
        return
    subprocess.run([binary, "install", "claude-code"], check=False)
    if not _memory_service_exists():
        subprocess.run([binary, "setup-service"], check=False)


def _cleanup_stale(
    agent_name: str,
    current_files: list[str],
    previous_manifest: dict,
) -> None:
    """Remove files that were previously installed but are no longer managed.

    Args:
        agent_name: Agent whose stale files to remove.
        current_files: Currently installed file paths for this agent.
        previous_manifest: The manifest from the previous installation.
    """
    previous_entry = previous_manifest.get(agent_name, {})
    previous_files = set(previous_entry.get("files", []))
    current_set = set(current_files)
    stale = previous_files - current_set

    for filepath in sorted(stale):
        path = Path(filepath)
        if path.is_symlink() or path.is_file():
            path.unlink()
            log("info", f"[{agent_name}] Removed stale file: {path.name}")
        elif path.is_dir():
            shutil.rmtree(path)
            log("info", f"[{agent_name}] Removed stale directory: {path.name}")


def _remove_manifest_files(agent_name: str, files: list[str]) -> None:
    """Remove files that were installed for an agent.

    Args:
        agent_name: Agent whose files to remove.
        files: Installed file paths to remove.
    """
    for filepath in files:
        path = Path(filepath)
        if path.is_symlink() or path.is_file():
            path.unlink()
            log("info", f"[{agent_name}] Removed file: {path.name}")
        elif path.is_dir():
            shutil.rmtree(path)
            log("info", f"[{agent_name}] Removed directory: {path.name}")


def _remove_cline_symlinks() -> None:
    """Remove Cline's rules and workflows directory symlinks."""
    _, symlinks = _get_cline_extra_dirs()
    for dest in symlinks.values():
        if dest.is_symlink():
            dest.unlink()
            log("info", f"[cline] Removed symlink: {dest}")


def _unpatch_kiro_agent_config(agent_config_path: str) -> None:
    """Remove llm-prompts resource entries from a Kiro agent config.

    Args:
        agent_config_path: Path to the agent JSON file to unpatch.
    """
    config_path = Path(agent_config_path)
    if not config_path.exists():
        return

    config = json.loads(config_path.read_text(encoding="utf-8"))
    existing: list[str] = config.get("resources", [])
    to_remove = set(_kiro_resources())
    filtered = [r for r in existing if r not in to_remove]

    if filtered != existing:
        config["resources"] = filtered
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        removed = len(existing) - len(filtered)
        log("success", f"Removed {removed} resource(s) from {config_path}.")


def _disallow_update_claude_code() -> None:
    """Remove Bash(llm-prompts update *) from Claude Code permissions.allow."""
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    allow: list[str] = settings.get("permissions", {}).get("allow", [])
    rule = "Bash(llm-prompts update *)"
    if rule in allow:
        allow.remove(rule)
        settings_path.write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8"
        )
        log(
            "success",
            "Removed Bash(llm-prompts update *) from Claude Code permissions.",
        )


def uninstall(agent_names: list[str] | None = None, *, verbose: bool = False) -> None:
    """Reverse an installation, removing installed files and manifest entries.

    Args:
        agent_names: Agents to uninstall. None means all installed agents.
        verbose: Show debug-level output.
    """
    global _verbose  # noqa: PLW0603
    _verbose = verbose
    from .manifest import delete_agent, read_manifest

    manifest = read_manifest()
    targets = agent_names or list(manifest)
    for name in targets:
        entry = manifest.get(name)
        if entry is None:
            log("warn", f"[{name}] not installed; nothing to remove.")
            continue
        _remove_manifest_files(name, entry.get("files", []))
        if name == "cline":
            _remove_cline_symlinks()
        agent_config = entry.get("agent_config")
        if agent_config:
            _unpatch_kiro_agent_config(agent_config)
        if name == "claude-code":
            _disallow_update_claude_code()
        delete_agent(name)
        log("success", f"[{name}] Uninstalled.")


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
        "claude-code": _Agent(name="claude-code", root_dir=root_dir, dirs=dirs),
        "codex": _CodexAgent(name="codex", root_dir=root_dir, dirs=dirs),
    }
    targets = agent_names or list(all_agents)

    installed_files: dict[str, list[str]] = {name: [] for name in targets}

    from .plugins import (
        _load_plugins,
        _validate_plugins,
        discover_skills,
        ensure_cloned,
    )

    plugins = _load_plugins()
    plugin_errors = _validate_plugins(plugins)
    if plugin_errors:
        for err in plugin_errors:
            log("error", err)
        sys.exit(1)

    plugin_skill_pairs: list[tuple[str, Path]] = []
    for plugin in plugins:
        checkout = ensure_cloned(plugin)
        if checkout is None:
            continue
        plugin_skill_pairs.extend(discover_skills(checkout, plugin.get("skills")))

    if "cline" in targets:
        agents_dir, _ = _get_cline_extra_dirs()
        cline_skill_dirs = [
            *(d / "shared" / "skills" for d in overlay_dirs),
            root_dir / "shared" / "skills",
        ]
        managed_skills = _install_skills(cline_skill_dirs, agents_dir, "cline")
        plugin_managed = _install_plugin_skills(
            plugin_skill_pairs, agents_dir, "cline", managed_skills
        )
        managed_skills |= plugin_managed
        _check_unmanaged(agents_dir / "skills", managed_skills, "skills", is_dir=True)
        skills_dir = agents_dir / "skills"
        installed_files["cline"].extend(str(skills_dir / s) for s in managed_skills)

    for skill_agent in ("kiro", "claude-code", "codex"):
        if skill_agent not in targets:
            continue
        skills_parent = _skills_parent(dirs, skill_agent)
        skill_dirs = [
            *(d / "shared" / "skills" for d in overlay_dirs),
            root_dir / "shared" / "skills",
            root_dir / skill_agent / "skills",
            *(d / skill_agent / "skills" for d in overlay_dirs),
        ]
        managed = _install_skills(skill_dirs, skills_parent, skill_agent)
        plugin_managed = _install_plugin_skills(
            plugin_skill_pairs, skills_parent, skill_agent, managed
        )
        managed |= plugin_managed
        _check_unmanaged(
            skills_parent / "skills", managed, f"{skill_agent} skills", is_dir=True
        )
        skills_dir = skills_parent / "skills"
        installed_files[skill_agent].extend(str(skills_dir / s) for s in managed)

    if "claude-code" in targets:
        agents_dest = dirs["claude-code"]["agents"]
        agent_dirs = [
            *(d / "claude-code" / "agents" for d in overlay_dirs),
            root_dir / "claude-code" / "agents",
        ]
        managed_agents = _install_agents(agent_dirs, agents_dest)
        _check_unmanaged(agents_dest, managed_agents, "claude-code agents")
        installed_files["claude-code"].extend(
            str(agents_dest / a) for a in managed_agents
        )

    for name in targets:
        agent = all_agents[name]
        for subdir in ["rules", "workflows"]:
            overlay_srcs = [d / "shared" / subdir for d in overlay_dirs]
            overlay_agent_srcs = [d / agent.name / subdir for d in overlay_dirs]
            shared_src = root_dir / "shared" / subdir
            if subdir == "rules":
                installed = agent.install_rules(
                    shared_src, overlay_srcs, overlay_agent_srcs
                )
            else:
                installed = _install_content(
                    agent=agent,
                    subdir=subdir,
                    shared_src=shared_src,
                    overlay_srcs=overlay_srcs,
                    overlay_agent_srcs=overlay_agent_srcs,
                )
            dest_dir = agent.dest_dir(subdir)
            if not (isinstance(agent, _CodexAgent) and subdir == "rules"):
                _check_unmanaged(dest_dir, installed, f"{agent.name} {subdir}")
            installed_files[name].extend(str(dest_dir / f) for f in installed)

    if "codex" in targets:
        _ensure_codex_doc_limit(
            dirs["codex"]["rules"] / "config.toml",
            dirs["codex"]["rules"] / _CodexAgent.AGENTS_MD,
        )

    if "cline" in targets:
        log("info", "[cline] Symlinking rules and workflows...")
        _, cline_symlinks = _get_cline_extra_dirs()
        for subdir, symlink_dest in cline_symlinks.items():
            _symlink_dir(dirs["cline"][subdir], symlink_dest)

    from .manifest import read_manifest, write_manifest

    previous_manifest = read_manifest()
    for name in targets:
        _cleanup_stale(name, installed_files[name], previous_manifest)
        write_manifest(name, installed_files[name])


def get_managed_dirs() -> list[Path]:
    """Return directories managed by llm-prompts installation.

    These are directories where ``llm-prompts install`` writes files.
    External tools can use this to guard against direct edits.

    Returns:
        Sorted list of managed directory paths.
    """
    dirs = _get_dirs()
    agents_dir, _ = _get_cline_extra_dirs()
    managed: set[Path] = set()
    managed.add(agents_dir / "skills")
    for key, value in dirs.items():
        for subdir, subdir_path in value.items():
            if key == "codex" and subdir == "rules":
                continue
            managed.add(subdir_path)
        if key in ("cline", "kiro", "claude-code"):
            parent = next(iter(value.values())).parent
            managed.add(parent / "skills")
    return sorted(managed)


def get_managed_files() -> set[str]:
    """Return all file paths tracked in the installed manifest.

    Use this for precise file-level checking rather than directory-level
    blocking. Files not in this set are user-created and should not be
    blocked from editing.

    Returns:
        Set of absolute file path strings from the manifest.
    """
    from .manifest import read_manifest

    files: set[str] = set()
    for entry in read_manifest().values():
        files.update(entry.get("files", []))
    return files


if __name__ == "__main__":
    main()
