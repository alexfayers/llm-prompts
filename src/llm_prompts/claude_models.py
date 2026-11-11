"""Resolve Claude model names to the values this Claude Code install requests."""

from __future__ import annotations

import json
import os

from llm_prompts.home import user_home


def catalogue() -> dict[str, str]:
    """Map every model name this Claude Code install can select to its request value.

    Bedrock installs use ``modelOverrides``, since tier aliases may resolve to ids
    the account cannot serve. Bedrock is recognised from ``CLAUDE_CODE_USE_BEDROCK``
    or from settings keys only a Bedrock install has. Other installs use
    ``availableModels``.

    Returns:
        Mapping of model name to the value to request, empty when unavailable.
    """
    try:
        settings = json.loads(
            (user_home() / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(settings, dict):
        return {}
    is_bedrock = (
        bool(settings.get("awsCredentialExport"))
        or bool(settings.get("modelOverrides"))
        or os.environ.get("CLAUDE_CODE_USE_BEDROCK") == "1"
    )
    if is_bedrock:
        overrides = settings.get("modelOverrides")
        if not isinstance(overrides, dict):
            return {}
        return {k: v for k, v in overrides.items() if isinstance(v, str)}
    available = settings.get("availableModels")
    if not isinstance(available, list):
        return {}
    return {name: name for name in available if isinstance(name, str)}


def resolve_model(name: str) -> str:
    """Return the value to request for a model name, or the name when unmapped.

    Args:
        name: Model name as Claude Code lists it.

    Returns:
        The install's mapped model id, else ``name`` unchanged.
    """
    return catalogue().get(name, name)
