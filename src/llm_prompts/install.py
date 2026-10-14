"""Install Cline and Copilot rules, workflows, skills, and prompts."""

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Container, Mapping, Sequence
from dataclasses import dataclass
from functools import cache, partial
from importlib.metadata import distribution, packages_distributions
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal
from urllib.parse import urlparse
from urllib.request import url2pathname

from jinja2 import TemplateError

from .colors import Color, paint
from .herdsman import HERDSMAN_DISABLED_DEFINITIONS, herdr_available
from .render_template import (
    _read_text,
    clear_read_cache,
    find_unreplaced_variables,
    load_vars,
    normalize_whitespace,
    parse_frontmatter,
    render_template,
    resolve_frontmatter,
    resolve_source_file,
    split_frontmatter,
    strip_gating_keys,
    substitute_template,
    substitute_variables,
)

if TYPE_CHECKING:
    from .manifest import AgentManifest

LogLevel = Literal["debug", "info", "warn", "error", "success"]

_TARGET_GATING_KEYS = {
    "requires_env",
    "requires_command",
    "requires_absent_command",
    "targets",
    "exclude_targets",
    "extra_variants",
}

_COLORS: dict[LogLevel, Color] = {
    "debug": "grey",
    "info": "white",
    "warn": "yellow",
    "error": "red",
    "success": "green",
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
        print(paint(f"{_SYMBOLS[level]} {message}", _COLORS[level]), file=sys.stderr)
    else:
        print(f"{_PLAIN_SYMBOLS[level]} {message}", file=sys.stderr)


def _pi_agent_dir() -> Path:
    """Return pi's config directory.

    Returns:
        ``$PI_CODING_AGENT_DIR`` where set, else ``~/.pi/agent``.
    """
    override = os.environ.get("PI_CODING_AGENT_DIR")
    return Path(override).expanduser() if override else Path.home() / ".pi" / "agent"


def _get_dirs() -> dict[str, dict[str, Path]]:
    """Build destination directories used during installation.

    Returns:
        Mapping of agent names to their content directories.
    """
    home = Path.home()
    cline_merged = home / ".cline_merged"
    pi_agent = _pi_agent_dir()
    return {
        "cline": {
            "rules": cline_merged / "rules",
            "workflows": cline_merged / "workflows",
        },
        "copilot": {
            "rules": home / ".copilot" / "instructions",
            "skills": home / ".copilot" / "skills",
        },
        "kiro": {
            "rules": home / ".kiro" / "steering",
        },
        "claude-code": {
            "rules": home / ".claude" / "rules",
            "agents": home / ".claude" / "agents",
        },
        "codex": {
            "rules": home / ".codex",
            "skills": home / ".codex" / "skills",
        },
        "antigravity": {
            "rules": home / ".gemini" / "config",
            "skills": home / ".gemini" / "config" / "skills",
        },
        "pi": {
            "rules": pi_agent,
            "skills": pi_agent / "skills",
            "agents": pi_agent / "agents",
            "workflows": pi_agent / "prompts",
        },
    }


def content_subdirs(agent_name: str) -> list[str]:
    """Return the rules/workflows content subdirs installed for an agent.

    Args:
        agent_name: Agent name.

    Returns:
        ``rules``, plus ``workflows`` for the agents that install workflows.
    """
    return [s for s in ("rules", "workflows") if s in _get_dirs()[agent_name]]


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


def _override_key(target: str, key: str) -> str:
    """Return the frontmatter key that overrides ``key`` for one target.

    Args:
        target: Target agent name.
        key: Frontmatter key being overridden.

    Returns:
        ``<target>_<key>``, with hyphens in the target name as underscores.
    """
    return f"{target.replace('-', '_')}_{key}"


def _gating_value(frontmatter: dict[str, str], key: str, target: str) -> str:
    """Return a gating key's value, honouring a target-specific override.

    Args:
        frontmatter: Parsed frontmatter key-value pairs.
        key: Gating key.
        target: Target agent name whose override wins when set.

    Returns:
        The override's value if present, else the base key's, else empty.
    """
    return frontmatter.get(_override_key(target, key), frontmatter.get(key, ""))


def _passes_requires_gate(src: Path, target: str = "") -> bool:
    """Check a source file's ``requires_*`` frontmatter gates, if present.

    Args:
        src: Source file path.
        target: Target agent name whose gate overrides apply.

    Returns:
        True if the file has no ``requires_*`` keys, or every present gate
        is satisfied (env var set / command on or absent from PATH); False
        if the file should be skipped.
    """
    try:
        content = _read_text(src)
    except OSError:
        return True
    _, frontmatter = parse_frontmatter(content)
    return _requirements_met(frontmatter, target)


def _requirements_met(declared: dict[str, str], target: str = "") -> bool:
    """Check the ``requires_*`` gates among a set of declared keys.

    Args:
        declared: Frontmatter or pi package entry keys.
        target: Target agent name whose gate overrides apply.

    Returns:
        True if there are no ``requires_*`` keys, or every present gate is
        satisfied (env var set / command on or absent from PATH), and any
        ``source_file`` glob matches a file.
    """
    if "source_file" in declared and resolve_source_file(declared) is None:
        return False
    required_env = _gating_value(declared, "requires_env", target)
    if required_env and not _env_var_set(required_env):
        return False
    required_command = _gating_value(declared, "requires_command", target)
    if required_command and shutil.which(required_command) is None:
        return False
    absent_command = _gating_value(declared, "requires_absent_command", target)
    return not (absent_command and shutil.which(absent_command) is not None)


def _target_names(src: Path, key: str, target: str = "") -> set[str]:
    """Return the agent names listed under a comma-separated frontmatter key.

    Args:
        src: Source file path.
        key: Frontmatter key holding the comma-separated agent names.
        target: Target agent name whose key override applies.

    Returns:
        Set of agent names; empty if the key is absent.
    """
    try:
        content = _read_text(src)
    except OSError:
        return set()
    _, frontmatter = parse_frontmatter(content)
    return {
        name.strip()
        for name in _gating_value(frontmatter, key, target).split(",")
        if name.strip()
    }


def _targets_agent(src: Path, name: str) -> bool:
    """Return whether a source file installs to the named agent.

    ``targets`` lists the only agents to install to; ``exclude_targets`` lists
    agents to skip. Neither key means every agent.

    Args:
        src: Source file path.
        name: Agent name.

    Returns:
        True if the file installs to ``name``.
    """
    included = _target_names(src, "targets", name)
    return (not included or name in included) and name not in _target_names(
        src, "exclude_targets", name
    )


@cache
def prompts_dir(module: str) -> Path:
    """Return a package's prompts directory, from its checkout if installed from one.

    Args:
        module: The importable package name.

    Returns:
        The prompts directory in the local checkout the package was installed
        from, or the one inside the installed package.
    """
    for dist_name in packages_distributions().get(module, []):
        raw_direct_url = distribution(dist_name).read_text("direct_url.json")
        direct_url = json.loads(raw_direct_url) if raw_direct_url else {}
        if "dir_info" not in direct_url:
            continue
        root = Path(url2pathname(urlparse(direct_url["url"]).path))
        for candidate in (root / "src" / module / "prompts", root / module / "prompts"):
            if candidate.is_dir():
                return candidate
    return Path(str(files(module) / "prompts"))


def _discover_overlay_paths() -> list[Path]:
    """Discover overlay directories from installed packages via entry_points.

    Packages declare an ``llm_prompts`` entry point group where each entry
    point value is the package name. The prompts directory is resolved via
    ``prompts_dir(<package>)``.

    Returns:
        List of overlay directory paths from installed packages.
    """
    from importlib.metadata import entry_points

    paths: list[Path] = []
    for ep in entry_points(group="llm_prompts"):
        try:
            overlay_path = prompts_dir(ep.value)
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


def _rendered_content(src: Path, vars_path: Path, target: str) -> str:
    """Render a shared source file's content for one target, without writing it.

    Args:
        src: Source template path.
        vars_path: Variables JSON path.
        target: Render target.

    Returns:
        Rendered content, as it would be installed.
    """
    return render_template(str(src), str(vars_path), target)


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
        output = _rendered_content(src, vars_path, target)
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


def _linked_content(src: Path) -> str:
    """Return an agent-specific source file's content, without writing it.

    Only the gating frontmatter keys are stripped; everything else, including
    the rest of the frontmatter, is carried verbatim - agent-specific sources
    never go through variable substitution or per-target rendering.

    Args:
        src: Source file path.

    Returns:
        Content as it would be installed.
    """
    return strip_gating_keys(_read_text(src), _GATING_FRONTMATTER_KEYS)


def _install_linked(src: Path, dest: Path, label: str) -> None:
    """Install a file by copying source content to destination.

    Args:
        src: Source file path.
        dest: Destination file path.
        label: Log label for this file.
    """
    src_content = _linked_content(src)
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


@dataclass(frozen=True)
class _AllExcept:
    """Skip set holding every source except ``kept``."""

    kept: frozenset[Path]

    def __contains__(self, item: object) -> bool:
        return item not in self.kept


@dataclass
class _Agent:
    """Agent installation configuration."""

    name: str
    root_dir: Path
    dirs: dict[str, dict[str, Path]]

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
        skip_set: Container[Path] = frozenset(),
        previous_manifest: "dict[str, AgentManifest] | None" = None,
    ) -> set[str]:
        """Install rule content, returning the destination filenames written.

        Args:
            shared_src: Base shared rules source directory.
            overlay_srcs: Overlay shared rules directories in priority order.
            overlay_agent_srcs: Overlay agent-specific rules directories.
            skip_set: Resolved source paths to leave untouched.
            previous_manifest: The manifest from the previous installation.

        Returns:
            Set of destination filenames that were installed.
        """
        return _install_content(
            self,
            "rules",
            shared_src,
            overlay_srcs,
            overlay_agent_srcs,
            skip_set,
            previous_manifest,
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
        skip_set: Container[Path] = frozenset(),
        previous_manifest: "dict[str, AgentManifest] | None" = None,
    ) -> set[str]:
        from .manifest import read_rendered_rule, write_rendered_rules

        dest_dir = self.dest_dir("rules")
        vars_path = self.vars_path()
        dest = dest_dir / self.AGENTS_MD

        log("info", f"[{self.name}] Installing rules...")
        collected = _collect_content_srcs(
            self, "rules", shared_src, overlay_srcs, overlay_agent_srcs
        )

        rules: dict[str, str] = {}
        held_back: list[str] = []
        for name, src in sorted((name, src) for name, src, _ in collected):
            if src.resolve() in skip_set:
                cached = read_rendered_rule(self.name, name)
                if cached is not None:
                    rules[name] = cached
                    continue
                if not isinstance(skip_set, _AllExcept):
                    held_back.append(name)
                    continue
            try:
                rules[name] = render_template(str(src), str(vars_path), self.name)
            except Exception as e:
                log("error", f"Failed to render rules/{src.name}: {e}")

        for name in held_back:
            log(
                "warn",
                f"[{self.name}] Held back {self.AGENTS_MD}: "
                f"rules/{name} skipped with no cached copy",
            )
        if held_back and dest.exists():
            return {self.AGENTS_MD}

        output = normalize_whitespace("\n\n".join(rules.values()))
        for var in find_unreplaced_variables(output):
            log("warn", f"Unreplaced variable '{{{{{var}}}}}' in {self.AGENTS_MD}")

        dest_dir.mkdir(parents=True, exist_ok=True)
        _write_if_changed(dest, output, self.AGENTS_MD)
        write_rendered_rules(self.name, rules)
        return {self.AGENTS_MD}


