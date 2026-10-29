"""Cline-hooks plugin that tells the user to uninstall agents llm-prompts no longer supports."""

from __future__ import annotations

from cline_hooks.core.plugin import HookResult, HooksPlugin, UserFacingNote

from .install import REMOVED_AGENTS
from .manifest import read_manifest


class RemovedAgentsNotice(HooksPlugin):
    """Reports removed agents that llm-prompts still manages."""

    def on_hook(self, hook_name: str, **kwargs: object) -> HookResult | None:
        """Return a session note naming the uninstall commands, or None.

        Args:
            hook_name: The hook event name.
            **kwargs: Hook-specific keyword arguments.

        Returns:
            A HookResult for a main-session TaskStart with removed agents
            still in the manifest, otherwise None.
        """
        if hook_name != "TaskStart" or kwargs.get("agent_type"):
            return None
        manifest = read_manifest()
        commands = [
            f"llm-prompts uninstall {n}" for n in REMOVED_AGENTS if n in manifest
        ]
        if not commands:
            return None
        text = "These agents are no longer supported. Remove with:\n" + "\n".join(
            commands
        )
        return HookResult(notes=[text], user_notes=[UserFacingNote(user_text=text)])
