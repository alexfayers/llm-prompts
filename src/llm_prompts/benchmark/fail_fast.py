"""Decide which benchmark cells to skip once a run has shown it cannot succeed."""

from __future__ import annotations

import threading

from llm_prompts.benchmark.transient import STARTUP_ERROR
from llm_prompts.benchmark.types import Cell, CheckSpec, ResultRow

TIMEOUT = "timeout"
ISOLATION_BREACH = "isolation breach: "
BASE_FAILED = "base failed: "
SETUP_ERROR = "setup error: "
BASE_SKIPPED = "base skipped: "
MAX_CHECK_CHARS = 80

Key = tuple[str, str, str]


def check_label(spec: CheckSpec) -> str:
    """Return a short one-line name for a check: its kind and arguments."""
    args = ", ".join(f"{name}={value}" for name, value in spec.args.items())
    text = " ".join((f"{spec.kind}({args})" if args else spec.kind).split())
    return text if len(text) <= MAX_CHECK_CHARS else text[: MAX_CHECK_CHARS - 3] + "..."


def is_setup_error(error: str) -> bool:
    """Return whether a row error comes from the setup or harness, not from the cell's own outcome."""
    return not (
        error == TIMEOUT
        or error.startswith((ISOLATION_BREACH, BASE_FAILED, STARTUP_ERROR))
    )


def _failed_checks(row: ResultRow) -> frozenset[int]:
    return frozenset(i for i, check in enumerate(row.checks) if not check.passed)


class FailFast:
    """Tracks results to find a setup error or a check that keeps failing.

    ``after`` is how many completed repeats of a side's scenario must fail the same check before
    its remaining repeats are skipped. None turns everything off.
    """

    def __init__(self, after: int | None) -> None:
        self._after = after
        self._lock = threading.Lock()
        self._failed: dict[Key, list[frozenset[int]]] = {}
        self._skipped: dict[Key, str] = {}
        self._aborted: str | None = None

    @property
    def enabled(self) -> bool:
        """Return whether fail-fast checks are on."""
        return self._after is not None

    @property
    def aborted(self) -> str | None:
        """Return the reason the whole run was aborted, if it was."""
        return self._aborted

    @staticmethod
    def _key(cell: Cell) -> Key:
        return cell.variant.label, cell.agent, cell.scenario.id

    def skip_reason(self, cell: Cell) -> str | None:
        """Return why the cell must not run, or None."""
        with self._lock:
            return self._aborted or self._skipped.get(self._key(cell))

    def observe(self, cell: Cell, row: ResultRow) -> bool:
        """Take in a recorded row and return whether it aborts the run."""
        if self._after is None or row.skipped:
            return False
        with self._lock:
            if error := row.error:
                if self._aborted is None and is_setup_error(error):
                    self._aborted = SETUP_ERROR + error
                    return True
                return False
            key = self._key(cell)
            runs = self._failed.setdefault(key, [])
            if len(runs) < self._after:
                runs.append(_failed_checks(row))
                if len(runs) == self._after and (
                    common := frozenset.intersection(*runs)
                ):
                    check = check_label(cell.scenario.checks[min(common)])
                    self._skipped[key] = (
                        f"first {self._after} repeats all failed {check}"
                    )
        return False