class _AntigravityAgent(_CodexAgent):
    """Antigravity agent that concatenates all rules into a single AGENTS.md file."""

    AGENTS_MD: ClassVar[str] = "AGENTS.md"


class _PiAgent(_CodexAgent):
    """Pi agent that concatenates all rules into its global AGENTS.md file."""

    AGENTS_MD: ClassVar[str] = "AGENTS.md"


AGENT_CLASSES: dict[str, type[_Agent]] = {
    "cline": _Agent,
    "copilot": _CopilotAgent,
    "kiro": _Agent,
    "claude-code": _Agent,
    "codex": _CodexAgent,
    "antigravity": _AntigravityAgent,
    "pi": _PiAgent,
}

# Frontmatter keys consumed by the installer's own gating logic
# (_passes_requires_gate, _targets_agent), with their per-target overrides.
# These are stripped from agent-specific files before install so they never
# leak into the installed copy.
_GATING_FRONTMATTER_KEYS = {
    "generate_variants",
    "roles",
    "rules",
    *_TARGET_GATING_KEYS,
    *(_override_key(t, k) for t in AGENT_CLASSES for k in _TARGET_GATING_KEYS),
}

_AGENT_ROLES = ("coordinator", "reasoner", "worker", "surveyor", "reviewer")
_RULE_ROLES = frozenset({"lead", *_AGENT_ROLES})


def _parse_roles(content: str, label: str) -> frozenset[str]:
    """Read the Pi roles a rule is selected for from its ``roles`` frontmatter.

    Args:
        content: Rule content after template substitution, frontmatter intact.
        label: Rule name for error messages.

    Returns:
        The declared roles, or ``{"core"}`` when the rule declares none.

    Raises:
        ValueError: ``roles`` is empty, malformed, or names an unknown role
            (``core`` is the default and cannot be declared).
    """
    split = split_frontmatter(content)
    declared = [
        line.partition(":")[2]
        for line in (split[0] if split else [])
        if line.partition(":")[0].strip() == "roles"
    ]
    if not declared:
        return frozenset({"core"})
    tokens = [t.strip() for t in declared[0].strip().strip("'\"").split(",")]
    roles = frozenset(tokens)
    if "" in roles or not roles <= _RULE_ROLES:
        raise ValueError(
            f"{label}: invalid roles '{declared[0].strip()}' - "
            f"omit roles for a core rule, or use any of {sorted(_RULE_ROLES)}"
        )
    return roles


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
        if not _passes_requires_gate(src, agent.name):
            log("debug", f"Skipping {name}: requires gate not satisfied.")
            return
        if not _targets_agent(src, agent.name):
            log("debug", f"Skipping {name}: excluded for {agent.name}.")
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
    skip_set: Container[Path] = frozenset(),
    previous_manifest: "dict[str, AgentManifest] | None" = None,
) -> set[str]:
    """Install shared and agent-specific content for one agent and content type.

    Args:
        agent: Agent configuration.
        subdir: Content subdirectory name (e.g. 'rules' or 'workflows').
        shared_src: Base shared source directory.
        overlay_srcs: Overlay shared source directories in priority order (first wins).
        overlay_agent_srcs: Overlay agent-specific source directories in priority order.
        skip_set: Resolved source paths to leave untouched.
        previous_manifest: The manifest from the previous installation.

    Returns:
        Set of destination filenames that were installed.
    """
    previous_manifest = previous_manifest if previous_manifest is not None else {}
    dest_dir = agent.dest_dir(subdir)
    vars_path = agent.vars_path()
    target = agent.name

    log("info", f"[{target}] Installing {subdir}...")
    dest_dir.mkdir(parents=True, exist_ok=True)

    collected = _collect_content_srcs(
        agent, subdir, shared_src, overlay_srcs, overlay_agent_srcs
    )
    managed: set[str] = set()
    for name, src, agent_specific in collected:
        if src.resolve() in skip_set:
            if _carry_forward(
                target,
                dest_dir / name,
                f"{subdir}/{name}",
                previous_manifest,
                quiet=isinstance(skip_set, _AllExcept),
            ):
                managed.add(name)
            continue
        if agent_specific:
            _install_linked(src, dest_dir / name, f"{subdir}/{name}")
        else:
            _install_rendered(
                src, dest_dir / name, vars_path, target, f"{subdir}/{name}"
            )
        managed.add(name)

    return managed


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


def _apply_frontmatter_overrides(content: str, overrides: dict[str, str]) -> str:
    """Rewrite matching frontmatter keys with override values, preserving the rest.

    Replaces each key present in both ``content``'s frontmatter and ``overrides``;
    appends any override key absent from the frontmatter. All other frontmatter
    lines and the body are carried verbatim. Synthesizes a frontmatter block if
    ``content`` has none.

    Args:
        content: Source ``SKILL.md`` content.
        overrides: Frontmatter key/value overrides, values already stringified.

    Returns:
        Content with the overrides applied.
    """
    split = split_frontmatter(content)
    frontmatter_lines, body = split if split is not None else ([], content)

    remaining = dict(overrides)
    lines = []
    for line in frontmatter_lines:
        key = line.partition(": ")[0].strip()
        if key in remaining:
            lines.append(f"{key}: {remaining.pop(key)}")
        else:
            lines.append(line)
    for key, value in remaining.items():
        lines.append(f"{key}: {value}")

    return "---\n" + "\n".join(lines) + "\n---\n" + body


def _materialize_skill_dir(
    source: Path, dest: Path, content: str, label: str, managed: set[str]
) -> None:
    """Materialize a skill as a real directory with a rewritten ``SKILL.md``.

    ``dest`` becomes a real directory (converted from a symlink/file if needed)
    containing ``content`` as its ``SKILL.md`` plus every other top-level entry
    of ``source`` symlinked in, so siblings keep tracking upstream. Any entry in
    ``dest`` no longer present in ``source`` is pruned, since manifest cleanup
    never inspects a skill directory's contents.

    Args:
        source: Skill's source directory.
        dest: Destination skill directory.
        content: Content to write as ``dest``'s ``SKILL.md``.
        label: Human-readable label for log/error messages.
        managed: Set to accumulate the installed destination name into.
    """
    name = dest.name
    try:
        if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
            dest.unlink()
        dest.mkdir(parents=True, exist_ok=True)

        _write_if_changed(dest / "SKILL.md", content, f"{label} '{name}' SKILL.md")

        source_names = {entry.name for entry in source.iterdir()}
        for entry in source.iterdir():
            if entry.name == "SKILL.md":
                continue
            _install_symlink(entry, dest / entry.name, f"{label} sibling", set())

        for existing in dest.iterdir():
            if existing.name == "SKILL.md" or existing.name in source_names:
                continue
            if existing.is_symlink() or existing.is_file():
                existing.unlink()
            else:
                shutil.rmtree(existing)

        managed.add(name)
    except Exception as e:
        log("error", f"Failed to materialize {label} '{name}': {e}")


def _materialize_override_skill(
    source: Path, dest: Path, overrides: dict[str, str], managed: set[str]
) -> None:
    """Install a plugin skill as a real directory with a patched ``SKILL.md``.

    Args:
        source: Plugin skill's checkout directory.
        dest: Destination skill directory.
        overrides: Frontmatter key/value overrides, values already stringified.
        managed: Set to accumulate the installed destination name into.
    """
    patched = _apply_frontmatter_overrides(_read_text(source / "SKILL.md"), overrides)
    _materialize_skill_dir(source, dest, patched, "plugin skill", managed)


def _builtin_skill_vars(vars_path: Path) -> dict[str, str]:
    """Load a target agent's variables JSON for built-in skill substitution.

    Args:
        vars_path: Variables JSON path.

    Returns:
        Parsed variables mapping, empty if the file is missing.
    """
    if not vars_path.exists():
        return {}
    return load_vars(vars_path)


def _materialize_builtin_skill(
    source: Path,
    dest: Path,
    vars_path: Path,
    managed: set[str],
    agent_name: str = "",
    skip_set: Container[Path] = frozenset(),
    previous_manifest: "dict[str, AgentManifest] | None" = None,
) -> None:
    """Install a built-in/overlay skill as a real directory with variables substituted.

    Only ``substitute_variables`` is applied to ``SKILL.md`` - never
    ``render_template``, which returns body only and would strip the
    frontmatter a skill needs to register.

    Args:
        source: Skill's source directory.
        dest: Destination skill directory.
        vars_path: Variables JSON path for the target agent.
        managed: Set to accumulate the installed destination name into.
        agent_name: Target agent name, used for the size-guard skip decision.
        skip_set: Resolved source paths to leave untouched.
        previous_manifest: The manifest from the previous installation.
    """
    previous_manifest = previous_manifest if previous_manifest is not None else {}
    skill_md = source / "SKILL.md"
    if skill_md.resolve() in skip_set:
        if _carry_forward(
            agent_name,
            dest,
            f"skill {dest.name}",
            previous_manifest,
            quiet=isinstance(skip_set, _AllExcept),
        ):
            managed.add(dest.name)
        return
    raw = _read_text(skill_md)
    try:
        substituted = strip_gating_keys(
            substitute_variables(raw, _builtin_skill_vars(vars_path)),
            _GATING_FRONTMATTER_KEYS,
        )
    except TemplateError as e:
        log("error", f"Failed to render skill '{source.name}': {e}")
        return
    for var in find_unreplaced_variables(substituted):
        log("warn", f"Unreplaced variable '{{{{{var}}}}}' in skill '{source.name}'")
    _materialize_skill_dir(source, dest, substituted, "skill", managed)


def _install_skills(
    candidate_dirs: list[Path],
    skills_parent: Path,
    agent_name: str,
    vars_path: Path,
    skip_set: Container[Path] = frozenset(),
    previous_manifest: "dict[str, AgentManifest] | None" = None,
) -> set[str]:
    """Install skills as materialized directories, overlay overriding base on collision.

    Args:
        candidate_dirs: Source skills directories in priority order (first wins).
        skills_parent: Parent directory whose ``skills`` subdir receives the
            materialized skill directories.
        agent_name: Target agent name, used to apply the requires-gate and
            ``targets``/``exclude_targets`` checks.
        vars_path: Variables JSON path for the target agent.
        skip_set: Resolved source paths to leave untouched.
        previous_manifest: The manifest from the previous installation.

    Returns:
        Set of installed skill names.
    """
    dest_root = skills_parent / "skills"

    def gate(skill_path: Path) -> bool:
        skill_md = skill_path / "SKILL.md"
        if not skill_md.is_file():
            return False
        if not _passes_requires_gate(skill_md, agent_name):
            log(
                "debug",
                f"Skipping skill '{skill_path.name}': requires gate not satisfied.",
            )
            return False
        if not _targets_agent(skill_md, agent_name):
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
        _materialize_builtin_skill(
            src,
            dest_root / name,
            vars_path,
            managed,
            agent_name,
            skip_set,
            previous_manifest,
        )
    return managed


