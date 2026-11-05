"""The interface every watch source implements."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from typing import Protocol

Fields = Mapping[str, str]


class WatchError(Exception):
    """A watch failed in a way the user can act on."""


class Source(Protocol):
    """Something that reports named fields about a target."""

    @property
    def default_interval(self) -> float:
        """Seconds between polls unless the user sets one."""

    @property
    def aliases(self) -> Mapping[str, Sequence[str]]:
        """Named conditions this source offers, each expanding to OR'd conditions."""

    def describe(self) -> str:
        """Return the short label printed with the result."""

    def poll(self) -> Fields:
        """Return the target's current fields."""


class SourceType(Protocol):
    """A source class: how the command line names it and builds it."""

    name: str
    default_interval: float
    aliases: Mapping[str, Sequence[str]]

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add this source's target arguments to its subcommand parser."""

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Source:
        """Build the source from parsed arguments."""
