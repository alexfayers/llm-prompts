"""Cline-hooks plugin that injects flagged skills as startup blocks."""

from __future__ import annotations

from pathlib import Path

from cline_hooks.core.plugin import HooksPlugin, hookimpl
from cline_hooks.core.protocol import get_protocol
from cline_hooks.plugins.startup_blocks import StartupBlock

from .manifest import read_manifest
from .render_template import split_frontmatter

_FLAG = "inject_at_start: true"


def _flagged(frontmatter: list[str]) -> bool:
    """Return whether the frontmatter sets the start-up flag under ``metadata``."""
    in_metadata = False
    for line in frontmatter:
        if line.startswith((" ", "\t")):
            if in_metadata and line.strip() == _FLAG:
                return True
        else:
            in_metadata = line.rstrip() == "metadata:"
    return False


def _skill_block(skill_dir: Path) -> StartupBlock | None:
    """Build the startup block for an installed skill, or None where it is not flagged."""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return None
    split = split_frontmatter(skill_file.read_text(encoding="utf-8"))
    if split is None:
        return None
    frontmatter, body = split
    if not _flagged(frontmatter):
        return None
    name = skill_dir.name
    return StartupBlock(
        title=f"skill `{name}`",
        replaces=f"load the `{name}` skill",
        body=lambda _: body.strip("\n"),
        skill=name,
        order=10,
    )


class SkillStartupBlocks(HooksPlugin):
    """Injects each installed skill flagged ``metadata.inject_at_start`` as a startup block."""

    @hookimpl
    def startup_blocks(self, workspace_roots: list[str]) -> list[StartupBlock]:
        """Return a block for each flagged skill installed for the active frontend."""
        spec = get_protocol().frontend_spec
        if spec is None:
            return []
        files = read_manifest().get(spec.name, {}).get("files", [])
        blocks = (_skill_block(Path(file)) for file in files)
        return [block for block in blocks if block is not None]
