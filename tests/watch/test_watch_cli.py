"""Tests for the watch command line."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from conftest import FakeSubprocess

from llm_prompts import cli
from llm_prompts.watch.sources.command import CommandSource


def run_cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int | None:
    monkeypatch.setattr(sys, "argv", ["llm-prompts", "watch", *argv])
    return cli.main()


def test_cli_exits_0_when_the_command_succeeds(
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_subprocess.on("test")

    assert run_cli(monkeypatch, "cmd", "--until", "ok", "--", "test", "-f", "flag") == 0
    assert capsys.readouterr().out == "cmd test: ok (exit=0)\n"


def test_cli_exits_124_on_timeout(
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_subprocess.on("test", returncode=1)

    argv = ("cmd", "--until", "ok", "--timeout", "0", "--", "test", "-f", "x")

    assert run_cli(monkeypatch, *argv) == 124
    assert capsys.readouterr().out.startswith("cmd test: timeout (exit=1 ")


def test_cli_limits_each_command_run_to_the_timeout(
    fake_subprocess: FakeSubprocess, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_subprocess.on("tool")

    argv = ("cmd", "--until", "ok", "--interval", "1", "--timeout", "60", "--", "tool")

    assert run_cli(monkeypatch, *argv) == 0
    assert fake_subprocess.calls[0][1]["timeout"] == 60


def test_cli_exits_0_when_the_output_changes(
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_subprocess.on("cat", stdout=["one", "two"])

    argv = ("cmd", "--until", "update", "--interval", "0", "--", "cat", "flag")

    assert run_cli(monkeypatch, *argv) == 0
    assert capsys.readouterr().out.startswith("cmd cat: update (sha=")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (FileNotFoundError("secret/path"), "watch: Command not found: tool\n"),
        (
            ZeroDivisionError("boom"),
            "watch: unexpected error: ZeroDivisionError: boom\n",
        ),
    ],
)
def test_cli_exits_1_with_a_fixed_message_on_error(
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    message: str,
) -> None:
    fake_subprocess.on("tool", side_effect=error)

    assert run_cli(monkeypatch, "cmd", "--until", "ok", "--", "tool") == 1
    assert capsys.readouterr().err == message


def test_cli_runs_a_source_an_installed_package_provides(
    fake_subprocess: FakeSubprocess, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PluginSource(CommandSource):
        name = "plugin-cmd"

    monkeypatch.setattr(
        "llm_prompts.watch.core.registry.entry_points",
        lambda group: [SimpleNamespace(load=lambda: PluginSource)],
    )
    fake_subprocess.on("test")

    assert run_cli(monkeypatch, "plugin-cmd", "--until", "ok", "--", "test") == 0
