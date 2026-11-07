import json
from dataclasses import replace
from io import StringIO

import pytest
from rich.console import Console

from llm_prompts.benchmark.report.compare import (
    Report,
    ScenarioDelta,
    SizeChange,
    Summary,
    Usage,
    Verdict,
    gate_breaches,
    gate_notes,
    outcome_summary,
    size_summary,
)
from llm_prompts.benchmark.report.compare import compare as compare_rows
from llm_prompts.benchmark.report.compare import usage as usage_of
from llm_prompts.benchmark.report.compare import verdict as verdict_of
from llm_prompts.benchmark.report.render import render, to_json
from llm_prompts.benchmark.report.terminal import summary, summary_table
from llm_prompts.benchmark.types import DEFAULT_GATE, JsonValue, ResultRow

Rows = list[dict[str, JsonValue]]


def parsed(rows: Rows) -> list[ResultRow]:
    return [ResultRow.from_json(r) for r in rows]


def compare(rows: Rows) -> list[ScenarioDelta]:
    return compare_rows(parsed(rows))


def usage(rows: Rows) -> Usage:
    return usage_of(parsed(rows))


def verdict(rows: Rows, deltas: list[ScenarioDelta]) -> Verdict:
    return verdict_of(parsed(rows), deltas)


def row(
    variant: str = "a",
    passed: bool = True,
    tokens: int = 100,
    context: int = 10,
    cost: float | None = 0.5,
    wall_s: float = 10.0,
    error: str | None = None,
) -> dict[str, JsonValue]:
    return {
        "variant": variant, "scenario": "s1", "agent": "claude", "passed": passed, "gate": {"max_pass_drop": 0.34, "max_context_rise": 0.25, "max_cost_rise": 0.5, "max_time_rise": 0.5},
        "tokens": {"input": tokens}, "judge_tokens": 7, "start_context": context // 2, "context": context, "cost_usd": cost, "wall_s": wall_s,
        "tool_calls": 1, "turns": 4, "error": error, "memory": {"memory_calls": 2},
    }  # fmt: skip


def full_report(
    rows: list[dict[str, JsonValue]], sizes: tuple[SizeChange, ...] = ()
) -> Report:
    deltas = compare(rows)
    return Report("r2", "a", "b", "light", ("pi",), verdict(rows, deltas), tuple(deltas), sizes, None, usage(rows))  # fmt: skip


def test_compare_summarises_completed_rows_per_variant() -> None:
    rows = [
        row(tokens=100, context=10, cost=1.0, wall_s=10),
        row(tokens=300, context=30, cost=None),
        row(passed=False, tokens=900, context=20, cost=3.0, wall_s=30),
        row(error="boom", context=999, wall_s=999),
        row("b"),
    ]

    (delta,) = compare(rows)

    assert (
        delta.a.passed,
        delta.a.total,
        delta.a.median_tokens,
        delta.a.median_context,
        delta.a.median_cost_usd,
        delta.a.median_wall_s,
    ) == (3, 4, 300, 20, 2.0, 10)
    assert (delta.a.errors, delta.a.memory["memory_calls"]) == (("boom",), 2.0)
    assert delta.b.total == 1


def chained(summary: Summary) -> Summary:
    return replace(
        summary,
        chain_cost_usd=summary.median_cost_usd,
        chain_wall_s=summary.median_wall_s,
        chain_runs=summary.completed,
    )


BASE = chained(
    Summary(
        12, 12, completed=12, median_context=1000, median_cost_usd=1.0, median_wall_s=10
    )
)


def test_usage_sums_every_row_and_counts_only_judge_tokens_of_reused_ones() -> None:
    rows = [
        row(tokens=100, cost=0.5),
        row(tokens=50, cost=None, error="x"),
        {**row(tokens=40, cost=2.0), "reused_from": "r1"},
    ]

    used = usage(rows)

    assert (used.agent_tokens, used.judge_tokens, used.agent_cost_usd) == (150, 21, 0.5)
    assert (used.reused_runs, used.reused_cost_usd) == (1, 2.0)


def delta(b: Summary) -> ScenarioDelta:
    return ScenarioDelta("s1", "claude", DEFAULT_GATE, BASE, chained(b), chain=("s1",))


