"""Keep a stateful source's state on disk between runs."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from .source import Fields, Stateful


class Persisted:
    """Wraps a stateful source, loading its state from disk and saving it after each poll."""

    def __init__(self, source: Stateful) -> None:
        """Load the state stored for the source's name and target."""
        self._source = source
        label = re.sub(r"[^\w.-]", "_", source.state_key)
        digest = hashlib.sha256(source.state_key.encode()).hexdigest()[:16]
        self._file = (
            Path.home()
            / ".cache"
            / "llm-prompts"
            / "watch"
            / f"{source.name}-{label}-{digest}.json"
        )
        self._saved = ""
        try:
            saved = self._file.read_text(encoding="utf-8")
            state = json.loads(saved)
            if not isinstance(state, dict):
                raise TypeError("stored state is not an object")
            source.load_state(state)
            self._file.chmod(0o600)
            self._saved = saved
        except (OSError, ValueError, TypeError):
            self._saved = ""

    @property
    def default_interval(self) -> float:
        """Seconds between polls unless the user sets one."""
        return self._source.default_interval

    @property
    def aliases(self) -> Mapping[str, Sequence[str]]:
        """Named conditions the source offers."""
        return self._source.aliases

    def describe(self) -> str:
        """Return the short label printed with the result."""
        return self._source.describe()

    def poll(self) -> Fields:
        """Poll the source, then save its state if it changed."""
        fields: Fields = self._source.poll()
        state = json.dumps(self._source.dump_state(), sort_keys=True)
        if state != self._saved:
            self._save(state)
        return fields

    def _save(self, state: str) -> None:
        temporary: Path | None = None
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(
                dir=self._file.parent, prefix=f"{self._file.stem}.", suffix=".tmp"
            )
            os.close(descriptor)
            temporary = Path(name)
            temporary.write_text(state, encoding="utf-8")
            temporary.replace(self._file)
        except OSError as error:
            print(f"watch: cannot write the cache: {error}", file=sys.stderr)
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink(missing_ok=True)
        else:
            self._saved = state
