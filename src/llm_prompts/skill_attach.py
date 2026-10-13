"""Cline-hooks plugin that suggests installed skills in a spawned subagent's task."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from cline_hooks.core.hook_kwargs import PreToolUseKwargs
from cline_hooks.core.plugin import HookResult, HooksPlugin
from cline_hooks.core.protocol import get_protocol
from cline_hooks.core.vocabulary import AGENT_SPAWN_TOOLS, CanonicalHook

from .manifest import read_manifest
from .render_template import split_frontmatter

_ATTACH_FLAG = re.compile(r"\s+attach_(triggers|roles):\s*(\S.*)")
_MAX_SKILLS = 3


def _mentions(text: str, phrase: str) -> bool:
    """Return True where text holds the phrase as whole words, ignoring case."""
    return re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE) is not None


def _attach_flags(skill_dir: Path) -> dict[str, list[str]]:
    """Return a skill's ``attach_triggers`` and ``attach_roles`` metadata as lists."""
    skill_file = skill_dir / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8") if skill_file.is_file() else ""
    matches = map(_ATTACH_FLAG.fullmatch, (split_frontmatter(text) or ([], ""))[0])
    return {m[1]: re.split(r"\s*,\s*", m[2].strip()) for m in matches if m}


class SkillAttach(HooksPlugin):
    """Appends a hint naming the installed skills that fit a subagent's task."""

    def on_hook(
        self, hook_name: str, *, logger: logging.Logger, **kwargs: object
    ) -> HookResult | None:
        """Suggest skills on a subagent spawn by appending a hint to its task."""
        if hook_name != CanonicalHook.PRE_TOOL_USE:
            return None
        kw = PreToolUseKwargs.build(kwargs)
        spec = get_protocol().frontend_spec
        key = next((k for k in ("task", "prompt") if k in kw.parameters), None)
        if kw.tool_name not in AGENT_SPAWN_TOOLS or not (spec and key):
            return None
        task = str(kw.parameters[key])
        roles = {str(kw.parameters.get(k)) for k in ("definition", "subagent_type")}
        names = []
        for skill in map(Path, read_manifest().get(spec.name, {}).get("files", [])):
            flags = _attach_flags(skill)
            fits = bool(roles & set(flags.get("roles", [])))
            fits = fits or any(_mentions(task, t) for t in flags.get("triggers", []))
            if fits and not _mentions(task, skill.name):
                names.append(skill.name)
        if not names:
            return None
        hint = spec.skill_hint(names[:_MAX_SKILLS])
        return HookResult(
            updated_input={**kw.parameters, key: f"{task}\n\n{hint}"},
            fallback_notes=[hint],
        )
