from dataclasses import replace
from pathlib import Path

import pytest

from benchmark.conftest import SCENARIO
from llm_prompts.benchmark.fail_fast import FailFast
from llm_prompts.benchmark.types import (
    Cell,
    CheckOutcome,
    CheckSpec,
    ResultRow,
    Variant,
)

FIRST = CheckSpec("tool_called", {"name": "first"})
SECOND = CheckSpec("tool_called", {"name": "second"})


def cell(fake_variant: Variant, repeat: int = 0) -> Cell:
    scenario = replace(SCENARIO, workspace=Path("ws"), checks=(FIRST, SECOND))
    return Cell(fake_variant, "claude", scenario, repeat)


def row(*passed: bool, error: str | None = None) -> ResultRow:
    return ResultRow(
        variant="a",
        scenario="s",
        agent="claude",
        error=error,
        checks=tuple(CheckOutcome("k", p, "") for p in passed),
    )


def test_repeats_failing_different_checks_are_not_skipped(
    fake_variant: Variant,
) -> None:
    fail_fast = FailFast(2)

    fail_fast.observe(cell(fake_variant, 0), row(False, True))
    fail_fast.observe(cell(fake_variant, 1), row(True, False))

    assert fail_fast.skip_reason(cell(fake_variant, 2)) is None


def test_a_repeat_that_passes_among_the_first_n_prevents_a_skip(
    fake_variant: Variant,
) -> None:
    fail_fast = FailFast(2)

    fail_fast.observe(cell(fake_variant, 0), row(True, True))
    fail_fast.observe(cell(fake_variant, 1), row(False, True))
    fail_fast.observe(cell(fake_variant, 2), row(False, True))

    assert fail_fast.skip_reason(cell(fake_variant, 3)) is None


def test_the_same_failed_check_in_the_first_n_repeats_names_it_in_the_skip_reason(
    fake_variant: Variant,
) -> None:
    fail_fast = FailFast(2)

    fail_fast.observe(cell(fake_variant, 0), row(False, False))
    fail_fast.observe(cell(fake_variant, 1), row(True, False))

    assert (
        fail_fast.skip_reason(cell(fake_variant, 2))
        == "first 2 repeats all failed tool_called(name=second)"
    )


@pytest.mark.parametrize(
    "error",
    [
        "timeout",
        "isolation breach: x",
        "base failed: y",
        "startup error: agent exit 1: z",
    ],
)
def test_errors_that_are_the_cells_own_outcome_do_not_abort(
    fake_variant: Variant, error: str
) -> None:
    fail_fast = FailFast(2)

    assert not fail_fast.observe(cell(fake_variant), row(error=error))
    assert fail_fast.aborted is None


def test_setup_errors_abort_the_run(fake_variant: Variant) -> None:
    fail_fast = FailFast(2)

    assert fail_fast.observe(cell(fake_variant), row(error="agent exit 1: auth failed"))
    assert fail_fast.aborted == "setup error: agent exit 1: auth failed"


def test_nothing_is_skipped_when_off(fake_variant: Variant) -> None:
    fail_fast = FailFast(None)

    assert not fail_fast.observe(cell(fake_variant), row(error="agent exit 1"))
    assert fail_fast.skip_reason(cell(fake_variant)) is None
