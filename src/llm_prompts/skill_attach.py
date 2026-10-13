"""Cline-hooks plugin that suggests installed skills in a spawned subagent's task."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from cline_hooks.core.hook_kwargs import PreToolUseKwargs
from cline_hooks.core.plugin import HookResult, HooksPlugin
from cline_hooks.core.protocol import get_protocol
from cline_hooks.core.vocabulary import AGENT_SPAWN_TOOLS, CanonicalHook
from cline_hooks.plugins.startup_blocks import split_skill

from .manifest import read_manifest
from .render_template import nested_frontmatter

_TASK_KEYS = ("task", "prompt")
_ROLE_KEYS = ("definition", "subagent_type")
_MAX_SKILLS = 3


def _mentions(text: str, phrase: str) -> bool:
    """Return True where text holds the phrase as whole words, ignoring case."""
    return re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE) is not None


def _listed(flags: dict[str, str], key: str) -> list[str]:
    """Return the comma-separated values of a skill metadata key."""
    return [value.strip() for value in flags.get(key, "").split(",") if value.strip()]


class SkillAttach(HooksPlugin):
    """Appends a hint naming the installed skills that fit a subagent's task."""

    def on_hook(
        self, hook_name: str, *, logger: logging.Logger, **kwargs: object
    ) -> HookResult | None:
        """Suggest skills on a subagent spawn.

        Args:
            hook_name: The hook event name.
            logger: This plugin's hook-scoped child logger.
            **kwargs: Hook-specific keyword arguments.

        Returns:
            The spawn input with the hint appended to its task, or None where no skill fits.
        """
        if hook_name != CanonicalHook.PRE_TOOL_USE:
            return None
        kw = PreToolUseKwargs.build(kwargs)
        spec = get_protocol().frontend_spec
        key = next(
            (key for key in _TASK_KEYS if isinstance(kw.parameters.get(key), str)), None
        )
        if kw.tool_name not in AGENT_SPAWN_TOOLS or spec is None or key is None:
            return None
        task = str(kw.parameters[key])
        roles = [
            str(kw.parameters[role_key])
            for role_key in _ROLE_KEYS
            if role_key in kw.parameters
        ]
        names = []
        for file in read_manifest().get(spec.name, {}).get("files", []):
            frontmatter, _ = split_skill(Path(file) / "SKILL.md")
            flags = nested_frontmatter(frontmatter, "metadata")
            fits = any(
                _mentions(task, trigger)
                for trigger in _listed(flags, "attach_triggers")
            )
            fits = fits or any(role in _listed(flags, "attach_roles") for role in roles)
            name = Path(file).name
            if fits and not _mentions(task, name):
                names.append(name)
        if not names:
            return None
        hint = spec.skill_hint(names[:_MAX_SKILLS])
        return HookResult(
            updated_input={**kw.parameters, key: f"{task}\n\n{hint}"},
            fallback_notes=[hint],
        )
