"""Watch the output of a command."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from typing import ClassVar, Self

from ..core.source import Fields, WatchError


class CommandSource:
    """Reports a command's exit status, a hash of its output and any JSON scalars it prints."""

    name: ClassVar[str] = "cmd"
    default_interval: ClassVar[float] = 30.0
    aliases: ClassVar[Mapping[str, Sequence[str]]] = {
        "ok": ["exit=0"],
        "update": ["changed:sha"],
    }

    def __init__(self, argv: list[str], timeout: float | None = None) -> None:
        """Watch the output of argv, abandoning a run after timeout seconds if set."""
        self._argv = argv
        self._timeout = timeout

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Add the command arguments."""
        parser.add_argument("argv", nargs="+", help="Command to run, after --.")

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Self:
        """Build the source from parsed arguments."""
        return cls(args.argv, args.timeout)

    def describe(self) -> str:
        """Return the short label printed with the result."""
        return f"cmd {self._argv[0]}"

    def poll(self) -> Fields:
        """Run the command and return its fields."""
        try:
            result = subprocess.run(
                self._argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            raise WatchError(f"Command timed out: {self._argv[0]}") from None
        except OSError:
            raise WatchError(f"Command not found: {self._argv[0]}") from None
        try:
            printed = json.loads(result.stdout)
        except ValueError:
            printed = None
        scalars = {
            key: json.dumps(value) if isinstance(value, bool) else str(value)
            for key, value in (printed.items() if isinstance(printed, dict) else [])
            if isinstance(value, str | int | float | bool)
        }
        return {
            **scalars,
            "exit": str(result.returncode),
            "sha": hashlib.sha256(result.stdout.encode()).hexdigest(),
        }
