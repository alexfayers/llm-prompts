"""Find the watch sources: built-in ones and those installed packages provide."""

from __future__ import annotations

from importlib.metadata import entry_points

from ..sources.command import CommandSource
from ..sources.github_pr import GithubPrSource
from .source import SourceType

ENTRY_POINT_GROUP = "llm_prompts.watch_sources"


def sources() -> dict[str, SourceType]:
    """Return every watch source class by name."""
    found: dict[str, SourceType] = {
        source.name: source for source in (CommandSource, GithubPrSource)
    }
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        source = entry_point.load()
        found[source.name] = source
    return found
