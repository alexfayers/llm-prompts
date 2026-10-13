"""Cline-hooks plugin that reports the workspace HANDOFF.md as a startup block."""

from __future__ import annotations

from pathlib import Path

from cline_hooks.core.plugin import HooksPlugin, hookimpl
from cline_hooks.plugins.startup_blocks import StartupBlock

_HANDOFF_FILE = "HANDOFF.md"


class HandoffBlock(HooksPlugin):
    """Injects whether the workspace root holds a HANDOFF.md."""

    @hookimpl
    def startup_blocks(self, workspace_roots: list[str]) -> list[StartupBlock]:
        """Return the HANDOFF.md block, or none without a workspace root."""
        if not workspace_roots:
            return []
        handoff = next(
            (
                path
                for root in workspace_roots
                if (path := Path(root) / _HANDOFF_FILE).is_file()
            ),
            None,
        )
        text = (
            f"{handoff} exists - run the pickup skill."
            if handoff
            else f"No {_HANDOFF_FILE}."
        )
        return [
            StartupBlock(
                title=_HANDOFF_FILE,
                replaces="check for HANDOFF.md in the workspace root",
                body=lambda _: text,
                order=5,
            )
        ]
