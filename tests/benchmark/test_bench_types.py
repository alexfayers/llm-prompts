import json
from pathlib import Path

from benchmark.traces import make_trace
from llm_prompts.benchmark import saved
from llm_prompts.benchmark.types import MemoryEntity, ResultRow, Tokens


def test_result_row_round_trips_and_defaults_what_an_older_row_lacks() -> None:
    row = ResultRow(
        variant="a",
        agent="pi",
        scenario="s",
        tokens=Tokens(input=3),
        fork_start_contexts=(5, 6),
        fork_start_s=(1.5,),
        peak_rss_kb=2048,
    )

    assert ResultRow.from_json(json.loads(json.dumps(row.to_json()))) == row
    assert ResultRow.from_json({"variant": "a", "agent": "pi", "scenario": "s"}) == (
        ResultRow(variant="a", agent="pi", scenario="s")
    )


def test_a_saved_trace_loads_back_equal(tmp_path: Path) -> None:
    trace = make_trace(
        fork_start_contexts=(5, 6), fork_start_s=(1.5,), peak_rss_kb=2048
    )
    (tmp_path / "ws").mkdir()
    (tmp_path / "cell").mkdir()

    saved.write(tmp_path / "cell", tmp_path / "ws", trace, (), ())

    assert saved.load(tmp_path / "cell").trace == trace


def test_saved_memory_loads_back_with_its_location(tmp_path: Path) -> None:
    entity = MemoryEntity("knowledge/a", "knowledge", ("x",), location="/ws/fetch.py")
    (tmp_path / "ws").mkdir()
    (tmp_path / "cell").mkdir()

    saved.write(tmp_path / "cell", tmp_path / "ws", make_trace(), (), (entity,))

    assert saved.load(tmp_path / "cell").memory_after == (entity,)
