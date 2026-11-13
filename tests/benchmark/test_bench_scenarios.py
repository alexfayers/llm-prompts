import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benchmark.conftest import UNSCRIPTED_TRACE
from llm_prompts.benchmark.scenarios import loader as scenarios
from llm_prompts.benchmark.scenarios.checks import CHECKS, evaluate
from llm_prompts.benchmark.scenarios.checks.context import CheckContext
from llm_prompts.benchmark.scenarios.loader import ScenarioError
from llm_prompts.benchmark.types import (
    DEFAULT_GATE,
    CheckOutcome,
    CheckSpec,
    MemoryEntity,
    Scenario,
    ToolCall,
)

REQUIRED = """\
id = "demo"
level = "light"
workspace = "ws"
project = "demo"
prompt = "Do the thing."

[[check]]
kind = "tool_called"
name = "done"
"""
FULL = (
    REQUIRED.replace(
        '"light"',
        '"medium"\nagents = ["pi"]\ntimeout_s = 60\nsetup = ["git branch x", "ls"]',
    )
    + """
[gate]
max_pass_drop = 0.1
max_time_rise = 0.2

[[memory]]
name = "pattern/retry"
entityType = "pattern"
observations = ["retry 3 times"]
relations = [{ target = "project/demo", type = "part-of" }]
status = "active"

[[check]]
kind = "tool_called"
name = "a"
before = ["Edit", "Write"]
"""
)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "fixtures" / "ws").mkdir(parents=True)
    monkeypatch.setattr(scenarios, "DATA_DIR", tmp_path)
    return tmp_path


def add(data_dir: Path, name: str, text: str = REQUIRED) -> Path:
    path = data_dir / f"{name}.toml"
    path.write_text(text.replace('id = "demo"', f'id = "{name}"', 1))
    return path


def test_parse_full_file_and_defaults(data_dir: Path) -> None:
    full = scenarios.parse(add(data_dir, "demo", FULL))
    plain = scenarios.parse(add(data_dir, "plain"))

    assert full == Scenario(
        "demo", "medium", ("pi",), data_dir / "fixtures" / "ws", "demo", "Do the thing.", 60,
        replace(DEFAULT_GATE, max_pass_drop=0.1, max_time_rise=0.2),
        (MemoryEntity("pattern/retry", "pattern", ("retry 3 times",), (("project/demo", "part-of"),), "active"),),
        (CheckSpec("tool_called", {"name": "done"}), CheckSpec("tool_called", {"name": "a", "before": ("Edit", "Write")})),
        setup=("git branch x", "ls"),
    )  # fmt: skip
    assert (plain.agents, plain.timeout_s, plain.gate) == (
        ("claude", "pi"),
        300,
        DEFAULT_GATE,
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('"light"', '"light"\nmax_turns = 1'),
        ('"tool_called"', '"nonsense"'),
        ('"ws"', '"../x"'),
        ('"light"', '"extreme"'),
        ("[[check]]", "[[nothing]]"),
        ('project = "demo"\n', ""),
        ('"light"', '"light"\nagents = "x"'),
        ('"light"', '"light"\nagents = [1]'),
        ('"light"', '"light"\nagents = []'),
        ('"light"', '"light"\nmemory = [1]'),
        ('"light"', '"light"\ntimeout_s = 0'),
        ('"light"', '"light"\n='),
        ('"ws"', '"nope"'),
        ('"done"', "1.5"),
        ('id = "demo"', 'id = "other"'),
        ('[[check]]\nkind = "tool_called"\nname = "done"\n', ""),
    ],
)
def test_parse_rejects_violation(data_dir: Path, old: str, new: str) -> None:
    path = add(data_dir, "demo", REQUIRED.replace(old, new))

    with pytest.raises(ScenarioError, match=str(path)):
        scenarios.parse(path)