@pytest.mark.parametrize(
    ("b", "regressed"),
    [
        (Summary(0, 12, median_context=1000, median_cost_usd=1.0), True),
        (Summary(2, 3, median_context=1250, median_cost_usd=1.5), False),
        (Summary(3, 3, 3, median_context=1000, median_cost_usd=1.6), True),
        (Summary(3, 3, 2, median_context=1000, median_cost_usd=1.6), False),
        (Summary(0, 0, median_context=5000), False),
    ],
)
def test_verdict_applies_the_gate(b: Summary, regressed: bool) -> None:
    assert verdict([row()], [delta(b)]) == ("regressed" if regressed else "ok")
    assert verdict([row(error="x")], [delta(b)]) == "all errored"


def test_render_json_and_summaries() -> None:
    a = Summary(
        2,
        3,
        median_context=1000,
        median_start_context=400,
        median_cost_usd=0.5,
        median_turns=7,
        median_wall_s=100,
        errors=("timeout",),
        median_tokens=100,
    )
    b = Summary(
        1,
        3,
        median_context=1200,
        median_cost_usd=0.6,
        median_turns=9,
        median_wall_s=150,
        median_tokens=150,
        memory={"memory_calls": 2.0},
    )
    d = ScenarioDelta("s1", "claude", DEFAULT_GATE, a, b)
    report = Report(
        "run-1",
        "origin/main",
        "worktree",
        "light",
        ("claude", "pi"),
        "regressed",
        (d,),
        (SizeChange("pi", 1, 2, 1),),
        None,
        Usage(300, 20, 1.234),
    )
    out = StringIO()
    Console(file=out, width=200).print(
        summary_table([d], size_summary(report.prompt_size))
    )

    markdown = render(report)
    data = json.loads(to_json(report))
    text = summary([d], size_summary(report.prompt_size))

    assert markdown.startswith(
        "# Benchmark origin/main -> worktree\n\nRun run-1, level light, agents claude, pi. Gate: regressed.\n"
    )
    (line,) = [x for x in markdown.splitlines() if x.startswith("|") and "s1" in x]
    assert all(
        p in line
        for p in (
            "2/3",
            "400->1,000",
            "0->1,200",
            "+20%",
            "$0.50",
            "100s",
            "150s",
            "+50%",
            "| 7 | 9 | 0 | 0 | -",
            "memory_calls=2",
        )
    )
    assert "Actual tokens: 320 (agent 300, judge 20), agent cost $1.23\n" in markdown
    assert data["usage"]["judge_tokens"] == 20
    assert "Errors:\n- s1 claude A: timeout\n" in markdown
    assert "- pi: 1 -> 2 bytes (+1)\n" in markdown
    assert (data["verdict"], data["scenarios"][0]["token_change"]) == ("regressed", 0.5)
    assert text.splitlines()[0].endswith(
        "(+20%), cost $0.50 -> $0.60 (+20%), time 100s -> 150s (+50%), A error: timeout"
    )
    assert "Prompt size: pi +1 bytes" in out.getvalue()
    assert markdown.endswith(
        "## Overall\n\nOverall: B regressed. Pass rate 2/3 to 1/3 (-1 cells), cost +20%, time +50%.\nPrompt: pi +1 bytes, no passes gained.\n"
    )
    assert data["summary"] == outcome_summary(report).splitlines()


def skipped(variant: str, repeat: int, reason: str) -> dict[str, JsonValue]:
    return {**row(variant, passed=False, tokens=0), "repeat": repeat, "skipped": reason}


def test_skipped_rows_are_not_counted_as_passes_or_failures_and_are_listed() -> None:
    reason = "first 2 repeats all failed tool_called(name=x)"
    rows = [
        row(passed=False), row(passed=False), skipped("a", 2, reason), skipped("a", 3, reason),
        row("b"), row("b"), row("b"),
    ]  # fmt: skip
    report = full_report(rows)
    (d,) = report.scenarios

    markdown = render(report)
    data = json.loads(to_json(report))

    assert (d.a.passed, d.a.total, d.a.skipped_total) == (0, 2, 2)
    assert (d.b.passed, d.b.total, d.b.skipped_total) == (3, 3, 0)
    assert d.a.median_tokens == 100
    assert "| 0/2 [0%-66%] (2 skipped) | 3/3 [44%-100%] |" in markdown
    assert f"Skipped:\n- s1 claude A: #3, #4 skipped, {reason}\n" in markdown
    assert data["scenarios"][0]["a"]["skipped"] == {reason: [2, 3]}
    assert f"A skipped 2: {reason}" in summary([d], "")
    assert reason in summary_table_text([d])


