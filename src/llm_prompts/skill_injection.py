"""Cline-hooks plugin that injects flagged skills as startup blocks."""

from __future__ import annotations

from pathlib import Path

from cline_hooks.core.plugin import HooksPlugin, hookimpl
from cline_hooks.core.protocol import get_protocol
from cline_hooks.plugins.startup_blocks import StartupBlock, split_skill

from .manifest import read_manifest
from .render_template import nested_frontmatter

_FLAG = "true"


def _skill_block(skill_dir: Path) -> StartupBlock | None:
    """Build the startup block for an installed skill, or None where it is not flagged.

    Args:
        skill_dir: Installed skill directory.

    Returns:
        The block holding the skill's installed body, or None.
    """
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return None
    frontmatter, body = split_skill(skill_file)
    flags = nested_frontmatter(frontmatter, "metadata")
    if flags.get("inject_at_start") != _FLAG:
        return None
    name = skill_dir.name
    return StartupBlock(
        title=f"skill `{name}`",
        replaces=f"load the `{name}` skill",
        body=lambda _: body,
        skill=name,
        subagents=flags.get("inject_subagents") == _FLAG,
        on_resume=flags.get("inject_resume") == _FLAG,
        order=10,
    )


class SkillStartupBlocks(HooksPlugin):
    """Injects each installed skill flagged ``metadata.inject_at_start`` as a startup block."""

    @hookimpl
    def startup_blocks(self, workspace_roots: list[str]) -> list[StartupBlock]:
        """Return a block for each flagged skill installed for the active frontend.

        Args:
            workspace_roots: Workspace root paths.

        Returns:
            The flagged skills' blocks; empty without an active frontend or manifest entry.
        """
        spec = get_protocol().frontend_spec
        if spec is None:
            return []
        files = read_manifest().get(spec.name, {}).get("files", [])
        blocks = (_skill_block(Path(file)) for file in files)
        return [block for block in blocks if block is not None]