def test_delegation_is_parsed_inherited_by_a_follow_up_and_limited_to_claude(
    data_dir: Path,
) -> None:
    claude_only = REQUIRED.replace('"light"', '"light"\nagents = ["claude"]')
    root = scenarios.parse(
        add(
            data_dir,
            "root",
            claude_only.replace('"light"', '"light"\ndelegation = true'),
        )
    )
    follow_up = scenarios.parse(add(data_dir, "next", FOLLOW_UP))
    plain = scenarios.parse(add(data_dir, "plain"))

    assert (root.delegation, follow_up.delegation, plain.delegation) == (
        True,
        True,
        False,
    )
    for agents in ('["claude", "pi"]', '["pi"]'):
        path = add(
            data_dir,
            "bad",
            REQUIRED.replace(
                '"light"', f'"light"\nagents = {agents}\ndelegation = true'
            ),
        )
        with pytest.raises(ScenarioError, match="delegation"):
            scenarios.parse(path)


FOLLOW_UP = """\
id = "demo"
level = "light"
base = "root"
prompt = "Then this."

[[check]]
kind = "tool_called"
name = "done"
"""


def test_follow_up_takes_workspace_project_memory_agents_and_setup_from_its_base(
    data_dir: Path,
) -> None:
    root = scenarios.parse(add(data_dir, "root", FULL))

    follow_up = scenarios.parse(add(data_dir, "next", FOLLOW_UP))

    assert follow_up.base == root
    assert (follow_up.workspace, follow_up.project, follow_up.memory, follow_up.agents) == (
        root.workspace, root.project, root.memory, root.agents,
    )  # fmt: skip
    assert follow_up.prompt == "Then this."
    assert follow_up.setup == root.setup == ("git branch x", "ls")


FRESH = FOLLOW_UP.replace(
    'base = "root"', 'base = "next"\nfresh = true\nheadline = true'
)


def test_fresh_follow_up_of_a_follow_up_takes_its_settings_through_the_chain(
    data_dir: Path,
) -> None:
    root = scenarios.parse(add(data_dir, "root", FULL))
    next_ = scenarios.parse(add(data_dir, "next", FOLLOW_UP))

    later = scenarios.parse(add(data_dir, "later", FRESH))

    assert later.base == next_
    assert (later.workspace, later.project, later.memory, later.agents) == (
        root.workspace, root.project, root.memory, root.agents,
    )  # fmt: skip
    assert (later.fresh, later.headline) == (True, True)
    assert (root.fresh, root.headline) == (False, False)
    assert later.ask == "Then this."
    assert next_.ask == root.prompt
    assert later.root == root


@pytest.mark.parametrize(
    "follow_up",
    [
        FOLLOW_UP.replace('base = "root"', 'base = "root"\nworkspace = "ws"'),
        FOLLOW_UP.replace('"root"', '"missing"'),
        FOLLOW_UP.replace('"root"', '"chained"'),
        FOLLOW_UP.replace('base = "root"', "fresh = true"),
        FOLLOW_UP.replace('base = "root"', 'base = "root"\nfresh = 1'),
    ],
    ids=[
        "own-workspace",
        "missing-base",
        "nested-base",
        "fresh-without-base",
        "fresh-not-a-bool",
    ],
)
def test_follow_up_rejects_violation(data_dir: Path, follow_up: str) -> None:
    add(data_dir, "root", FULL)
    add(data_dir, "chained", FOLLOW_UP)
    path = add(data_dir, "next", follow_up)

    with pytest.raises(ScenarioError, match=str(path)):
        scenarios.parse(path)


def test_follow_up_cycle_is_rejected(data_dir: Path) -> None:
    add(data_dir, "ping", FOLLOW_UP.replace('"root"', '"pong"\nfresh = true'))
    add(data_dir, "pong", FOLLOW_UP.replace('"root"', '"ping"\nfresh = true'))

    with pytest.raises(ScenarioError, match="cycle"):
        scenarios.parse(data_dir / "ping.toml")


def test_load_adds_every_ancestor_of_a_selected_follow_up(data_dir: Path) -> None:
    add(data_dir, "root", REQUIRED.replace("light", "heavy"))
    add(data_dir, "next", FOLLOW_UP.replace("light", "heavy"))
    add(data_dir, "later", FRESH)

    loaded = scenarios.load("light", ("claude", "pi"), ("later",))

    assert [s.id for s in loaded] == ["later", "next", "root"]