def summary_table_text(deltas: list[ScenarioDelta], width: int = 400) -> str:
    out = StringIO()
    Console(file=out, width=width).print(summary_table(deltas, ""))
    return out.getvalue()


def test_a_run_cut_short_by_a_setup_error_is_aborted_not_all_errored_or_ok() -> None:
    rows = [
        row("a", passed=False, error="agent exit 1: auth failed"),
        skipped("b", 0, "setup error: agent exit 1: auth failed"),
    ]
    report = full_report(rows)

    assert report.verdict == "aborted"
    assert "Gate: aborted by a setup error." in render(report)
    assert (
        verdict([row(error="x"), skipped("a", 1, "first 2 repeats all failed y")], [])
        == "all errored"
    )


def outcome(
    rows: list[dict[str, JsonValue]], sizes: tuple[SizeChange, ...] = ()
) -> str:
    return outcome_summary(full_report(rows, sizes))


def scenario(
    name: str, a: list[bool], b: list[bool], b_cost: float = 0.5
) -> list[dict[str, JsonValue]]:
    return [
        {**row(v, passed=p, cost=cost), "scenario": name, "agent": "pi", "repeat": n}
        for v, results, cost in (("a", a, 0.5), ("b", b, b_cost))
        for n, p in enumerate(results)
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (
            scenario("s1", [True, False], [True, True]) + scenario("s2", [True], [True]),
            "Overall: B improved. Pass rate 2/3 to 3/3 (+1 cells), cost +0%, time +0%.",
        ),
        (
            scenario("s1", [False] * 3, [True, True, False]) + scenario("s2", [True] * 3, [True, True, False]),
            "Overall: B no change. Pass rate 3/6 to 4/6 (+1 cells), cost +0%, time +0%.",
        ),
        (
            scenario("s1", [True, True], [True, False]),
            "Overall: B regressed. Pass rate 2/2 to 1/2 (-1 cells), cost +0%, time +0%.",
        ),
        (
            scenario("s1", [True, False, True], [True] * 3, b_cost=1.0),
            "Overall: B regressed. Pass rate 2/3 to 3/3 (+1 cells), cost +100%, time +0%.",
        ),
    ],
)  # fmt: skip
def test_overall_is_decided_by_passing_cells_and_the_gate(
    rows: list[dict[str, JsonValue]], expected: str
) -> None:
    assert outcome(rows).splitlines()[0] == expected


@pytest.mark.parametrize(
    ("a", "b", "size", "expected"),
    [
        ([False, True], [True, True], 1024, ["Prompt: pi +1,024 bytes = +1.00 passing cells per KB, $1.00 per extra pass."]),
        ([False, True], [False, True], 1024, ["Prompt: pi +1,024 bytes, no passes gained."]),
        ([True, True], [False, True], 1024, ["Prompt: pi +1,024 bytes, no passes gained."]),
        ([False, True], [True, True], -512, ["Prompt: pi -512 bytes, passing cells +1."]),
        ([False, True], [True, True], 0, []),
    ],
)  # fmt: skip
def test_prompt_value_is_passing_cells_gained_per_kb_of_added_prompt(
    a: list[bool], b: list[bool], size: int, expected: list[str]
) -> None:
    sizes = (SizeChange("pi", 0, size, size), SizeChange("claude-code", 0, 99, 99))

    assert outcome(scenario("s1", a, b, b_cost=1.0), sizes).splitlines()[1:] == expected


