from llm_prompts.benchmark.types import ResultRow, Tokens


def test_result_row_round_trips_and_defaults_what_an_older_row_lacks() -> None:
    row = ResultRow(variant="a", agent="pi", scenario="s", tokens=Tokens(input=3))

    assert ResultRow.from_json(row.to_json()) == row
    assert ResultRow.from_json({"variant": "a", "agent": "pi", "scenario": "s"}) == (
        ResultRow(variant="a", agent="pi", scenario="s")
    )