def _install_plugin_skills(
    skill_pairs: list[tuple[str, Path, dict[str, str]]],
    skills_parent: Path,
    agent_name: str,
    already_managed: set[str],
) -> set[str]:
    """Install plugin-source skills as symlinks, lowest priority.

    Plugin skills never overwrite a built-in/overlay skill of the same name, and
    a duplicate name across plugins resolves in config order (first wins). A
    skill with a non-empty override map is materialized as a real directory
    with a patched ``SKILL.md``; one with no overrides is installed as a plain
    symlink, unchanged from today's behavior.

    Args:
        skill_pairs: ``(name, source_dir, overrides)`` triples from plugin
            discovery, in config order.
        skills_parent: Parent directory whose ``skills`` subdir receives symlinks.
        agent_name: Target agent name, for the requires-gate and
            ``targets``/``exclude_targets`` checks.
        already_managed: Skill names already installed this run (built-in or
            overlay); a plugin skill colliding with one is skipped.

    Returns:
        Set of installed plugin skill names.
    """
    dest_root = skills_parent / "skills"
    managed: set[str] = set()
    seen: set[str] = set()
    for name, src_dir, overrides in skill_pairs:
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
        if not _passes_requires_gate(skill_md, agent_name):
            log(
                "debug", f"Skipping plugin skill '{name}': requires gate not satisfied."
            )
            continue
        if not _targets_agent(skill_md, agent_name):
            log("debug", f"Skipping plugin skill '{name}': excluded for {agent_name}.")
            continue
        if overrides:
            _materialize_override_skill(src_dir, dest_root / name, overrides, managed)
        else:
            _install_symlink(src_dir, dest_root / name, "plugin skill", managed)
    return managed


_LONG_CONTEXT_SUFFIX = "[1m]"


