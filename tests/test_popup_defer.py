"""Tests for the popup-defer pi extension."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "extensions"
    / "popup-defer.ts"
)
_HARNESS = Path(__file__).parent / "popup_defer_harness.mjs"
_DEBOUNCE_MS = 200
_TICK_MS = 30


def _can_strip_types() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run(
        [node, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not _can_strip_types(), reason="node with type stripping missing"
)


def _run(
    tmp_path: Path,
    steps: list[dict[str, Any]],
    *,
    debounce: str = str(_DEBOUNCE_MS),
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"script": str(_SCRIPT), "limits": limits or {}, "steps": steps})
    )
    done = subprocess.run(
        ["node", str(_HARNESS), str(config)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PI_POPUP_DEFER_MS": debounce},
    )
    output: dict[str, Any] = json.loads(done.stdout)
    assert "error" not in output, output["error"]
    results: dict[str, Any] = output["results"]
    return results


_DIALOG_CALLS: dict[str, list[Any]] = {
    "select": ["Pick", ["a", "b"]],
    "confirm": ["Sure?", "message"],
    "input": ["Name", "placeholder"],
    "editor": ["Edit", "prefill"],
    "custom": [{"$fn": 1}],
}


@pytest.mark.parametrize("method", sorted(_DIALOG_CALLS))
def test_dialog_is_held_while_typing_then_shown_after_a_pause(
    tmp_path: Path, method: str
) -> None:
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"call": method, "args": _DIALOG_CALLS[method], "as": "result"},
            {"sleep": _DEBOUNCE_MS // 2},
            {"shown": "while_typing"},
            {"sleep": _DEBOUNCE_MS},
            {"shown": "after_pause"},
        ],
    )
    assert results["while_typing"] == []
    assert [call["method"] for call in results["after_pause"]] == [method]
    assert results["after_pause"][0]["at"] >= _DEBOUNCE_MS
    assert results["result"]["value"] == f"{method}-result"


@pytest.mark.parametrize(
    ("start", "typed"),
    [({}, False), ({"mode": "rpc"}, True)],
    ids=["tui-idle", "not-tui"],
)
def test_dialog_is_shown_at_once_when_not_typing_or_not_in_the_tui(
    tmp_path: Path, start: dict[str, str], typed: bool
) -> None:
    steps: list[dict[str, Any]] = [{"start": start}]
    if typed:
        steps.append({"key": "a"})
    steps += [
        {"call": "select", "args": _DIALOG_CALLS["select"]},
        {"sleep": _TICK_MS},
        {"shown": "shown"},
        {"handlers": "handlers"},
    ]
    results = _run(tmp_path, steps)
    assert [call["method"] for call in results["shown"]] == ["select"]
    assert results["shown"][0]["at"] < _DEBOUNCE_MS
    assert results["handlers"] == (0 if start else 1)


@pytest.mark.parametrize(
    "data",
    [
        "\x1b[<0;10;5M",
        "\x1b[<0;10;5m",
        "\x1b[I",
        "\x1b[O",
        "\x1b[?997;1n",
        "\x1b[97;1:3u",
    ],
    ids=["mouse-press", "mouse-release", "focus-in", "focus-out", "colour", "release"],
)
def test_terminal_reports_that_are_not_keystrokes_do_not_hold_a_dialog(
    tmp_path: Path, data: str
) -> None:
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": data, "as": "consumed"},
            {"call": "select", "args": _DIALOG_CALLS["select"]},
            {"sleep": _TICK_MS},
            {"shown": "shown"},
        ],
    )
    assert len(results["shown"]) == 1
    assert results["consumed"] is False


def test_keystrokes_are_passed_through_unconsumed(tmp_path: Path) -> None:
    results = _run(
        tmp_path,
        [{"start": {}}, {"key": "a", "as": "plain"}, {"key": "\x1b[A", "as": "arrow"}],
    )
    assert results["plain"] is False
    assert results["arrow"] is False


@pytest.mark.parametrize("enter", ["\r", "\n", "\x1b[13u"], ids=["cr", "lf", "kitty"])
def test_enter_ends_the_typing_burst(tmp_path: Path, enter: str) -> None:
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"call": "select", "args": _DIALOG_CALLS["select"]},
            {"sleep": _TICK_MS},
            {"shown": "held"},
            {"key": enter},
            {"sleep": _TICK_MS},
            {"shown": "released"},
        ],
    )
    assert results["held"] == []
    assert len(results["released"]) == 1


def test_held_dialogs_are_shown_in_the_order_they_were_requested(
    tmp_path: Path,
) -> None:
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"call": "select", "args": _DIALOG_CALLS["select"]},
            {"call": "confirm", "args": _DIALOG_CALLS["confirm"]},
            {"call": "input", "args": _DIALOG_CALLS["input"]},
            {"sleep": _DEBOUNCE_MS * 2},
            {"shown": "shown"},
        ],
    )
    assert [call["method"] for call in results["shown"]] == [
        "select",
        "confirm",
        "input",
    ]


def test_a_dialog_is_shown_after_the_max_hold_even_if_typing_continues(
    tmp_path: Path,
) -> None:
    max_hold = _DEBOUNCE_MS * 3
    steps: list[dict[str, Any]] = [
        {"start": {}},
        {"key": "a"},
        {"call": "select", "args": _DIALOG_CALLS["select"]},
    ]
    for _ in range(max_hold // _TICK_MS + 5):
        steps += [{"sleep": _TICK_MS}, {"key": "a"}]
    steps.append({"shown": "shown"})
    results = _run(tmp_path, steps, limits={"maxHoldMs": max_hold})
    assert len(results["shown"]) == 1
    assert max_hold <= results["shown"][0]["at"] < max_hold + _DEBOUNCE_MS


@pytest.mark.parametrize("method", ["select", "confirm", "input"])
def test_aborting_a_held_dialog_resolves_it_without_showing_it(
    tmp_path: Path, method: str
) -> None:
    args = [*_DIALOG_CALLS[method], {"signal": {"$signal": "stop"}}]
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"call": method, "args": args, "as": "result"},
            {"sleep": _TICK_MS},
            {"abort": "stop"},
            {"sleep": _DEBOUNCE_MS * 2},
            {"shown": "shown"},
        ],
    )
    assert results["shown"] == []
    assert results["result"]["value"] is None
    assert results["result"]["at"] < _DEBOUNCE_MS


def test_hold_time_is_subtracted_from_the_dialog_timeout(tmp_path: Path) -> None:
    timeout = _DEBOUNCE_MS * 5
    args = [*_DIALOG_CALLS["confirm"], {"timeout": timeout}]
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"call": "confirm", "args": args},
            {"sleep": _DEBOUNCE_MS * 2},
            {"shown": "shown"},
        ],
    )
    shown_timeout = results["shown"][0]["args"][2]["timeout"]
    assert shown_timeout <= timeout - _DEBOUNCE_MS
    assert shown_timeout > 0


def test_a_dialog_whose_timeout_ends_during_the_hold_is_never_shown(
    tmp_path: Path,
) -> None:
    timeout = _DEBOUNCE_MS // 2
    args = [*_DIALOG_CALLS["confirm"], {"timeout": timeout}]
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"call": "confirm", "args": args, "as": "result"},
            {"sleep": _DEBOUNCE_MS * 2},
            {"shown": "shown"},
        ],
    )
    assert results["shown"] == []
    assert results["result"]["value"] is None
    assert results["result"]["at"] < _DEBOUNCE_MS


def test_a_dialog_with_an_already_aborted_signal_is_not_shown(tmp_path: Path) -> None:
    args = [*_DIALOG_CALLS["select"], {"signal": {"$signal": "stop"}}]
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"abort": "stop"},
            {"call": "select", "args": args, "as": "result"},
            {"sleep": _TICK_MS},
            {"shown": "shown"},
        ],
    )
    assert results["shown"] == []
    assert results["result"]["value"] is None


def test_a_zero_timeout_means_no_timeout_and_is_left_alone(tmp_path: Path) -> None:
    args = [*_DIALOG_CALLS["confirm"], {"timeout": 0}]
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"call": "confirm", "args": args},
            {"sleep": _DEBOUNCE_MS * 2},
            {"shown": "shown"},
        ],
    )
    assert results["shown"][0]["args"][2] == {"timeout": 0}


def test_printable_keys_are_swallowed_briefly_after_a_dialog_mounts(
    tmp_path: Path,
) -> None:
    swallow = _DEBOUNCE_MS
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"call": "select", "args": _DIALOG_CALLS["select"]},
            {"sleep": _DEBOUNCE_MS + _TICK_MS},
            {"key": "b", "as": "printable"},
            {"key": "\x1b[A", "as": "arrow"},
            {"key": "\r", "as": "enter"},
            {"sleep": swallow},
            {"key": "c", "as": "later"},
        ],
        limits={"swallowMs": swallow},
    )
    assert results["printable"] is True
    assert (results["arrow"], results["enter"], results["later"]) == (False,) * 3


def test_zero_in_the_environment_turns_deferral_off(tmp_path: Path) -> None:
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"call": "select", "args": _DIALOG_CALLS["select"]},
            {"sleep": _TICK_MS},
            {"shown": "shown"},
            {"key": "b", "as": "after_mount"},
        ],
        debounce="0",
    )
    assert len(results["shown"]) == 1
    assert results["after_mount"] is False


def _typed_select_steps(*before: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"start": {}},
        *before,
        {"key": "a"},
        {"call": "select", "args": _DIALOG_CALLS["select"]},
        {"sleep": _TICK_MS},
        {"shown": "shown"},
    ]


@pytest.mark.parametrize(
    ("env", "command", "held"),
    [
        (str(_DEBOUNCE_MS), "off", False),
        (str(_DEBOUNCE_MS), "0", False),
        (str(_DEBOUNCE_MS), "on", True),
        (str(_DEBOUNCE_MS), "5000", True),
        ("0", "on", True),
        ("0", str(_DEBOUNCE_MS), True),
    ],
)
def test_popup_defer_command_switches_deferral(
    tmp_path: Path, env: str, command: str, held: bool
) -> None:
    results = _run(
        tmp_path,
        _typed_select_steps({"command": "popup-defer", "args": command}),
        debounce=env,
    )
    assert (results["shown"] == []) is held


def test_starting_a_session_again_does_not_stack_wrappers_or_subscriptions(
    tmp_path: Path,
) -> None:
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"start": {}},
            {"start": {}, "pi": "reloaded"},
            {"handlers": "handlers"},
            {"key": "a", "as": "unused"},
            {"call": "select", "args": _DIALOG_CALLS["select"]},
            {"sleep": _DEBOUNCE_MS * 2},
            {"shown": "shown"},
            {"command": "popup-defer", "args": "off", "pi": "reloaded"},
            {"key": "b"},
            {"call": "select", "args": _DIALOG_CALLS["select"]},
            {"sleep": _TICK_MS},
            {"shown": "after_off"},
        ],
    )
    assert results["handlers"] == 1
    assert len(results["shown"]) == 1
    assert len(results["after_off"]) == 2


def test_turning_deferral_off_releases_dialogs_already_held(tmp_path: Path) -> None:
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"key": "a"},
            {"call": "select", "args": _DIALOG_CALLS["select"]},
            {"sleep": _TICK_MS},
            {"command": "popup-defer", "args": "off"},
            {"sleep": _TICK_MS},
            {"shown": "shown"},
        ],
    )
    assert len(results["shown"]) == 1


def test_popup_defer_command_reports_state_and_rejects_bad_input(
    tmp_path: Path,
) -> None:
    results = _run(
        tmp_path,
        [
            {"start": {}},
            {"command": "popup-defer", "args": ""},
            {"command": "popup-defer", "args": "soon"},
            {"command": "popup-defer", "args": "off"},
            {"notices": "notices"},
        ],
    )
    assert results["notices"] == [
        f"popup-defer on, {_DEBOUNCE_MS} ms",
        "Usage: /popup-defer [on|off|<ms>]",
        "popup-defer off",
    ]
