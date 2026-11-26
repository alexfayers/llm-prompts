import json
from pathlib import Path

from benchmark.traces import make_trace
from llm_prompts.benchmark import saved
from llm_prompts.benchmark.types import ResultRow, Tokens


def test_result_row_round_trips_and_defaults_what_an_older_row_lacks() -> None:
    row = ResultRow(
        variant="a",
        agent="pi",
        scenario="s",
        tokens=Tokens(input=3),
        fork_start_contexts=(5, 6),
    )

    assert ResultRow.from_json(json.loads(json.dumps(row.to_json()))) == row
    assert ResultRow.from_json({"variant": "a", "agent": "pi", "scenario": "s"}) == (
        ResultRow(variant="a", agent="pi", scenario="s")
    )


def test_a_saved_trace_loads_back_equal(tmp_path: Path) -> None:
    trace = make_trace(fork_start_contexts=(5, 6))
    (tmp_path / "ws").mkdir()
    (tmp_path / "cell").mkdir()

    saved.write(tmp_path / "cell", tmp_path / "ws", trace, (), ())

    assert saved.load(tmp_path / "cell").trace == trace