def _claude_model_catalogue() -> dict[str, str]:
    """Map every model name this Claude Code install can select to its request value.

    Bedrock installs are the reason this exists: the CLI's tier aliases resolve to
    model ids an account may not serve, and an unservable id silently falls back to
    the session's default model, so ``modelOverrides`` is the only authoritative
    source there. Elsewhere ``availableModels`` names the models directly.

    ``CLAUDE_CODE_USE_BEDROCK`` only reaches processes that inherit the shell
    environment, so Bedrock is also recognised from settings keys only a Bedrock
    install has: ``awsCredentialExport`` and a non-empty ``modelOverrides``.

    Returns:
        Mapping of model name to the value to request, empty when unavailable.
    """
    try:
        settings = json.loads(
            (Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}
    is_bedrock = (
        bool(settings.get("awsCredentialExport"))
        or bool(settings.get("modelOverrides"))
        or os.environ.get("CLAUDE_CODE_USE_BEDROCK") == "1"
    )
    if is_bedrock:
        overrides = settings.get("modelOverrides")
        return overrides if isinstance(overrides, dict) else {}
    available = settings.get("availableModels")
    if not isinstance(available, list):
        return {}
    return {name: name for name in available if isinstance(name, str)}


def _resolve_variant_model(alias: str, catalogue: dict[str, str]) -> str:
    """Resolve a tier alias to the newest model of that family the install can run.

    Picks the highest version within the alias's family and prefers that version's
    long-context entry, never trading a newer model for an older long-context one.

    Args:
        alias: Tier alias from a variant token (e.g. ``haiku``).
        catalogue: Mapping from :func:`_claude_model_catalogue`.

    Returns:
        Resolved model value, or the alias unchanged when nothing matches.
    """
    pattern = re.compile(
        rf"claude-{re.escape(alias)}-(\d+(?:-\d+)*)"
        rf"({re.escape(_LONG_CONTEXT_SUFFIX)})?"
    )
    best: tuple[tuple[int, ...], bool] | None = None
    resolved = alias
    for name, value in catalogue.items():
        match = pattern.fullmatch(name)
        if match is None:
            continue
        rank = (
            tuple(int(part) for part in match.group(1).split("-")),
            match.group(2) is not None,
        )
        if best is None or rank > best:
            best, resolved = rank, value
    return resolved


_THINKING_OFF_VARIANT_MODELS = {"pi": frozenset({"haiku"})}


def _apply_variant_frontmatter(
    content: str,
    stem: str,
    model: str,
    effort: str,
    model_value: str,
    effort_value: str = "",
) -> str:
    """Rewrite a template's frontmatter for one generated model/effort variant.

    Overrides ``name`` to the variant's own name, appends a ``[model, effort
    effort]`` suffix to ``description``, and adds ``model``/``effort`` keys.
    All other frontmatter keys and the body are carried verbatim. A block-scalar
    (``>-``, ``|-``, etc.) description gets the suffix as a trailing continuation
    line, folded into the value by the YAML parser, rather than appended onto
    the indicator line itself where it would break the block-scalar syntax.

    Args:
        content: Template content, already stripped of gating keys.
        stem: Template filename stem (e.g. ``worker``).
        model: Tier alias for this variant, used in its name and description.
        effort: Effort level for this variant.
        model_value: Value to emit as the ``model`` key.
        effort_value: Value to emit as the ``effort`` key; defaults to ``effort``.

    Returns:
        Content with the variant's frontmatter applied.
    """
    split = split_frontmatter(content)
    if split is None:
        return content
    frontmatter_lines, body = split
    suffix = f"[{model}, {effort} effort]"
    lines = []
    in_description_block = False
    description_indent = "  "

    def close_description_block() -> None:
        nonlocal in_description_block
        if in_description_block:
            lines.append(f"{description_indent}{suffix}")
            in_description_block = False

    for line in frontmatter_lines:
        if in_description_block and (not line.strip() or line[:1] in (" ", "\t")):
            lines.append(line)
            if line.strip():
                description_indent = line[: len(line) - len(line.lstrip())]
            continue
        close_description_block()

        key = line.partition(": ")[0].strip()
        if key == "name":
            lines.append(f"name: {stem}-{model}-{effort}")
        elif key == "description":
            value = line.partition(": ")[2].strip()
            if re.fullmatch(r"[>|][+-]?", value):
                lines.append(line)
                in_description_block = True
            else:
                lines.append(f"{line} {suffix}")
        else:
            lines.append(line)
    close_description_block()

    lines.append(f"model: {model_value}")
    lines.append(f"effort: {effort_value or effort}")
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def _frontmatter_tokens(frontmatter: dict[str, str], key: str) -> list[str]:
    """Split a flat, comma-separated frontmatter value into stripped tokens.

    Args:
        frontmatter: Parsed frontmatter key/value pairs.
        key: Frontmatter key to read.

    Returns:
        Non-empty tokens, or an empty list when the key is absent.
    """
    return [t.strip() for t in frontmatter.get(key, "").split(",") if t.strip()]


def _expand_agent_variants(
    src_path: Path,
    resolve_model: Callable[[str], str] | None = None,
    variables: dict[str, str] | None = None,
    target: str = "",
) -> list[tuple[str, str]]:
    """Expand a ``generate_variants`` template source into generated variant files.

    Parses the flat, comma-separated ``generate_variants`` frontmatter key
    (each token a ``<model>-<effort>`` pair) and produces one generated file
    per token. Malformed tokens are logged and skipped rather than raising.
    The target's ``<target>_extra_variants`` tokens are added too, but only
    those whose model alias ``resolve_model`` maps to something else.

    Args:
        src_path: Template source file path.
        resolve_model: Maps a variant's tier alias to its ``model`` value;
            defaults to the Claude Code model catalogue.
        variables: Variables the source is rendered with before its
            frontmatter is parsed.
        target: Target agent name whose ``<target>_extra_variants`` apply.

    Returns:
        List of ``(generated_filename, generated_content)`` pairs.

    Raises:
        TemplateError: If the source is not a valid template.
    """
    content = substitute_variables(_read_text(src_path), variables or {})
    _, frontmatter = parse_frontmatter(content)
    tokens = _frontmatter_tokens(frontmatter, "generate_variants")
    extra_tokens = (
        _frontmatter_tokens(frontmatter, _override_key(target, "extra_variants"))
        if target
        else []
    )
    stripped = strip_gating_keys(content, _GATING_FRONTMATTER_KEYS)
    stem = src_path.stem
    if resolve_model is None:
        resolve_model = partial(
            _resolve_variant_model, catalogue=_claude_model_catalogue()
        )

    generated: list[tuple[str, str]] = []
    for token in [*tokens, *extra_tokens]:
        parts = token.split("-")
        if len(parts) != 2:
            log(
                "warn", f"Skipping malformed variant token '{token}' in {src_path.name}"
            )
            continue
        model, effort = parts
        resolved_model = resolve_model(model)
        if token in extra_tokens and resolved_model == model:
            continue
        filename = f"{stem}-{model}-{effort}.md"
        generated.append(
            (
                filename,
                _apply_variant_frontmatter(
                    stripped,
                    stem,
                    model,
                    effort,
                    resolved_model,
                    "off"
                    if model in _THINKING_OFF_VARIANT_MODELS.get(target, ())
                    else "",
                ),
            )
        )
    return generated


@dataclass(frozen=True)
class _RuleSources:
    """Rule sources an agent can pull in through ``rules``."""

    sources: dict[str, tuple[Path, bool]]
    vars_path: Path
    agent_name: str

    @classmethod
    def collect(
        cls,
        agent: _Agent,
        overlay_dirs: Sequence[Path],
        skip_set: Container[Path] = frozenset(),
    ) -> "_RuleSources":
        """Collect rule sources by installed filename stem, in install priority order.

        Args:
            agent: The agent configuration the rules are rendered for.
            overlay_dirs: Overlay prompts directories in priority order.
            skip_set: Resolved source paths left untouched by the install; excluded.

        Returns:
            Rule sources mapping each stem to ``(source_path, is_agent_specific)``.
        """
        collected = _collect_content_srcs(
            agent,
            "rules",
            agent.root_dir / "shared" / "rules",
            [d / "shared" / "rules" for d in overlay_dirs],
            [d / agent.name / "rules" for d in overlay_dirs],
        )
        return cls(
            {
                Path(name).stem: (src, specific)
                for name, src, specific in collected
                if src.resolve() not in skip_set
            },
            agent.vars_path(),
            agent.name,
        )

    def body(self, name: str) -> str | None:
        """Render a rule as installed, without its frontmatter.

        Args:
            name: Rule filename stem.

        Returns:
            The rule body, or ``None`` when rendering fails.
        """
        src, agent_specific = self.sources[name]
        try:
            content = (
                _linked_content(src)
                if agent_specific
                else _rendered_content(src, self.vars_path, self.agent_name)
            )
        except Exception as e:
            log("error", f"Failed to render included rule '{name}': {e}")
            return None
        for var in find_unreplaced_variables(content):
            log(
                "warn", f"Unreplaced variable '{{{{{var}}}}}' in included rule '{name}'"
            )
        split = split_frontmatter(content)
        return (split[1] if split else content).strip("\n")


def _omit_claude_md_for_rules(content: str) -> str:
    """Set ``omitClaudeMd: true`` on agent content that does not set it.

    Args:
        content: Agent content whose source names its rules with ``rules``.

    Returns:
        ``content`` with ``omitClaudeMd: true`` unless already present.
    """
    if "omitClaudeMd" in parse_frontmatter(content)[1]:
        return content
    return content.replace("---\n", "---\nomitClaudeMd: true\n", 1)


def _append_included_rules(
    content: str, src: Path, rules: "_RuleSources | None"
) -> str:
    """Append the rules named by an agent source's ``rules`` key.

    A source with a ``rules`` key also gets ``omitClaudeMd: true`` unless it
    already sets ``omitClaudeMd``.

    Args:
        content: The agent content to install.
        src: Agent source path, whose frontmatter names the rules.
        rules: Available rule sources, or ``None`` when none are collected.

    Returns:
        ``content`` with ``omitClaudeMd: true`` set unless already present,
        followed by each included rule body.
    """
    _, frontmatter = parse_frontmatter(_read_text(src))
    if "rules" not in frontmatter:
        return content
    content = _omit_claude_md_for_rules(content)
    if rules is None:
        return content
    bodies: list[str] = []
    for token in _frontmatter_tokens(frontmatter, "rules"):
        if token not in rules.sources:
            log("warn", f"Skipping unknown included rule '{token}' in {src.name}")
        elif (body := rules.body(token)) is not None:
            bodies.append(body)
    if not bodies:
        return content
    return content.rstrip("\n") + "\n\n" + "\n\n".join(bodies) + "\n"


@dataclass(frozen=True)
class _PiRuleBundle:
    """Pi rules rendered once, each with the roles it is selected for.

    Attributes:
        texts: Rendered rule text by installed filename.
        roles: Roles each rule is selected for, by installed filename.
        held_back: Skipped rules that have no cached text and selectors.
        failures: ``(source, message)`` for each rule that failed to render.
        selector_errors: ``(source, message)`` for each rule with invalid
            ``roles``.
    """

    texts: dict[str, str]
    roles: dict[str, frozenset[str]]
    held_back: tuple[str, ...] = ()
    failures: tuple[tuple[Path, str], ...] = ()
    selector_errors: tuple[tuple[Path, str], ...] = ()

    @classmethod
    def build(
        cls,
        agent: _Agent,
        overlay_dirs: Sequence[Path],
        skip_set: Container[Path] = frozenset(),
        previous_manifest: "dict[str, AgentManifest] | None" = None,
        vars_path: Path | None = None,
    ) -> "_PiRuleBundle":
        """Render every rule pi installs, once, with its role selectors.

        Skipped rules take their cached text and selectors together.

        Args:
            agent: The pi agent configuration.
            overlay_dirs: Overlay prompts directories in priority order.
            skip_set: Resolved source paths left untouched by the install.
            previous_manifest: The manifest from the previous installation.
            vars_path: Variables JSON path, instead of the agent's own.

        Returns:
            The bundle.
        """
        from .manifest import read_rendered_rule

        vars_path = vars_path or agent.vars_path()
        cached_roles = (
            (previous_manifest or {}).get(agent.name, {}).get("pi_rule_roles", {})
        )
        texts: dict[str, str] = {}
        roles: dict[str, frozenset[str]] = {}
        held_back: list[str] = []
        failures: list[tuple[Path, str]] = []
        selector_errors: list[tuple[Path, str]] = []
        for name, src, agent_specific in _collect_content_srcs(
            agent,
            "rules",
            agent.root_dir / "shared" / "rules",
            [d / "shared" / "rules" for d in overlay_dirs],
            [d / agent.name / "rules" for d in overlay_dirs],
        ):
            if src.resolve() in skip_set:
                cached = read_rendered_rule(agent.name, name)
                if cached is not None and name in cached_roles:
                    texts[name], roles[name] = cached, frozenset(cached_roles[name])
                    continue
                if not isinstance(skip_set, _AllExcept):
                    held_back.append(name)
                    continue
            try:
                if agent_specific:
                    texts[name] = _linked_content(src)
                    declared = _read_text(src)
                else:
                    texts[name] = _rendered_content(src, vars_path, agent.name)
                    declared = substitute_template(str(src), str(vars_path))
            except Exception as e:
                failures.append((src, f"Failed to render rules/{name}: {e}"))
                continue
            try:
                roles[name] = _parse_roles(declared, f"rules/{name}")
            except ValueError as e:
                selector_errors.append((src, str(e)))
                del texts[name]
        return cls(
            texts, roles, tuple(held_back), tuple(failures), tuple(selector_errors)
        )

    def lead_names(self) -> list[str]:
        """List the rules in the global ``AGENTS.md``: the core and lead rules.

        Returns:
            Installed filenames, sorted.
        """
        return sorted(
            name for name in self.texts if self.roles[name] & {"core", "lead"}
        )

    def lead_text(self) -> str:
        """Return the global ``AGENTS.md`` text: the core and lead rules.

        Returns:
            The selected rules joined in installed-filename order.
        """
        return normalize_whitespace(
            "\n\n".join(self.texts[name] for name in self.lead_names())
        )

    def select(self, frontmatter: dict[str, str]) -> list[str]:
        """Choose the rules an agent definition references.

        Args:
            frontmatter: The agent source's parsed frontmatter.

        Returns:
            Installed filenames, sorted, each once. A source with ``rules``
            gets those rules, one with ``omitClaudeMd`` gets none, a known
            role gets the core rules and its own, any other gets every rule.
        """
        if "rules" in frontmatter:
            names = {
                f"{token}.md" for token in _frontmatter_tokens(frontmatter, "rules")
            }
            return sorted(names & self.texts.keys())
        if frontmatter.get("omitClaudeMd") == "true":
            return []
        role = frontmatter.get("name", "")
        if role not in _AGENT_ROLES:
            return sorted(self.texts)
        return sorted(name for name, r in self.roles.items() if r & {"core", role})


def _reference_rules(
    content: str, src_frontmatter: dict[str, str], bundle: _PiRuleBundle
) -> str:
    """Put the rule references an agent source selects ahead of its body.

    Args:
        content: Generated agent content.
        src_frontmatter: The agent source's parsed frontmatter.
        bundle: The rules pi installs.

    Returns:
        ``content`` with ``omitClaudeMd: true`` set when the source names its
        rules, and one ``@../rules/<name>`` line per selected rule before the
        body.
    """
    if "rules" in src_frontmatter:
        content = _omit_claude_md_for_rules(content)
    references = [f"@../rules/{name}" for name in bundle.select(src_frontmatter)]
    split = split_frontmatter(content)
    if not references or split is None:
        return content
    head = content[: len(content) - len(split[1])]
    return head + "\n".join(references) + "\n\n" + split[1].lstrip("\n")


def _expanded_definition(content: str, rule_texts: Mapping[str, str]) -> str:
    """Expand a definition's rule references the way herdsman does at launch.

    Each whole-line ``@../rules/<name>`` reference is replaced by that rule's
    text. A rule is included once and references are not expanded recursively.

    Args:
        content: Installed definition content.
        rule_texts: Rendered rule text by installed filename.

    Returns:
        The definition body, outer blank lines trimmed, with references replaced.

    Raises:
        ValueError: A reference names no rule, or a rule's text is not
            NUL-free UTF-8.
    """
    split = split_frontmatter(content)
    body = (split[1] if split else content).strip("\n")
    included: set[str] = set()
    lines: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("@../rules/"):
            lines.append(line)
            continue
        name = stripped.removeprefix("@../rules/")
        if name not in rule_texts:
            raise ValueError(f"unresolved rule reference '{stripped}'")
        if name in included:
            continue
        text = rule_texts[name]
        try:
            text.encode()
        except UnicodeEncodeError as e:
            raise ValueError(f"rule '{name}' is not valid UTF-8") from e
        if "\0" in text:
            raise ValueError(f"rule '{name}' contains a NUL byte")
        included.add(name)
        lines.append(text)
    return "\n".join(lines)


def _pi_definitions(
    candidate_dirs: list[Path],
    bundle: _PiRuleBundle,
    dialect: "_AgentDialect",
    variables: dict[str, str],
) -> tuple[list[tuple[str, Path, str]], list[Path]]:
    """Generate every pi subagent definition the install would write.

    Args:
        candidate_dirs: Source agent directories in priority order (first wins).
        bundle: The rules pi installs.
        dialect: The pi subagent definition dialect.
        variables: Variables the sources are rendered with.

    Returns:
        The ``(filename, source, content)`` of each definition, and the
        sources that failed to render.
    """
    definitions: list[tuple[str, Path, str]] = []
    failed: list[Path] = []
    for name, src in _resolve_priority_sources(
        candidate_dirs, lambda d: sorted(d.glob("*.md")), lambda p: p.name
    ):
        try:
            rendered = substitute_variables(_read_text(src), variables)
            generated = _generated_agents(
                src, rendered, name, dialect, variables, "pi", None, bundle
            )
        except TemplateError:
            failed.append(src)
            continue
        definitions.extend((gen_name, src, content) for gen_name, content in generated)
    return definitions, failed


@dataclass(frozen=True)
class _AgentDialect:
    """How a target agent's subagent definitions differ from Claude Code's.

    Attributes:
        translate: Rewrites installed agent content, or ``None`` to install
            Claude Code definitions as they are.
        resolve_model: Maps a variant's tier alias to its ``model`` value, or
            ``None`` to use the Claude Code model catalogue.
    """

    translate: Callable[[str], str] | None = None
    resolve_model: Callable[[str], str] | None = None


_CLAUDE_AGENT_DIALECT = _AgentDialect()

_PI_TOOL_NAMES = {
    "Read": ["read"],
    "Write": ["write"],
    "Edit": ["edit"],
    "Bash": ["bash"],
    "Grep": ["grep"],
    "Glob": ["find"],
    "LS": ["ls"],
    "TaskCreate": ["ext:tower-do/tower_do", "ext:tower-do-patch/tower_do_patch"],
    "TaskUpdate": ["ext:tower-do/tower_do", "ext:tower-do-patch/tower_do_patch"],
    "TaskGet": ["ext:tower-do/tower_do_status"],
    "TaskList": ["ext:tower-do/tower_do_status"],
    "SendMessage": ["ext:tower-do/tower_do_talk"],
}
_PI_DROPPED_FRONTMATTER_KEYS = {"color", "omitClaudeMd"}


_HERDSMAN_STRING_KEYS = {"name", "description", "model"}
_HERDSMAN_ARRAY_KEYS = {
    "tools": "tools",
    "disallowedTools": "excludeTools",
    "allowed_subagents": "agents",
}
_HERDSMAN_BOOLEAN_KEYS = {"skills": "inheritSkills"}


def _pi_skill_paths(
    value: str, skill_sources: Sequence[Path], agent_dir: Path, strict: bool = True
) -> list[str]:
    """Resolve a ``pi_skills`` list to the skill files a delegate loads.

    Args:
        value: Comma-separated skill names; a trailing ``?`` marks an optional skill.
        skill_sources: Skill source directories, whose subdirectories are skills.
        agent_dir: Pi's config directory, holding installed skills and packages.
        strict: Whether a required skill that resolves nowhere is an error.

    Returns:
        Absolute ``SKILL.md`` path per resolvable skill: an installed skill from
        ``skill_sources``, else a skill shipped by an installed pi package.

    Raises:
        ValueError: A required skill resolves nowhere and ``strict`` is set.
    """
    paths: list[str] = []
    for entry in (item.strip() for item in value.split(",")):
        name = entry.removesuffix("?")
        if any((source / name / "SKILL.md").is_file() for source in skill_sources):
            paths.append(str(agent_dir / "skills" / name / "SKILL.md"))
        elif packaged := sorted(
            path
            for pattern in ("*", "@*/*")
            for path in agent_dir.glob(
                f"npm/node_modules/{pattern}/skills/{name}/SKILL.md"
            )
        ):
            paths.append(str(packaged[0]))
        elif strict and entry == name:
            raise ValueError(f"pi_skills: skill '{name}' not found")
    return paths


def _herdsman_agent_content(
    content: str,
    tool_names: Mapping[str, list[str]],
    resolve_model: Callable[[str], str],
    resolve_skills: Callable[[str], list[str]],
) -> str:
    """Rewrite a Claude Code subagent definition for the herdsman extension.

    Args:
        content: Installed Claude Code agent content.
        tool_names: Herdsman tool names for each Claude Code tool name.
        resolve_model: Maps the definition's ``model`` tier alias to its model.
        resolve_skills: Maps a ``pi_skills`` value to skill file paths.

    Returns:
        Content with herdsman's frontmatter and the body unchanged.

    Raises:
        ValueError: A frontmatter key has no herdsman equivalent.
    """
    split = split_frontmatter(content)
    if split is None:
        return content
    frontmatter = resolve_frontmatter(split[0]) or {}
    lines: list[str] = []
    for key, value in frontmatter.items():
        if key in _HERDSMAN_STRING_KEYS:
            text = resolve_model(value) if key == "model" else value
            lines.append(f"{key}: {json.dumps(text)}")
        elif key == "effort":
            lines.append(f"thinking: {value}")
        elif key in _HERDSMAN_ARRAY_KEYS:
            names = [name.strip() for name in value.split(",")]
            if key != "allowed_subagents":
                names = [
                    herdsman
                    for name in names
                    for herdsman in tool_names.get(
                        name,
                        [name]
                        if name.islower()
                        and (key == "disallowedTools" or not name.startswith("mcp__"))
                        else [],
                    )
                ]
            if names:
                lines.append(
                    f"{_HERDSMAN_ARRAY_KEYS[key]}: {json.dumps(list(dict.fromkeys(names)))}"
                )
        elif key == "pi_skills":
            lines.append(f"skills: {json.dumps(resolve_skills(value))}")
        elif key == "extensions":
            names = [
                n.strip().strip("'\"")
                for n in value.strip("[]").split(",")
                if n.strip()
            ]
            lines.append("noExtensions: true")
            if names:
                lines.append(f"extensions: {json.dumps(names)}")
        elif key in _HERDSMAN_BOOLEAN_KEYS:
            lines.append(
                f"{_HERDSMAN_BOOLEAN_KEYS[key]}: {str(value == 'true').lower()}"
            )
        elif key not in _PI_DROPPED_FRONTMATTER_KEYS:
            raise ValueError(
                f"No herdsman equivalent for agent frontmatter key '{key}'"
            )
    inherit = str(frontmatter.get("omitClaudeMd") != "true").lower()
    lines += [
        "systemPromptMode: append",
        "inheritGlobalContext: false",
        f"inheritProjectContext: {inherit}",
    ]
    return "---\n" + "\n".join(lines) + "\n---\n" + split[1]


def _pi_agent_models(fragments: list[Path]) -> dict[str, str]:
    """Collect the tier-to-model map declared by every ``pi/agent-models.json``.

    Args:
        fragments: Candidate fragment paths, core first, then overlays.

    Returns:
        Model for each tier alias; the last fragment declaring a tier wins.
    """
    models: dict[str, str] = {}
    for fragment in fragments:
        if fragment.is_file():
            models.update(json.loads(_read_text(fragment)))
    return models


def _agent_source_dirs(
    root_dir: Path, overlay_dirs: Sequence[Path], target: str
) -> list[Path]:
    """Return the subagent source directories a target installs from.

    Args:
        root_dir: This package's own prompts directory.
        overlay_dirs: Overlay prompts directories in priority order.
        target: Target agent name.

    Returns:
        Directories in priority order (first wins): each root's ``pi`` agents
        for pi, its ``claude-code`` agents where it applies - every root for
        Claude Code, only this package's own for pi - then its ``shared``
        agents.
    """
    dirs: list[Path] = []
    for root in (*overlay_dirs, root_dir):
        if target == "pi":
            dirs.append(root / "pi" / "agents")
        if target == "claude-code" or (target == "pi" and root == root_dir):
            dirs.append(root / "claude-code" / "agents")
        dirs.append(root / "shared" / "agents")
    return dirs


def _pi_agent_dialect(
    root_dir: Path, overlay_dirs: Sequence[Path], strict_skills: bool = True
) -> _AgentDialect:
    """Build the pi subagent dialect from the core and overlay model maps.

    Args:
        root_dir: This package's own prompts directory.
        overlay_dirs: Overlay prompts directories in priority order.
        strict_skills: Whether a ``pi_skills`` entry that resolves nowhere fails.

    Returns:
        Dialect translating definitions to pi, with mapped tiers resolved.
    """
    models = _pi_agent_models(
        [root_dir / "pi" / "agent-models.json"]
        + [d / "pi" / "agent-models.json" for d in overlay_dirs]
    )

    def resolve_model(tier: str) -> str:
        return models.get(tier, tier)

    tool_names = {
        **{
            claude: [pi.rpartition("/")[2] for pi in pis]
            for claude, pis in _PI_TOOL_NAMES.items()
        },
        "Agent": ["agent"],
    }
    return _AgentDialect(
        partial(
            _herdsman_agent_content,
            tool_names=tool_names,
            resolve_model=resolve_model,
            resolve_skills=partial(
                _pi_skill_paths,
                skill_sources=[
                    *(d / "shared" / "skills" for d in overlay_dirs),
                    root_dir / "shared" / "skills",
                    root_dir / "pi" / "skills",
                    *(d / "pi" / "skills" for d in overlay_dirs),
                ],
                agent_dir=_pi_agent_dir(),
                strict=strict_skills,
            ),
        ),
        resolve_model,
    )


def _install_disabled_definitions(agents_dir: Path) -> set[str]:
    """Write overlays that disable herdsman's bundled agent definitions.

    Args:
        agents_dir: Destination agents directory.

    Returns:
        Set of installed overlay filenames.
    """
    managed: set[str] = set()
    for name in HERDSMAN_DISABLED_DEFINITIONS:
        filename = f"{name}.md"
        dest = agents_dir / filename
        if dest.is_symlink():
            dest.unlink()
        _write_if_changed(
            dest,
            f"---\nname: {name}\nenabled: false\n---\n",
            f"agent {filename}",
        )
        managed.add(filename)
    return managed


def _install_herdsman_overlays(overlays_dir: Path, agents_dir: Path) -> set[str]:
    """Copy overlays of herdsman's bundled agent definitions verbatim.

    Args:
        overlays_dir: Source directory of overlay definitions.
        agents_dir: Destination agents directory.

    Returns:
        Set of installed overlay filenames.
    """
    managed: set[str] = set()
    for src in sorted(overlays_dir.glob("*.md")):
        dest = agents_dir / src.name
        if dest.is_symlink():
            dest.unlink()
        _write_if_changed(dest, _read_text(src), f"agent {src.name}")
        managed.add(src.name)
    return managed


def _generated_agents(
    src: Path,
    rendered: str,
    name: str,
    dialect: _AgentDialect,
    variables: dict[str, str],
    agent_name: str,
    rules: "_RuleSources | None",
    bundle: "_PiRuleBundle | None",
) -> list[tuple[str, str]]:
    """Generate the installed files for one subagent source.

    Args:
        src: Agent source path.
        rendered: The source after variable substitution.
        name: The source's filename.
        dialect: The target agent's subagent definition dialect.
        variables: Variables the source is rendered with.
        agent_name: Target agent name.
        rules: Rule sources that ``rules`` keys resolve against.
        bundle: Rules to reference instead of inlining, if any.

    Returns:
        ``(filename, content)`` for each variant, in the target's dialect.
    """
    frontmatter = parse_frontmatter(rendered)[1]
    files = (
        _expand_agent_variants(src, dialect.resolve_model, variables, agent_name)
        if "generate_variants" in frontmatter
        else [(name, strip_gating_keys(rendered, _GATING_FRONTMATTER_KEYS))]
    )
    generated: list[tuple[str, str]] = []
    for gen_name, gen_content in files:
        content = (
            _reference_rules(gen_content, frontmatter, bundle)
            if bundle is not None
            else _append_included_rules(gen_content, src, rules)
        )
        generated.append(
            (gen_name, dialect.translate(content) if dialect.translate else content)
        )
    return generated


def _install_agents(
    candidate_dirs: list[Path],
    agents_dir: Path,
    skip_set: Container[Path] = frozenset(),
    previous_manifest: "dict[str, AgentManifest] | None" = None,
    rules: "_RuleSources | None" = None,
    agent_name: str = "claude-code",
    dialect: _AgentDialect = _CLAUDE_AGENT_DIALECT,
    variables: dict[str, str] | None = None,
    bundle: "_PiRuleBundle | None" = None,
) -> set[str]:
    """Install subagent definitions as rendered files.

    Overlay dirs override base on filename collision (first wins). Each source
    is rendered with ``variables`` and written to ``agents_dir``; one whose
    frontmatter has ``generate_variants`` is expanded into per-model/effort
    files.

    Args:
        candidate_dirs: Source agent directories in priority order (first wins).
        agents_dir: Destination agents directory (e.g. ~/.claude/agents).
        skip_set: Resolved source paths to leave untouched.
        previous_manifest: The manifest from the previous installation.
        rules: Rule sources that ``rules`` keys resolve against.
        agent_name: Target agent name, for the manifest entry.
        dialect: The target agent's subagent definition dialect.
        variables: Variables the sources are rendered with.
        bundle: Rules to reference from definitions instead of inlining them.

    Returns:
        Set of installed agent filenames.
    """
    previous_manifest = previous_manifest if previous_manifest is not None else {}
    log("info", f"[{agent_name}] Installing agents...")
    managed: set[str] = set()
    resolved = _resolve_priority_sources(
        candidate_dirs,
        lambda d: sorted(d.glob("*.md")),
        lambda p: p.name,
    )
    variables = variables or {}
    for name, src in resolved:
        try:
            rendered = substitute_variables(_read_text(src), variables)
        except TemplateError as e:
            log("error", f"Failed to render agent '{name}': {e}")
            continue
        _, frontmatter = parse_frontmatter(rendered)
        has_variants = "generate_variants" in frontmatter
        if src.resolve() in skip_set:
            previous_files = previous_manifest.get(agent_name, {}).get("files", [])
            if has_variants:
                prefix = f"{src.stem}-"
                for filepath in previous_files:
                    prev_path = Path(filepath)
                    if (
                        prev_path.parent == agents_dir
                        and prev_path.name.startswith(prefix)
                        and prev_path.name.endswith(".md")
                        and _carry_forward(
                            agent_name,
                            prev_path,
                            f"agent {prev_path.name}",
                            previous_manifest,
                            quiet=isinstance(skip_set, _AllExcept),
                        )
                    ):
                        managed.add(prev_path.name)
            elif _carry_forward(
                agent_name,
                agents_dir / name,
                f"agent {name}",
                previous_manifest,
                quiet=isinstance(skip_set, _AllExcept),
            ):
                managed.add(name)
            continue
        for gen_name, gen_content in _generated_agents(
            src, rendered, name, dialect, variables, agent_name, rules, bundle
        ):
            dest = agents_dir / gen_name
            if dest.is_symlink():
                dest.unlink()
            _write_if_changed(dest, gen_content, f"agent {gen_name}")
            managed.add(gen_name)
    return managed


def _pi_rules_dir() -> Path:
    """Return the directory holding pi's shared rule files.

    Returns:
        ``rules`` under pi's config directory.
    """
    return _pi_agent_dir() / "rules"


def _install_pi_rule_files(bundle: _PiRuleBundle, rules_dir: Path) -> set[str]:
    """Write each rule as a file the agent definitions reference.

    Args:
        bundle: The rules pi installs.
        rules_dir: Destination directory.

    Returns:
        Installed rule filenames, or an empty set when any rule failed to write.
    """
    log("info", "[pi] Installing rule files...")
    rules_dir.mkdir(parents=True, exist_ok=True)
    for name, text in bundle.texts.items():
        dest = rules_dir / name
        if dest.is_symlink():
            dest.unlink()
        _write_if_changed(dest, text, f"rules/{name}")
    if not all((rules_dir / name).is_file() for name in bundle.texts):
        return set()
    return set(bundle.texts)


def _install_pi_lead_rules(agent: _Agent, bundle: _PiRuleBundle) -> set[str]:
    """Write the global ``AGENTS.md`` holding the core and lead rules.

    Args:
        agent: The pi agent configuration.
        bundle: The rules pi installs.

    Returns:
        The installed filename.
    """
    from .manifest import write_rendered_rules

    log("info", f"[{agent.name}] Installing rules...")
    output = bundle.lead_text()
    for var in find_unreplaced_variables(output):
        log("warn", f"Unreplaced variable '{{{{{var}}}}}' in {_PiAgent.AGENTS_MD}")
    dest_dir = agent.dest_dir("rules")
    dest_dir.mkdir(parents=True, exist_ok=True)
    _write_if_changed(dest_dir / _PiAgent.AGENTS_MD, output, _PiAgent.AGENTS_MD)
    write_rendered_rules(agent.name, bundle.texts)
    return {_PiAgent.AGENTS_MD}


def _previous_pi_bundle_files(
    previous_manifest: "dict[str, AgentManifest]", agents_dir: Path, agents_md: Path
) -> list[str]:
    """List the pi files of the last installed rule bundle.

    Args:
        previous_manifest: The manifest from the previous installation.
        agents_dir: Pi's agent definitions directory.
        agents_md: Pi's global ``AGENTS.md``.

    Returns:
        The previous definitions, rule files and ``AGENTS.md``.
    """
    return [
        f
        for f in previous_manifest.get("pi", {}).get("files", [])
        if Path(f).parent in (agents_dir, _pi_rules_dir()) or Path(f) == agents_md
    ]


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


def try_install_hooks_antigravity() -> None:
    """Patch Antigravity hooks.json with cline-hooks entries if available."""
    import shutil
    import subprocess

    binary = shutil.which("cline-hook")
    if not binary:
        log(
            "debug",
            "cline-hook not found on PATH, skipping Antigravity hook injection.",
        )
        return
    subprocess.run([binary, "install", "antigravity"], check=False)


_PI_DEFAULT_KEYS = (
    "defaultProvider",
    "defaultModel",
    "defaultTools",
    "steeringMode",
    "followUpMode",
    "cacheWarming",
    "enableInstallTelemetry",
)


def _package_source(entry: str | dict[str, Any]) -> str:
    """Return a pi ``packages`` entry's source, whether string or object form."""
    return entry if isinstance(entry, str) else str(entry.get("source", ""))


def _pi_packages(fragments: list[Path]) -> list[str]:
    """Collect the pi packages declared by every ``pi/settings.json`` fragment.

    Args:
        fragments: Candidate fragment paths, core first, then overlays.

    Returns:
        Package sources whose gates pass, in declaration order, without duplicates.
    """
    packages: list[str] = []
    for fragment in fragments:
        if not fragment.is_file():
            continue
        for entry in json.loads(_read_text(fragment)).get("packages", []):
            if isinstance(entry, dict) and not _requirements_met(entry, "pi"):
                continue
            source = _package_source(entry)
            if source not in packages:
                packages.append(source)
    return packages


def _pi_defaults(fragments: list[Path]) -> dict[str, Any]:
    """Collect the default provider, model and tools declared by ``pi/settings.json`` fragments.

    Args:
        fragments: Candidate fragment paths, core first, then overlays.

    Returns:
        the ``_PI_DEFAULT_KEYS`` values; the last fragment declaring a key wins.
    """
    defaults: dict[str, Any] = {}
    for fragment in fragments:
        if fragment.is_file():
            declared = json.loads(_read_text(fragment))
            defaults.update(
                {key: declared[key] for key in _PI_DEFAULT_KEYS if key in declared}
            )
    return defaults


def _install_pi_extensions(
    source_dirs: list[Path], dest_dir: Path, previous_files: Container[str]
) -> list[str]:
    """Copy every ``*.ts`` pi extension from the source directories into ``dest_dir``.

    A destination file that exists but was not installed by llm-prompts is left alone.

    Args:
        source_dirs: Candidate ``pi/extensions`` directories, core first, then overlays.
        dest_dir: pi's extensions directory.
        previous_files: File paths llm-prompts installed for pi last time.

    Returns:
        Installed file paths; a later source wins on a filename collision.
    """
    sources: dict[str, Path] = {}
    for source_dir in source_dirs:
        if source_dir.is_dir():
            sources.update(
                {path.name: path for path in sorted(source_dir.glob("*.ts"))}
            )
    if sources:
        dest_dir.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for name, path in sources.items():
        dest = dest_dir / name
        if dest.exists() and str(dest) not in previous_files:
            log(
                "warn",
                f"[pi] Skipped extension {name}: {dest} is not managed by llm-prompts.",
            )
            continue
        _write_text(dest, _read_text(path))
        installed.append(str(dest))
    return installed


def _seed_pi_files(dirs: list[Path]) -> None:
    """Copy ``pi/seed/`` files into the pi agent directory where absent.

    Args:
        dirs: Prompts directories, core first, then overlays; a later directory
            replaces an earlier one's file at the same relative path.
    """
    seeds: dict[Path, Path] = {}
    for prompts_dir in dirs:
        seed_dir = prompts_dir / "pi" / "seed"
        for source in sorted(seed_dir.rglob("*")):
            if source.is_file():
                seeds[source.relative_to(seed_dir)] = source
    for relative, source in seeds.items():
        dest = _pi_agent_dir() / relative
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            _write_text(dest, _read_text(source))
            log("success", f"[pi] Seeded {dest}.")


def _sync_pi_packages(
    wanted: list[str], previous: list[str], defaults: dict[str, Any] | None = None
) -> None:
    """Make pi's global settings list exactly the managed packages in ``wanted``.

    Packages the user added themselves are left alone; a package llm-prompts
    managed before but no longer declares is removed. Each default the user's
    settings lack is filled in; one already set is kept.

    Args:
        wanted: Package sources llm-prompts now declares.
        previous: Package sources llm-prompts managed at the last install.
        defaults: Default provider, model and tools llm-prompts now declares.
    """
    settings_path = _pi_agent_dir() / "settings.json"
    settings: dict[str, Any] = (
        json.loads(_read_text(settings_path)) if settings_path.exists() else {}
    )
    current: list[str | dict[str, Any]] = settings.get("packages", [])
    stale = set(previous) - set(wanted)
    packages = [entry for entry in current if _package_source(entry) not in stale]
    present = {_package_source(entry) for entry in packages}
    packages.extend(source for source in wanted if source not in present)
    missing_defaults = {k: v for k, v in (defaults or {}).items() if k not in settings}
    if packages == current and not missing_defaults:
        return
    settings["packages"] = packages
    settings.update(missing_defaults)
    _write_text(settings_path, json.dumps(settings, indent=2) + "\n")
    log("success", f"[pi] Updated packages in {settings_path}.")


def _install_pi_packages(sources: list[str]) -> bool:
    """Run ``pi install`` for each npm package whose pinned version is not installed.

    Args:
        sources: Package sources llm-prompts declares.

    Returns:
        Whether any ``pi install`` failed.
    """
    pi = shutil.which("pi")
    if pi is None:
        log("warn", "[pi] `pi` not found, skipping package installs.")
        return False
    failed = False
    for source in sources:
        if not source.startswith("npm:"):
            continue
        name, _, version = source.removeprefix("npm:").rpartition("@")
        if not name:
            name, version = source.removeprefix("npm:"), ""
        manifest = _pi_agent_dir() / "npm" / "node_modules" / name / "package.json"
        if manifest.exists() and (
            not version or json.loads(_read_text(manifest)).get("version") == version
        ):
            continue
        if subprocess.run([pi, "install", source], check=False).returncode:
            log("error", f"[pi] `pi install {source}` failed.")
            failed = True
    return failed


def _enabled_claude_plugin_paths() -> list[Path] | None:
    """Return install paths of the Claude plugins enabled in the user's settings.

    Returns:
        Existing install directories, or None when a Claude file is unparseable.
    """
    claude_dir = Path.home() / ".claude"
    settings_path = claude_dir / "settings.json"
    installed_path = claude_dir / "plugins" / "installed_plugins.json"
    if not settings_path.exists() or not installed_path.exists():
        return []
    try:
        enabled = json.loads(_read_text(settings_path)).get("enabledPlugins", {})
        installed = json.loads(_read_text(installed_path)).get("plugins", {})
    except json.JSONDecodeError:
        log("warn", "[pi] Could not parse Claude plugin files, skipping plugins.")
        return None
    paths: list[Path] = []
    for key in (key for key, on in enabled.items() if on):
        records = installed.get(key) or [{}]
        path = Path(records[0].get("installPath", ""))
        if path.is_absolute() and path.is_dir():
            paths.append(path)
        else:
            log("warn", f"[pi] Plugin {key} is not installed, skipping.")
    return paths


def _claude_plugin_skill_dirs() -> list[str] | None:
    """Return the skill dirs of the enabled Claude plugins, or None if unreadable."""
    plugin_paths = _enabled_claude_plugin_paths()
    if plugin_paths is None:
        return None
    return [str(p / "skills") for p in plugin_paths if (p / "skills").is_dir()]


def _sync_pi_skills(wanted: list[str], previous: list[str]) -> None:
    """Make pi's ``skills`` setting list exactly the managed dirs in ``wanted``.

    Entries the user added themselves are left alone.

    Args:
        wanted: Skill dirs llm-prompts now declares.
        previous: Skill dirs llm-prompts managed at the last install.
    """
    settings_path = _pi_agent_dir() / "settings.json"
    settings: dict[str, Any] = (
        json.loads(_read_text(settings_path)) if settings_path.exists() else {}
    )
    current: list[str] = settings.get("skills", [])
    stale = set(previous) - set(wanted)
    skills = [entry for entry in current if entry not in stale]
    skills.extend(path for path in wanted if path not in skills)
    if skills == current:
        return
    settings["skills"] = skills
    _write_text(settings_path, json.dumps(settings, indent=2) + "\n")
    log("success", f"[pi] Updated skills in {settings_path}.")


_PI_PERMISSION_ACTIONS = (("allow", "allow"), ("ask", "ask"), ("deny", "deny"))


def _claude_mcp_permissions() -> dict[str, str] | None:
    """Translate Claude's MCP permission rules into pi's ``mcp`` permission rules.

    Only rules for servers in pi's ``mcp.json`` are used. A server with Claude
    rules but no server-wide allow defaults to ``ask``, ahead of its tool rules.

    Returns:
        Ordered pi rules (last match wins), or None when Claude's settings are unparseable.
    """
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        permissions = json.loads(_read_text(settings_path)).get("permissions", {})
    except json.JSONDecodeError:
        log("warn", "[pi] Could not parse Claude settings, skipping MCP permissions.")
        return None
    pi_servers = sorted(
        _read_mcp_servers(_pi_agent_dir() / "mcp.json", "mcp.json"),
        key=len,
        reverse=True,
    )
    server_rules: dict[str, str] = {}
    tool_rules: dict[str, str] = {}
    for claude_list, action in _PI_PERMISSION_ACTIONS:
        for rule in permissions.get(claude_list, []):
            server = next(
                (s for s in pi_servers if rule.startswith(f"mcp__{s}__")), None
            )
            if server is None:
                continue
            tool = rule.removeprefix(f"mcp__{server}__")
            if tool == "*":
                server_rules[server] = action
            else:
                tool_rules[f"{server}:{tool}"] = action
    touched = {key.split(":", 1)[0] for key in tool_rules} | set(server_rules)
    defaults = {s: "ask" for s in sorted(touched) if s not in server_rules}
    return {**defaults, **server_rules, **tool_rules}


def _sync_pi_mcp_permissions(wanted: dict[str, str], previous: list[str]) -> None:
    """Make pi's ``mcp`` permission rules include exactly the managed ``wanted`` rules.

    Rules the user added themselves are left alone.

    Args:
        wanted: Rules llm-prompts now declares, in match order.
        previous: Rule keys llm-prompts managed at the last install.
    """
    config_path = (
        _pi_agent_dir() / "extensions" / "pi-permission-system" / "config.json"
    )
    config: dict[str, Any] = (
        json.loads(_read_text(config_path)) if config_path.exists() else {}
    )
    current: dict[str, str] = config.get("permission", {}).get("mcp", {})
    kept = {k: v for k, v in current.items() if k not in previous and k not in wanted}
    rules = {**kept, **wanted}
    if rules == current and list(rules) == list(current):
        return
    permission = config.setdefault("permission", {})
    if rules:
        permission["mcp"] = rules
    else:
        permission.pop("mcp", None)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _write_text(config_path, json.dumps(config, indent=2) + "\n")
    log("success", f"[pi] Updated MCP permissions in {config_path}.")


_PI_MCP_KEYS = ("type", "command", "args", "env", "cwd", "url", "headers")


def _read_mcp_servers(path: Path, label: str) -> dict[str, Any]:
    """Read the ``mcpServers`` map from a JSON file, warning on a bad file."""
    if not path.exists():
        return {}
    try:
        servers: dict[str, Any] = json.loads(_read_text(path)).get("mcpServers", {})
    except json.JSONDecodeError:
        log("warn", f"[pi] Could not parse {label}, skipping MCP servers.")
        return {}
    return servers


def _sync_pi_mcp_servers() -> None:
    """Add the MCP servers from Claude's user config and enabled plugins that pi's lacks.

    Existing pi entries are never changed, and Claude's user config wins over
    plugins. Servers pi cannot run are skipped. Only server names are logged,
    since entries may hold secrets.
    """
    candidates = _read_mcp_servers(Path.home() / ".claude.json", ".claude.json")
    plugin_paths = _enabled_claude_plugin_paths() or []
    plugin_sets = [
        _read_mcp_servers(path / ".mcp.json", f"{path.name}/.mcp.json")
        for path in plugin_paths
    ]
    mcp_path = _pi_agent_dir() / "mcp.json"
    config: dict[str, Any] = (
        json.loads(_read_text(mcp_path)) if mcp_path.exists() else {}
    )
    servers: dict[str, Any] = config.setdefault("mcpServers", {})
    added = []
    for name, entry in [
        item for source in (candidates, *plugin_sets) for item in source.items()
    ]:
        if name in servers:
            continue
        if entry.get("type") == "sse" or not (entry.get("command") or entry.get("url")):
            log("warn", f"[pi] Skipping unsupported MCP server {name}.")
            continue
        servers[name] = {k: entry[k] for k in _PI_MCP_KEYS if k in entry}
        added.append(name)
    if not added:
        return
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    _write_text(mcp_path, json.dumps(config, indent=2) + "\n")
    log("success", f"[pi] Added MCP servers {', '.join(added)} to {mcp_path}.")


def try_install_hooks_pi() -> None:
    """Write the cline-hooks bridge extension for pi if available."""
    import shutil
    import subprocess

    binary = shutil.which("cline-hook")
    if not binary:
        log("debug", "cline-hook not found on PATH, skipping Pi hook injection.")
        return
    subprocess.run([binary, "install", "pi"], check=False)


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


def try_install_memory_codex() -> None:
    """Add mcp-memory to Codex if available."""
    import shutil
    import subprocess

    binary = shutil.which("mcp-memory")
    if not binary:
        log("debug", "mcp-memory not found on PATH, skipping Codex MCP setup.")
        return
    subprocess.run([binary, "install", "codex"], check=False)
    if not _memory_service_exists():
        subprocess.run([binary, "setup-service"], check=False)


def try_install_memory_antigravity() -> None:
    """Add mcp-memory to Antigravity if available."""
    import shutil
    import subprocess

    binary = shutil.which("mcp-memory")
    if not binary:
        log(
            "debug",
            "mcp-memory not found on PATH, skipping Antigravity MCP setup.",
        )
        return
    subprocess.run([binary, "install", "antigravity"], check=False)
    if not _memory_service_exists():
        subprocess.run([binary, "setup-service"], check=False)


def try_install_memory_pi() -> None:
    """Add mcp-memory to pi's MCP config if available."""
    import shutil
    import subprocess

    binary = shutil.which("mcp-memory")
    if not binary:
        log("debug", "mcp-memory not found on PATH, skipping Pi MCP setup.")
        return
    subprocess.run([binary, "install", "pi"], check=False)
    if not _memory_service_exists():
        subprocess.run([binary, "setup-service"], check=False)


def _carry_forward(
    agent_name: str,
    dest: Path,
    label: str,
    previous_manifest: "dict[str, AgentManifest]",
    quiet: bool = False,
) -> bool:
    """Decide whether a size-guard-skipped destination stays managed.

    Args:
        agent_name: Agent the destination belongs to.
        dest: Destination path that was skipped.
        label: Human-readable label for the skipped prompt.
        previous_manifest: The manifest from the previous installation.
        quiet: Whether to omit the size guard warnings.

    Returns:
        Whether ``dest`` was installed last time and should stay managed.
    """
    previous_files = set(previous_manifest.get(agent_name, {}).get("files", []))
    if quiet:
        return str(dest) in previous_files
    if str(dest) in previous_files:
        log("warn", f"[{agent_name}] Kept previous {label}: size guard violation")
        return True
    log("warn", f"[{agent_name}] Not installed {label}: size guard violation")
    return False


def _cleanup_stale(
    agent_name: str,
    current_files: list[str],
    previous_manifest: "dict[str, AgentManifest]",
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


def _remove_empty_dir(path: Path) -> None:
    """Remove a directory when it exists and holds nothing.

    Args:
        path: Directory to remove.
    """
    if path.is_dir() and not any(path.iterdir()):
        path.rmdir()


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
    global _verbose
    _verbose = verbose
    from .manifest import delete_agent, delete_rendered_rules, read_manifest

    manifest = read_manifest()
    targets = agent_names or list(manifest)
    for name in targets:
        entry = manifest.get(name)
        if entry is None:
            log("warn", f"[{name}] not installed; nothing to remove.")
            continue
        _remove_manifest_files(name, entry.get("files", []))
        delete_rendered_rules(name)
        if name == "cline":
            _remove_cline_symlinks()
        agent_config = entry.get("agent_config")
        if agent_config:
            _unpatch_kiro_agent_config(agent_config)
        if name == "claude-code":
            _disallow_update_claude_code()
        if name == "pi":
            _remove_empty_dir(_pi_rules_dir())
            _sync_pi_packages([], entry.get("packages", []))
            _sync_pi_skills([], entry.get("skills", []))
            _sync_pi_mcp_permissions({}, entry.get("mcp_permissions", []))
        delete_agent(name)
        log("success", f"[{name}] Uninstalled.")


def main(
    agent_names: list[str] | None = None,
    *,
    verbose: bool = False,
    size_baseline: dict[Path, str] | None = None,
    only: Path | None = None,
) -> bool:
    """Run the installation workflow.

    Args:
        agent_names: Agents to install for. None means all.
        verbose: Show debug-level output.
        size_baseline: A `size_guard.snapshot_sources` taken before pulling
            sources; violations in files changed since then only warn.
        only: Source file to reinstall alone; every other prompt is left
            untouched and the manifest keeps its previous files.

    Returns:
        Whether any prompt was skipped or any agent frozen due to a size
        guard violation.
    """
    global _verbose
    _verbose = verbose
    clear_read_cache()
    root_dir = prompts_dir("llm_prompts")
    dirs = _get_dirs()

    overlay_dirs = _discover_overlay_paths()

    from .manifest import read_manifest
    from .size_guard import check as run_size_check
    from .size_guard import (
        check_source,
        format_report,
        parked_state_lines,
        resolve_skip_set,
        split_by_change,
    )

    previous_manifest = read_manifest()
    all_skipped: frozenset[Path] = frozenset()
    size_failed = False
    pi_install_failed = False
    frozen_agents: frozenset[str] = frozenset()
    skip_by_agent: dict[str, Container[Path]]
    if only is not None:
        result = check_source(only, _read_text(only))
        if not result.passed:
            for line in result.report.splitlines():
                log("error", line)
            size_failed = True
        skip = _AllExcept(frozenset() if size_failed else frozenset({only.resolve()}))
        skip_by_agent = dict.fromkeys(AGENT_CLASSES, skip)
    else:
        size_result = run_size_check([root_dir, *overlay_dirs])
        if size_result.declaration_errors:
            for line in format_report([], size_result.declaration_errors).splitlines():
                log("error", line)
            sys.exit(1)
        blocking, pulled = split_by_change(size_result.violations, size_baseline)
        skip_sets, frozen_agents = resolve_skip_set(blocking)
        skip_by_agent = dict(skip_sets)
        all_skipped = frozenset().union(*skip_sets.values())
        if blocking:
            for line in format_report(blocking).splitlines():
                log("error", line)
        for name in sorted(frozen_agents):
            log("error", f"[{name}] Frozen: collection_bytes size guard violation")
        if pulled:
            for line in format_report(pulled).splitlines():
                log("warn", line)
            log(
                "warn",
                "Installing anyway as these changed in this update; run "
                "`llm-prompts check` once they are compressed.",
            )
        for line in parked_state_lines(size_result.artifacts):
            log("info", line)
        for line in size_result.stale:
            log("warn", line)

    all_agents: dict[str, _Agent] = {
        name: agent_class(name=name, root_dir=root_dir, dirs=dirs)
        for name, agent_class in AGENT_CLASSES.items()
    }
    targets = agent_names or list(all_agents)

    installed_files: dict[str, list[str]] = {name: [] for name in targets}
    for name in frozen_agents & set(targets):
        installed_files[name] = list(previous_manifest.get(name, {}).get("files", []))
    active_targets = [name for name in targets if name not in frozen_agents]

    from .plugins import (
        _load_plugins,
        _stringify_override,
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

    plugin_skill_pairs: list[tuple[str, Path, dict[str, str]]] = []
    for plugin in plugins:
        checkout = ensure_cloned(plugin)
        if checkout is None:
            continue
        overrides_by_skill: dict[str, dict[str, Any]] = (
            plugin.get("frontmatter_overrides") or {}
        )
        for name, src in discover_skills(checkout, plugin.get("skills")):
            overrides = {
                key: _stringify_override(value)
                for key, value in overrides_by_skill.get(name, {}).items()
            }
            plugin_skill_pairs.append((name, src, overrides))

    if "cline" in active_targets:
        agents_dir, _ = _get_cline_extra_dirs()
        cline_skill_dirs = [
            *(d / "shared" / "skills" for d in overlay_dirs),
            root_dir / "shared" / "skills",
        ]
        managed_skills = _install_skills(
            cline_skill_dirs,
            agents_dir,
            "cline",
            all_agents["cline"].vars_path(),
            skip_by_agent.get("cline", frozenset()),
            previous_manifest,
        )
        plugin_managed = _install_plugin_skills(
            plugin_skill_pairs, agents_dir, "cline", managed_skills
        )
        managed_skills |= plugin_managed
        _check_unmanaged(agents_dir / "skills", managed_skills, "skills", is_dir=True)
        skills_dir = agents_dir / "skills"
        installed_files["cline"].extend(str(skills_dir / s) for s in managed_skills)

    for skill_agent in (
        "copilot",
        "kiro",
        "claude-code",
        "codex",
        "antigravity",
        "pi",
    ):
        if skill_agent not in active_targets:
            continue
        skills_parent = _skills_parent(dirs, skill_agent)
        skill_dirs = [
            *(d / "shared" / "skills" for d in overlay_dirs),
            root_dir / "shared" / "skills",
            root_dir / skill_agent / "skills",
            *(d / skill_agent / "skills" for d in overlay_dirs),
        ]
        managed = _install_skills(
            skill_dirs,
            skills_parent,
            skill_agent,
            all_agents[skill_agent].vars_path(),
            skip_by_agent.get(skill_agent, frozenset()),
            previous_manifest,
        )
        plugin_managed = _install_plugin_skills(
            plugin_skill_pairs, skills_parent, skill_agent, managed
        )
        managed |= plugin_managed
        _check_unmanaged(
            skills_parent / "skills", managed, f"{skill_agent} skills", is_dir=True
        )
        skills_dir = skills_parent / "skills"
        installed_files[skill_agent].extend(str(skills_dir / s) for s in managed)

    pi_bundle: _PiRuleBundle | None = None
    pi_bundle_held = False
    if "pi" in active_targets:
        pi_bundle = _PiRuleBundle.build(
            all_agents["pi"],
            overlay_dirs,
            skip_by_agent.get("pi", frozenset()),
            previous_manifest,
        )
        if pi_bundle.selector_errors:
            raise ValueError("; ".join(m for _, m in pi_bundle.selector_errors))
        for _, message in pi_bundle.failures:
            log("error", message)
        for name in pi_bundle.held_back:
            log(
                "warn",
                f"[pi] Kept previous rule bundle: rules/{name} skipped with no cached copy",
            )
        pi_bundle_held = bool(pi_bundle.held_back)
        if not pi_bundle_held:
            rule_files = _install_pi_rule_files(pi_bundle, _pi_rules_dir())
            pi_bundle_held = len(rule_files) != len(pi_bundle.texts)
            installed_files["pi"].extend(str(_pi_rules_dir() / f) for f in rule_files)
    pi_agents_md = dirs["pi"]["rules"] / _PiAgent.AGENTS_MD
    previous_pi_bundle = _previous_pi_bundle_files(
        previous_manifest, dirs["pi"]["agents"], pi_agents_md
    )
    if pi_bundle_held:
        installed_files["pi"].extend(
            f for f in previous_pi_bundle if Path(f).parent == _pi_rules_dir()
        )

    for agents_target in ("claude-code", "pi"):
        if agents_target not in active_targets:
            continue
        agents_dest = dirs[agents_target]["agents"]
        agent_dirs = _agent_source_dirs(root_dir, overlay_dirs, agents_target)
        target_skip_set = skip_by_agent.get(agents_target, frozenset())
        if agents_target == "pi" and pi_bundle_held:
            managed_agents = {
                Path(f).name
                for f in previous_pi_bundle
                if Path(f).parent == agents_dest
            }
        else:
            managed_agents = _install_agents(
                agent_dirs,
                agents_dest,
                target_skip_set,
                previous_manifest,
                _RuleSources.collect(
                    all_agents[agents_target],
                    overlay_dirs,
                    frozenset() if only is not None else target_skip_set,
                ),
                agents_target,
                _pi_agent_dialect(root_dir, overlay_dirs)
                if agents_target == "pi"
                else _CLAUDE_AGENT_DIALECT,
                _builtin_skill_vars(all_agents[agents_target].vars_path()),
                bundle=pi_bundle if agents_target == "pi" else None,
            )
        if agents_target == "pi":
            managed_agents |= _install_disabled_definitions(agents_dest)
            managed_agents |= _install_herdsman_overlays(
                root_dir / "pi" / "herdsman-overlays", agents_dest
            )
        _check_unmanaged(agents_dest, managed_agents, f"{agents_target} agents")
        installed_files[agents_target].extend(
            str(agents_dest / a) for a in managed_agents
        )

    for name in active_targets:
        agent = all_agents[name]
        agent_skip_set = skip_by_agent.get(name, frozenset())
        for subdir in content_subdirs(name):
            overlay_srcs = [d / "shared" / subdir for d in overlay_dirs]
            overlay_agent_srcs = [d / agent.name / subdir for d in overlay_dirs]
            shared_src = root_dir / "shared" / subdir
            if subdir == "rules" and name == "pi" and pi_bundle is not None:
                installed = (
                    {_PiAgent.AGENTS_MD} & {Path(f).name for f in previous_pi_bundle}
                    if pi_bundle_held
                    else _install_pi_lead_rules(agent, pi_bundle)
                )
            elif subdir == "rules":
                installed = agent.install_rules(
                    shared_src,
                    overlay_srcs,
                    overlay_agent_srcs,
                    agent_skip_set,
                    previous_manifest,
                )
            else:
                installed = _install_content(
                    agent=agent,
                    subdir=subdir,
                    shared_src=shared_src,
                    overlay_srcs=overlay_srcs,
                    overlay_agent_srcs=overlay_agent_srcs,
                    skip_set=agent_skip_set,
                    previous_manifest=previous_manifest,
                )
            dest_dir = agent.dest_dir(subdir)
            if not (isinstance(agent, _CodexAgent) and subdir == "rules"):
                _check_unmanaged(dest_dir, installed, f"{agent.name} {subdir}")
            installed_files[name].extend(str(dest_dir / f) for f in installed)

    if "codex" in active_targets:
        _ensure_codex_doc_limit(
            dirs["codex"]["rules"] / "config.toml",
            dirs["codex"]["rules"] / _CodexAgent.AGENTS_MD,
        )

    if "cline" in active_targets:
        log("info", "[cline] Symlinking rules and workflows...")
        _, cline_symlinks = _get_cline_extra_dirs()
        for subdir, symlink_dest in cline_symlinks.items():
            _symlink_dir(dirs["cline"][subdir], symlink_dest)

    from .manifest import write_manifest

    pi_packages: list[str] | None = None
    pi_skills: list[str] | None = None
    pi_mcp_rules: list[str] | None = None
    pi_rule_roles: dict[str, list[str]] | None = previous_manifest.get("pi", {}).get(
        "pi_rule_roles"
    )
    if "pi" in active_targets:
        pi_rule_roles = (
            None
            if pi_bundle is None
            else previous_manifest.get("pi", {}).get("pi_rule_roles", {})
            if pi_bundle_held
            else {name: sorted(r) for name, r in pi_bundle.roles.items()}
        )
        if not herdr_available():
            log("warn", "[pi] `herdr` not found on PATH. pi needs herdr to run.")
        pi_fragments = [root_dir / "pi" / "settings.json"] + [
            d / "pi" / "settings.json" for d in overlay_dirs
        ]
        pi_packages = _pi_packages(pi_fragments)
        _sync_pi_packages(
            pi_packages,
            previous_manifest.get("pi", {}).get("packages", []),
            _pi_defaults(pi_fragments),
        )
        pi_install_failed = _install_pi_packages(pi_packages)
        installed_files["pi"].extend(
            _install_pi_extensions(
                [root_dir / "pi" / "extensions"]
                + [d / "pi" / "extensions" for d in overlay_dirs],
                _pi_agent_dir() / "extensions",
                set(previous_manifest.get("pi", {}).get("files", [])),
            )
        )
        _seed_pi_files([root_dir, *overlay_dirs])
        _sync_pi_mcp_servers()
        pi_skills = _claude_plugin_skill_dirs()
        if pi_skills is None:
            pi_skills = previous_manifest.get("pi", {}).get("skills", [])
        _sync_pi_skills(pi_skills, previous_manifest.get("pi", {}).get("skills", []))
        previous_rules = previous_manifest.get("pi", {}).get("mcp_permissions", [])
        claude_rules = _claude_mcp_permissions()
        if claude_rules is None:
            pi_mcp_rules = previous_rules
        else:
            pi_mcp_rules = list(claude_rules)
            _sync_pi_mcp_permissions(claude_rules, previous_rules)
    for name in targets:
        manifest_files = list(dict.fromkeys(installed_files[name]))
        if only is None:
            _cleanup_stale(name, manifest_files, previous_manifest)
            if name == "pi" and pi_bundle is None:
                _remove_empty_dir(_pi_rules_dir())
        else:
            manifest_files = sorted(
                set(manifest_files)
                | set(previous_manifest.get(name, {}).get("files", []))
            )
        write_manifest(
            name,
            manifest_files,
            packages=pi_packages if name == "pi" else None,
            skills=pi_skills if name == "pi" else None,
            mcp_permissions=pi_mcp_rules if name == "pi" else None,
            pi_rule_roles=pi_rule_roles if name == "pi" else None,
        )

    for source in sorted(all_skipped):
        display = source.parent.name if source.name == "SKILL.md" else source.name
        log("error", f"Skipped installing {display}: size guard violation")

    return size_failed or bool(all_skipped) or bool(frozen_agents) or pi_install_failed


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
    managed.add(_pi_rules_dir())
    for key, value in dirs.items():
        for subdir, subdir_path in value.items():
            if key in ("codex", "antigravity", "pi") and subdir == "rules":
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


def get_source_for_managed_file(path: str) -> str | None:
    """Return the source file an installed managed file was generated from.

    Args:
        path: Absolute path of an installed file.

    Returns:
        Source file path, or None where no unambiguous source resolves
        (variant-generated agents, plugin skills, concatenated targets).
    """
    from .cli import _collect_sources

    dest = Path(path)
    if dest.parent == _pi_rules_dir():
        source = _collect_sources("pi").get(f"rules/{dest.name}")
        return str(source) if source is not None else None
    dirs = _get_dirs()
    for agent, subdirs in dirs.items():
        for subdir, dest_dir in subdirs.items():
            if dest.parent == dest_dir:
                source = _collect_sources(agent).get(f"{subdir}/{dest.name}")
                if source is not None:
                    return str(source)
        skills_dir = _skills_parent(dirs, agent) / "skills"
        if skills_dir in dest.parents:
            relative = dest.relative_to(skills_dir)
            source = _collect_sources(agent).get(f"skills/{relative.parts[0]}")
            if source is not None:
                return str(source.parent.joinpath(*relative.parts[1:]))
    return None


def partial_source(path: Path) -> Path | None:
    """Return the source file whose installed prompt an edit of ``path`` rebuilds.

    Args:
        path: An edited source file, or an installed managed file.

    Returns:
        The source file to reinstall alone, or None where the edit cannot be
        reinstalled on its own (variables, settings, allowances, concatenated
        or plugin-sourced files, files outside every prompts root).
    """
    from .size_guard import _owning_root

    source = path.resolve()
    managed = get_managed_files()
    dest = next((d for d in (str(path), str(source)) if d in managed), None)
    if dest is not None:
        mapped = get_source_for_managed_file(dest)
        if mapped is None:
            return None
        source = Path(mapped).resolve()
    root = _owning_root(source)
    if root is None or not source.is_file():
        return None
    match source.relative_to(root).parts:
        case (_, "rules" | "workflows" | "agents", name) if name.endswith(".md"):
            return source
        case (group, "skills", skill, _, *_):
            skill_md = root / group / "skills" / skill / "SKILL.md"
            return skill_md if skill_md.is_file() else None
    return None


if __name__ == "__main__":
    main()
