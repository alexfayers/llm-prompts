import re
import threading
from io import StringIO

import pytest
from rich.console import Console

from llm_prompts.benchmark.live_view import LiveView
from llm_prompts.benchmark.types import ResultRow


def terminal(height: int = 25) -> tuple[Console, StringIO]:
    out = StringIO()
    return Console(file=out, force_terminal=True, width=100, height=height), out


def frame(view: LiveView) -> list[str]:
    """Return the lines of the live display as the terminal shows them."""
    console, out = terminal()
    console.print(view.display)
    return [
        line.rstrip()
        for line in re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out.getvalue()).splitlines()
    ]


def finished(passed: bool = True) -> ResultRow:
    return ResultRow(variant="a", scenario="one", agent="claude", passed=passed, wall_s=42.0, turns=6, cost_usd=0.18, start_context=1000, context=2000)  # fmt: skip


def test_a_cell_keeps_its_row_from_start_to_result_and_new_cells_append_below() -> None:
    console, _ = terminal()
    with LiveView(["one", "two", "three"], console) as view:
        view.start("a", "one")
        view.start("b", "two")
        view.tool("a", "Bash")
        before = frame(view)
        view.finish("a", "one", finished())
        view.start("c", "three")
        after = frame(view)

    assert re.search(r"one\s+\d+s\s+Bash \(1\)", before[0])
    assert re.search(r"two\s+\d+s$", before[1])
    assert re.search(
        r"one\s+pass\s+42s\s+1,000->2,000 ctx\s+\$0.18\s+6 turns", after[0]
    )
    assert re.search(r"two\s+\d+s$", after[1])
    assert re.search(r"three\s+\d+s$", after[2])
    assert "1/3 done, 0 fail, 0 skipped, ETA" in after[3]


def test_a_failed_cell_is_counted_and_a_skipped_cell_shows_its_reason_in_its_own_row() -> (
    None
):
    console, _ = terminal()
    with LiveView(["one", "two"], console) as view:
        view.start("a", "one")
        view.start("b", "two")
        view.finish("a", "one", finished(passed=False))
        view.skip("b", "two", "setup error: boom")
        rows = frame(view)

    assert "fail" in rows[0]
    assert re.search(r"two\s+skipped\s+setup error: boom", rows[1])
    assert "1 fail, 1 skipped, ETA" in rows[2]


def test_a_startup_error_is_shown_as_an_error_and_not_counted_as_a_fail() -> None:
    console, _ = terminal()
    row = ResultRow(variant="a", scenario="one", agent="claude", error="startup error: agent exit 1: throttled", startup_error=True)  # fmt: skip
    with LiveView(["one"], console) as view:
        view.start("a", "one")
        view.finish("a", "one", row)
        rows = frame(view)

    assert re.search(r"one\s+error\s+startup error: agent exit 1: throttled", rows[0])
    assert "0 fail" in rows[1]


def test_finished_rows_scroll_off_the_top_only_when_the_display_is_taller_than_the_terminal() -> (
    None
):
    console, out = terminal(height=6)
    labels = [f"cell-{n}" for n in range(6)]
    with LiveView(labels, console) as view:
        for n, label in enumerate(labels):
            view.start(str(n), label)
            view.finish(str(n), label, finished())
        rows = frame(view)

    scrolled = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out.getvalue())
    assert "cell-0" in scrolled
    assert not any("cell-0" in row for row in rows)
    assert any("cell-5" in row for row in rows)
    assert "6/6 done" in rows[-1]


def test_without_a_terminal_nothing_is_printed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = StringIO()
    with LiveView(["one", "two"], Console(file=out, force_terminal=False)) as view:
        view.start("a", "one")
        view.start("b", "two")
        view.tool("a", "Bash")
        view.finish("b", "two", finished())
        view.skip("a", "one", "why")

    assert (out.getvalue(), capsys.readouterr()) == ("", ("", ""))


def test_rendering_waits_for_the_lock_that_guards_the_rows() -> None:
    view = LiveView(["a one"], console=terminal()[0])
    rendered = threading.Thread(target=frame, args=(view,))

    with view._lock:
        rendered.start()
        rendered.join(timeout=0.3)
        assert rendered.is_alive()

    rendered.join(timeout=5)
    assert not rendered.is_alive()