def test_a_regressed_gate_names_the_scenario_and_rule_that_tripped_it() -> None:
    rows = scenario("s1", [True] * 3, [True] * 3, b_cost=0.8) + scenario(
        "s2", [True] * 12, [False] * 12
    )
    report = full_report(rows)
    deltas = report.scenarios

    assert gate_breaches(deltas) == (
        "s1 pi: cost +60% (limit +50%, median of 3 A and 3 B runs)",
        "s2 pi: pass rate 12/12 -> 0/12 (drop 100%, limit 34%, 95% intervals 76%-100% and 0%-24% do not overlap)",
    )
    assert "Gate: regressed.\n\nGate breaches:\n- s1 pi: cost +60%" in render(report)
    assert json.loads(to_json(report))["gate_breaches"][0].startswith("s1 pi: cost")
    assert "Gate breach: s1 pi: cost +60%" in summary(deltas, "")


def test_rise_rules_below_three_completed_runs_are_info_not_a_breach() -> None:
    rows = scenario("s1", [True] * 2, [True] * 2, b_cost=0.8) + scenario(
        "s2", [True] * 12, [False] * 12
    )
    deltas = compare(rows)

    assert gate_notes(deltas) == (
        "s1 pi: cost +60% over limit +50%, not gated (needs 3 completed runs on each side, has 2 A and 2 B)",
    )
    assert (
        len(gate_breaches(deltas)) == 1
        and "s2 pi: pass rate 12/12" in gate_breaches(deltas)[0]
    )
    assert "Gate info: s1 pi: cost +60% over limit" in summary(deltas, "")


def test_a_pass_that_costs_less_than_a_cent_extra_is_no_extra_cost() -> None:
    sizes = (SizeChange("pi", 0, 1024, 1024),)

    lines = outcome(scenario("s1", [False, True], [True, True], b_cost=0.4999), sizes)

    assert (
        lines.splitlines()[1]
        == "Prompt: pi +1,024 bytes = +1.00 passing cells per KB, no extra cost."
    )


def follow_up(
    name: str,
    base: str,
    variant: str,
    cost: float = 0.1,
    fresh: bool = False,
    **more: JsonValue,
) -> dict[str, JsonValue]:
    return {
        **row(variant, cost=cost),
        "scenario": name, "agent": "pi", "follow_up_of": base, "fresh": fresh, **more,
    }  # fmt: skip


def base_row(
    name: str, variant: str, cost: float = 0.5, **more: JsonValue
) -> dict[str, JsonValue]:
    return {**row(variant, cost=cost), "scenario": name, "agent": "pi", **more}


def test_follow_up_rows_are_marked_in_the_table_the_markdown_and_the_json() -> None:
    rows = [
        base_row("root", "a"), base_row("root", "b"),
        follow_up("wrap", "root", "a"), follow_up("wrap", "root", "b"),
        follow_up("later", "wrap", "a", fresh=True), follow_up("later", "wrap", "b", fresh=True),
    ]  # fmt: skip
    report = full_report(rows)

    markdown = render(report)
    data = json.loads(to_json(report))

    names = [
        line.split(" | ")[0]
        for line in markdown.splitlines()
        if line.startswith("|") and "follow-up" in line
    ]
    assert names == [
        "| wrap -> follow-up of root",
        "| later -> fresh follow-up of wrap",
    ]
    assert "| root | pi |" in markdown
    assert "  ↳ later (fresh)" in summary_table_text(list(report.scenarios))
    assert [(d["scenario"], d["follow_up_of"], d["fresh"]) for d in data["scenarios"]] == [
        ("root", None, False), ("wrap", "root", False), ("later", "wrap", True),
    ]  # fmt: skip
    assert "Cost and time are each session's own" in markdown


def test_reused_rows_name_the_run_they_come_from_and_say_they_were_judged_again() -> (
    None
):
    rows = [
        base_row("root", "a", reused_from="r1"),
        base_row("root", "a", reused_from="r1"),
        base_row("root", "a"),
        base_row("root", "b"),
    ]
    report = full_report(rows)

    markdown = render(report)
    data = json.loads(to_json(report))

    assert (
        "| 3/3 [44%-100%] (2 reused from r1, re-judged) | 1/1 [21%-100%] |" in markdown
    )
    assert data["scenarios"][0]["a"]["reused_from"] == ["r1"]
    all_reused = full_report(
        [base_row("root", "a", reused_from="r1"), base_row("root", "b")]
    )
    assert "| 1/1 [21%-100%] (reused from r1, re-judged) |" in render(all_reused)