def test_load_filters_by_level_agents_and_ids_sorted(data_dir: Path) -> None:
    add(data_dir, "m", REQUIRED.replace("light", "medium"))
    add(data_dir, "l")
    add(data_dir, "c", REQUIRED.replace("workspace", 'agents = ["claude"]\nworkspace'))

    def ids(level: Any, agents: Any = ("claude", "pi"), wanted: Any = ()) -> list[str]:
        return [s.id for s in scenarios.load(level, agents, wanted)]

    assert (ids("light"), ids("medium"), ids("light", ("pi",))) == (
        ["c", "l"],
        ["c", "l", "m"],
        ["l"],
    )
    assert ids("light", wanted=("l",)) == ["l"]
    for missing, agents in (("m", ("claude",)), ("c", ("pi",))):
        with pytest.raises(ScenarioError, match=missing):
            ids("light", agents, (missing,))


def c(name: str, **args: str) -> ToolCall:
    return ToolCall(name, args, True)


def bash(command: str) -> ToolCall:
    return c("Bash", command=command)


WRAP_UP = (
    MemoryEntity(
        "feature/demo/url-scheme", "feature", ("fetch() rejects other schemes",)
    ),
    MemoryEntity(
        "task/demo-check",
        "task",
        ("Asked to add it",),
        (("feature/demo/url-scheme", "implements"),),
    ),
)
README = {"README.md": "Call fetch(url) to receive the body of a page.\n"}
SECOND_FEATURE = (
    *WRAP_UP,
    MemoryEntity("feature/demo/fetch-all", "feature", ("Callers get every body",)),
    MemoryEntity(
        "task/demo-fetch-all",
        "task",
        ("Asked to add it",),
        (("feature/demo/fetch-all", "implements"),),
    ),
)
# id: (scenario, expected pass, files, calls, added memory, replacement memory)
# fmt: off
CASES: dict[str, tuple[str, bool, dict[str, str], tuple[ToolCall, ...], tuple[MemoryEntity, ...], Any]] = {
    "retry-ok": ("recall-retry-policy", True, {"fetch.py": "time.sleep(2 ** attempt)\n"}, (c("memory.search_nodes"),), (), None),
    "no-push-ok": ("rule-no-push", True, README, (bash("git commit -am fix"),), (), None),
    "quality-ok": ("quality-simple-task", True, {"fetch.py": "raise DemoError\n"}, (), (), None),
    "second-feature-ok": ("quality-second-feature", True, {"fetch.py": "def fetch_all(urls):\n    pass\n"}, (), SECOND_FEATURE, None),
    "second-feature-only-one-feature": ("quality-second-feature", False, {"fetch.py": "def fetch_all(urls):\n    pass\n"}, (), WRAP_UP, None),
}
# fmt: on


@pytest.fixture(autouse=True)
def passing_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        CHECKS, "judge", lambda args, ctx: CheckOutcome("judge", True, "")
    )


def check_shipped(
    scenario_id: str,
    workspace: Path,
    files: dict[str, str] | None = None,
    calls: tuple[ToolCall, ...] = (),
    added: tuple[MemoryEntity, ...] = (),
    after: Any = None,
) -> bool:
    (scenario,) = (
        s for s in scenarios.load("heavy", ("claude", "pi")) if s.id == scenario_id
    )
    shutil.copytree(scenario.workspace, workspace)
    for relative, text in (files or {}).items():
        (workspace / relative).write_text(text)
    memory_after = (*scenario.memory, *added) if after is None else after
    context = CheckContext(
        replace(UNSCRIPTED_TRACE, tool_calls=calls),
        workspace,
        scenario.memory,
        memory_after,
    )
    return all(o.passed for o in evaluate(scenario.checks, context))


@pytest.mark.parametrize("case", CASES.values(), ids=CASES)
def test_shipped_scenario_checks(case: tuple[Any, ...], tmp_path: Path) -> None:
    scenario_id, expected, *rest = case

    assert check_shipped(scenario_id, tmp_path / "w", *rest) is expected


def test_an_agent_that_does_nothing_passes_no_shipped_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        CHECKS, "judge", lambda args, ctx: CheckOutcome("judge", False, "")
    )
    for scenario in scenarios.load("heavy", ("claude", "pi")):
        assert not check_shipped(scenario.id, tmp_path / scenario.id)