def test_terminal_table_marks_reused_passes_with_a_footnote_and_drops_all_zero_columns() -> (
    None
):
    report = full_report(
        [base_row("a-long-scenario-name", "a", reused_from="r1"), base_row("a-long-scenario-name", "b")]
    )  # fmt: skip

    text = summary_table_text(list(report.scenarios))

    assert "1/1*" in text
    assert "* reused from r1, re-judged" in text
    assert "a-long-scenario-name" in text
    assert "Failed" not in text
    assert "->" not in text
    assert "[" not in text


def test_terminal_table_fits_without_truncating_any_column_or_scenario_name() -> None:
    width = 140
    names = [
        "quality-lasting-fact",
        "quality-lasting-fact-wrap-up",
        "quality-lasting-fact-payoff",
    ]
    rows = [
        base_row(names[0], "a"), base_row(names[0], "b"),
        follow_up(names[1], names[0], "a"), follow_up(names[1], names[0], "b"),
        follow_up(names[2], names[1], "a", fresh=True), follow_up(names[2], names[1], "b", fresh=True),
    ]  # fmt: skip

    text = summary_table_text(list(full_report(rows).scenarios), width)

    assert "…" not in text
    assert all(name in text for name in names)
    assert all(len(line) <= width for line in text.splitlines())


def test_overall_counts_each_session_once_with_a_base_shared_by_several_follow_ups() -> (
    None
):
    rows = [
        base_row("root", v, cost=1.0) for v in "ab"
    ] + [
        follow_up(name, "root", v, cost=0.25) for name in ("one", "two") for v in "ab"
    ]  # fmt: skip

    lines = outcome(rows)

    assert (
        lines.splitlines()[0]
        == "Overall: B no change. Pass rate 3/3 to 3/3 (+0 cells), cost +0%, time +0%."
    )
    deltas = compare(rows)
    assert sum(d.a.spend_usd or 0 for d in deltas) == pytest.approx(1.5)
    assert sum(d.a.time_s for d in deltas) == pytest.approx(30)


def test_failed_test_runs_are_summed_per_side_and_shown_in_columns() -> None:
    rows = [
        base_row("root", "a", failed_test_runs=2), base_row("root", "a", failed_test_runs=1),
        base_row("root", "b", failed_test_runs=0), base_row("root", "b", error="x", failed_test_runs=5),
    ]  # fmt: skip
    (d,) = compare(rows)

    markdown = render(full_report(rows))

    assert (d.a.failed_test_runs, d.b.failed_test_runs) == (3, 0)
    assert "| Turns A | Turns B | Failed tests A | Failed tests B |" in markdown


def test_the_headline_scenario_leads_the_overall_line() -> None:
    rows = [
        {**follow_up("payoff", "wrap", v, cost=cost, fresh=True, headline=True, failed_test_runs=failed, repeat=n), "passed": ok}
        for v, cost, failed, oks in (("a", 0.2, 3, [True, False]), ("b", 0.1, 1, [True, True]))
        for n, ok in enumerate(oks)
    ]  # fmt: skip

    first = outcome(rows).splitlines()[0]

    assert first.startswith(
        "Overall: payoff payoff pi pass rate 1/2 to 2/2, cost $0.20 to $0.10 (-50%), failed test runs 6 to 2. B improved. Pass rate 1/2 to 2/2"
    )


def chain_rows(
    b_root: float, b_leaf: float, metric: str = "cost_usd", leaf: str = "payoff"
) -> list[dict[str, JsonValue]]:
    return [
        {**base_row("root", v, repeat=n), metric: value, "passed": True}
        for v, value in (("a", 0.5), ("b", b_root))
        for n in range(3)
    ] + [
        {**follow_up(leaf, "root", v, repeat=n), metric: value, "passed": True}
        for v, value in (("a", 0.5), ("b", b_leaf))
        for n in range(3)
    ]  # fmt: skip


@pytest.mark.parametrize(("metric", "rule"), [("cost_usd", "cost"), ("wall_s", "time")])
def test_cost_and_time_are_gated_over_the_whole_chain(metric: str, rule: str) -> None:
    credited = compare(chain_rows(0.9, 0.1, metric))
    over = compare(chain_rows(0.9, 1.0, metric))

    assert gate_breaches(credited) == ()
    assert gate_breaches(over) == (
        f"root > payoff pi: {rule} +90% (limit +50%, median of 3 A and 3 B chain runs)",
    )


def test_a_pass_drop_within_sampling_noise_is_info_not_a_breach() -> None:
    noisy = compare(scenario("s1", [True] * 3, [False] * 3))

    assert gate_breaches(noisy) == ()
    assert gate_notes(noisy) == (
        "s1 pi: pass rate 3/3 -> 0/3 drops over limit 34%, not gated (95% intervals 44%-100% and 0%-56% overlap)",
    )


def test_sibling_follow_ups_gate_their_own_chain_and_a_breach_names_that_path() -> None:
    rows = chain_rows(0.5, 0.5, leaf="left") + [
        r for r in chain_rows(0.5, 1.5, leaf="right") if r["scenario"] == "right"
    ]

    assert gate_breaches(compare(rows)) == (
        "root > right pi: cost +100% (limit +50%, median of 3 A and 3 B chain runs)",
    )


def test_a_repeat_with_an_errored_session_leaves_the_chain_and_too_few_repeats_are_info() -> (
    None
):
    rows = chain_rows(0.5, 1.5)
    rows[-1] = {**rows[-1], "error": "boom"}

    deltas = compare(rows)

    assert gate_breaches(deltas) == ()
    assert gate_notes(deltas) == (
        "root > payoff pi: cost +100% over limit +50%, not gated (needs 3 completed chain runs on each side, has 3 A and 2 B)",
    )


def test_a_base_context_rise_still_breaches_on_its_own_inside_a_chain() -> None:
    rows = [
        {**r, "context": 100 if r["variant"] == "b" else 10}
        for r in chain_rows(0.5, 0.5)
    ]

    assert gate_breaches(compare(rows)) == tuple(
        f"{name} pi: context +900% (limit +25%, median of 3 A and 3 B runs)"
        for name in ("root", "payoff")
    )


def test_chains_of_several_scenarios_are_listed_with_their_summed_cost_and_time() -> (
    None
):
    report = full_report(chain_rows(0.9, 0.1))

    markdown = render(report)
    data = json.loads(to_json(report))

    assert "## Chains\n" in markdown
    assert (
        "| root > payoff | pi | $1.00 | $1.00 | +0% | 20s | 20s | +0% | 3 | 3 |"
        in markdown
    )
    root, payoff = data["scenarios"]
    assert (root["chain"], payoff["chain"]) == ([], ["root", "payoff"])
    assert payoff["chain_cost_change"] == pytest.approx(0.0)
    assert "## Chains" not in render(
        full_report(scenario("s1", [True] * 3, [True] * 3))
    )


def test_startup_errors_are_left_out_of_the_pass_rate_and_the_gate_counts_and_retried_runs_are_counted() -> (
    None
):
    errored = {**row(error="startup error: agent exit 1: throttled"), "startup_error": True, "retries": 3, "retry_cost_usd": 0.3}  # fmt: skip
    rows = [row(), {**row(), "retries": 1, "startup_error": False}, errored, row("b"), row("b"), row("b")]  # fmt: skip
    report = full_report(rows)
    (d,) = report.scenarios

    markdown = render(report)

    assert (d.a.passed, d.a.total, d.a.completed, d.a.startup_errors, d.a.retried) == (2, 2, 2, 1, 2)  # fmt: skip
    assert "| 2/2 [34%-100%] (+1 error) |" in markdown
    assert "Retried runs: 2." in markdown
    assert "Retried runs: 2." in render(report, public=True)
    assert "(+1 error)" in summary_table_text([d])
    assert verdict(rows, [d]) == "ok"


def test_usage_adds_the_cost_of_failed_attempts_to_the_agent_cost() -> None:
    rows = [{**row(cost=0.5), "retry_cost_usd": 0.25}, row(cost=0.5)]

    assert usage(rows).agent_cost_usd == 1.25
