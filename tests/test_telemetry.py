"""Tests for anonymous usage telemetry."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest
import truststore
from conftest import run_capturing_exit

from llm_prompts import cli, telemetry

A, B = "a" * 40, "b" * 40
EVENT: dict[str, Any] = {"event": "command_run", "properties": {}}
OPT_OUTS = ("DO_NOT_TRACK", "LLM_PROMPTS_NO_TELEMETRY", "CI")


def _props(popen: MagicMock) -> dict[str, Any]:
    properties: dict[str, Any] = _events(popen)[0]["properties"]
    return properties


def _events(popen: MagicMock) -> list[dict[str, Any]]:
    """Return the sent events, with placeholders resolved as the detached sender does."""
    return [
        json.loads(telemetry._resolve_checkouts(call.args[0][3]))
        for call in popen.call_args_list
    ]


def _from_to(popen: MagicMock) -> tuple[str, str]:
    props = _props(popen)
    return props["from"]["llm-prompts"]["commit"], props["to"]["llm-prompts"]["commit"]


def _main(*argv: str) -> int | str | None:
    with patch("sys.argv", ["llm-prompts", *argv]):
        return run_capturing_exit(cli.main)


@pytest.mark.parametrize(
    ("env", "config", "expected"),
    [
        ({}, {}, True),
        ({"DO_NOT_TRACK": "0"}, {}, True),
        ({"DO_NOT_TRACK": "1"}, {}, False),
        ({"CI": "true"}, {}, False),
        ({}, {"telemetry": {"enabled": False}}, False),
        ({}, {"telemetry": False}, False),
        ({}, {"telemetry": {"enabled": "false"}}, False),
    ],
)
def test_any_opt_out_disables_telemetry(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], config: Any, expected: bool
) -> None:
    for name in OPT_OUTS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    with patch("llm_prompts.telemetry.read_config", return_value=config):
        assert telemetry.enabled() is expected


def test_event_carries_only_allowlisted_properties(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = [
        {"name": "cline-hooks", "source": "/synthetic/hooks"},
        {"name": "acme-secret-overlay", "source": "~/synthetic/overlay"},
        {"name": "acme-internal", "source": "git+ssh://git.internal.example/acme"},
        {"name": "pub-overlay", "source": "git+https://github.com/acme/pub.git"},
        {"name": "local-pub", "source": "~/synthetic/pub"},
    ]
    monkeypatch.setattr("llm_prompts.telemetry.read_config", lambda: {"tools": tools})

    monkeypatch.setattr("llm_prompts.cli._get_installed_commit", lambda _: A)
    with telemetry.Run(lambda _: A) as run:
        run.begin("update", [], installs=True)

    posted = MagicMock()
    monkeypatch.setattr("llm_prompts.telemetry.post", posted)
    telemetry.deliver(telemetry_popen.call_args.args[0][3])
    properties = json.loads(posted.call_args.args[0])["properties"]
    assert set(properties) == {
        *("command", "from", "to", "agents", "overlay_count", "overlays", "outcome"),
        *("flags", "duration_s", "os", "python", "schema", "$process_person_profile"),
    }
    assert properties["from"]["cline-hooks"] == {
        "commit": None,
        "local": True,
        "dirty": None,
        "ahead": None,
    }
    assert properties["from"]["llm-prompts"] == {
        "commit": A,
        "local": False,
        "dirty": False,
        "ahead": None,
    }
    assert properties["overlay_count"] == 4
    assert properties["overlays"] == {
        "pub-overlay": {"commit": A, "local": False, "dirty": False, "ahead": None}
    }
    assert properties["schema"] == 2
    assert "acme-internal" not in json.dumps(properties)
    assert "acme-secret" not in json.dumps(properties)
    assert "synthetic" not in json.dumps(properties)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_a_git_checkout_source_reports_its_head_and_whether_it_is_dirty(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The detached sender inspects local checkouts, not the command."""
    repo, plain = tmp_path / "hooks", tmp_path / "plain"
    repo.mkdir()
    plain.mkdir()
    _git(repo, "init", "-q")
    _git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    )
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    commit = ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q")
    _git(repo, *commit, "--allow-empty", "-m", "y")
    head = _git(repo, "rev-parse", "HEAD")
    tools = [
        {"name": "cline-hooks", "source": str(repo)},
        {"name": "mcp-memory", "source": str(plain)},
    ]
    monkeypatch.setattr("llm_prompts.telemetry.read_config", lambda: {"tools": tools})

    for dirty in (False, True):
        if dirty:
            (repo / "f").write_text("x")
        with (
            patch("llm_prompts.telemetry.run", side_effect=AssertionError),
            telemetry.Run(lambda _: A) as run,
        ):
            run.begin("update", [])
        posted = MagicMock()
        monkeypatch.setattr("llm_prompts.telemetry.post", posted)
        telemetry.deliver(telemetry_popen.call_args.args[0][3])
        sent = json.loads(posted.call_args.args[0])["properties"]
        telemetry_popen.reset_mock()
        expected = {"commit": head, "local": True, "dirty": dirty, "ahead": 1}
        assert sent["from"]["cline-hooks"] == expected
        assert sent["to"]["cline-hooks"] == expected
        assert sent["from"]["mcp-memory"] == {
            "commit": None,
            "local": True,
            "dirty": None,
            "ahead": None,
        }
        assert str(tmp_path) not in posted.call_args.args[0]


def test_post_verifies_certificates_with_the_system_trust_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urlopen = MagicMock()
    monkeypatch.setattr("llm_prompts.telemetry.urlopen", urlopen)

    assert telemetry.post("{}") is True

    assert isinstance(urlopen.call_args.kwargs["context"], truststore.SSLContext)


def test_debug_mode_shows_why_a_post_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LLM_PROMPTS_TELEMETRY_DEBUG", "1")
    monkeypatch.setattr(
        "llm_prompts.telemetry.urlopen", MagicMock(side_effect=URLError("no cert"))
    )

    telemetry.send(EVENT, "id-1")

    err = capsys.readouterr().err
    assert "telemetry sent: False" in err
    assert "no cert" in err


@pytest.mark.parametrize("debug", ["0", "1"])
def test_send_spawns_a_detached_sender_unless_debugging(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch, debug: str
) -> None:
    urlopen = MagicMock(side_effect=URLError("offline"))
    monkeypatch.setenv("LLM_PROMPTS_TELEMETRY_DEBUG", debug)
    monkeypatch.setattr("llm_prompts.telemetry.urlopen", urlopen)

    telemetry.send(EVENT, "id-1")

    assert urlopen.called is (debug == "1")
    assert telemetry_popen.called is (debug == "0")
    if debug == "0":
        kwargs = telemetry_popen.call_args.kwargs
        assert kwargs["start_new_session"] is True
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert not [n for n in kwargs["env"] if n.startswith("LLM_PROMPTS_")]


def test_the_parent_never_waits_on_the_sender(telemetry_popen: MagicMock) -> None:
    telemetry.send(EVENT, "id-1")

    assert telemetry_popen.return_value.mock_calls == []


@pytest.mark.parametrize("saved", ["{}", "[]", "not json"])
def test_an_unreadable_install_id_is_a_first_run_that_sends_nothing(
    telemetry_popen: MagicMock, isolated_config_dir: Any, saved: str
) -> None:
    (isolated_config_dir / "telemetry.json").write_text(saved, encoding="utf-8")

    for expected_sends in (0, 1):
        with telemetry.Run(lambda _: A) as run:
            run.begin("update", [])
        assert telemetry_popen.call_count == expected_sends


@pytest.mark.parametrize(
    ("env", "resume"),
    [({"DO_NOT_TRACK": "1"}, None), ({}, "not json"), ({}, "[1]")],
    ids=["opted-out", "bad-resume-json", "bad-resume-state"],
)
def test_begin_never_starts_a_report_when_opted_out_or_the_resume_state_is_bad(
    telemetry_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    resume: str | None,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    if resume:
        monkeypatch.setenv(telemetry.RESUME_ENV, resume)

    with telemetry.Run(lambda _: A) as run:
        run.begin("update", [])

    telemetry_popen.assert_not_called()
    assert telemetry.RESUME_ENV not in os.environ


def test_a_failing_report_sends_nothing_and_keeps_the_command_result(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "llm_prompts.telemetry.read_manifest", MagicMock(side_effect=KeyError)
    )

    with telemetry.Run(lambda _: A) as run:
        run.begin("update", [])

    telemetry_popen.assert_not_called()


@pytest.fixture
def stubbed_cli(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub everything the commands touch outside telemetry."""
    for target in (
        "llm_prompts.cli._pull_local_sources",
        "llm_prompts.cli._check_for_updates",
        "llm_prompts.cli._reconfigure_agents",
        "llm_prompts.plugins.pull_plugin_sources",
        "llm_prompts.setup.detect_stale_local_tools",
        "llm_prompts.install.partial_source",
        "llm_prompts.setup.config_path",
        "subprocess.run",
    ):
        monkeypatch.setattr(target, MagicMock())
    monkeypatch.setattr("llm_prompts.manifest.read_manifest", lambda: {"kiro": {}})
    monkeypatch.setattr("llm_prompts.size_guard.snapshot_sources", lambda _: {})
    monkeypatch.setattr("llm_prompts.install.main", MagicMock(return_value=False))
    run_setup = MagicMock(return_value=False)
    monkeypatch.setattr("llm_prompts.setup.run_setup", run_setup)
    return run_setup


@pytest.mark.usefixtures("stubbed_cli")
@pytest.mark.parametrize(
    ("argv", "install_result", "outcome"),
    [
        (["update"], False, "ok"),
        (["update"], True, "size_guard_failed"),
        (["update"], ValueError("secret"), "error:ValueError"),
        (["setup"], False, "ok"),
        (["install", "kiro", "--no-update"], False, "ok"),
        (["install", "kiro"], False, None),
        (["install", "kiro", "--root", "/synthetic/root"], False, "ok"),
        (["update", "--check"], False, "ok"),
        (["update", "--only", "/synthetic/rule.md"], False, "ok"),
        (["setup", "--dry-run"], False, "ok"),
        (["check"], False, "ok"),
    ],
)
def test_a_command_sends_at_most_one_event_naming_its_outcome(
    telemetry_popen: MagicMock,
    argv: list[str],
    install_result: Any,
    outcome: str | None,
) -> None:
    with (
        patch("llm_prompts.install.main", side_effect=[install_result]),
        contextlib.suppress(ValueError),
    ):
        _main(*argv)

    failed = isinstance(install_result, Exception)
    assert telemetry_popen.call_count == int(outcome is not None) + failed
    if outcome:
        assert _props(telemetry_popen)["outcome"] == outcome
        assert "secret" not in json.dumps(_props(telemetry_popen))


@pytest.mark.usefixtures("stubbed_cli")
def test_the_event_lists_sorted_flag_names_and_never_their_values(
    telemetry_popen: MagicMock,
) -> None:
    _main("install", "kiro", "--root=/synthetic/root", "--no-update", "-v")

    flags = _props(telemetry_popen)["flags"]
    assert flags == ["--no-update", "--root", "-v"]
    assert "synthetic" not in json.dumps(_props(telemetry_popen))


def test_a_failed_command_also_sends_an_exception_event_without_paths_or_message(
    telemetry_popen: MagicMock,
    stubbed_cli: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = str(Path.home())
    failure = ValueError(f"cannot read {home}/secret.md")

    with (
        patch("llm_prompts.install.main", side_effect=failure),
        contextlib.suppress(ValueError),
    ):
        _main("update")
    monkeypatch.setattr("llm_prompts.cli._get_installed_commit", lambda _: A)

    raised = next(e for e in _events(telemetry_popen) if e["event"] == "$exception")
    (item,) = raised["properties"]["$exception_list"]
    assert item["type"] == "ValueError"
    frames = item["stacktrace"]["frames"]
    assert frames
    assert {f["module"] for f in frames} <= {
        m for m in sys.modules if m.startswith("llm_prompts")
    }
    assert all(set(f) == {"filename", "module", "function", "lineno"} for f in frames)
    assert "llm_prompts/cli.py" in {f["filename"] for f in frames}
    assert not any(Path(f["filename"]).is_absolute() for f in frames)
    assert raised["properties"]["command"] == "update"
    assert raised["properties"]["llm_prompts_commit"]["commit"] == A
    sent = json.dumps(_events(telemetry_popen))
    assert home not in sent
    assert "secret.md" not in sent
    assert "cannot read" not in sent


@pytest.mark.usefixtures("stubbed_cli")
@pytest.mark.parametrize(
    "quiet", [SystemExit(0), SystemExit(None), SystemExit(1), KeyboardInterrupt()]
)
def test_an_exit_or_interrupt_sends_no_exception_event(
    telemetry_popen: MagicMock, quiet: BaseException
) -> None:
    with (
        patch("llm_prompts.install.main", side_effect=quiet),
        contextlib.suppress(BaseException),
    ):
        _main("update")

    assert "$exception" not in [e["event"] for e in _events(telemetry_popen)]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (["update"], ["update"]),
        (["install", "kiro"], ["install", "kiro", "--no-update"]),
    ],
)
def test_a_command_that_continues_in_a_new_process_reports_once_from_the_last(
    telemetry_popen: MagicMock,
    stubbed_cli: MagicMock,
    first: list[str],
    second: list[str],
) -> None:
    installed = {"commit": A}

    def upgrade(*_: Any, **__: Any) -> bool:
        installed["commit"] = B
        return True

    def restart(*_: Any, env: dict[str, str] | None = None, **__: Any) -> None:
        os.environ.update(env or {})
        raise SystemExit

    stubbed_cli.side_effect = upgrade
    with (
        patch("llm_prompts.cli._get_installed_commit", lambda _: installed["commit"]),
        patch("os.execvp", side_effect=restart),
        patch("subprocess.run", side_effect=restart),
        patch.dict("os.environ"),
    ):
        _main(*first)
        telemetry_popen.assert_not_called()
        stubbed_cli.side_effect = None
        stubbed_cli.return_value = False
        _main(*second)

        assert telemetry_popen.call_count == 1
        assert _from_to(telemetry_popen) == (A, B)


def test_the_parent_never_looks_up_versions_unless_the_command_installs(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    lookups = MagicMock(return_value=A)
    with telemetry.Run(lookups) as run:
        run.begin("startup-check", [])
    lookups.assert_not_called()

    monkeypatch.setattr("llm_prompts.cli._get_installed_commit", lambda _: B)
    posted = MagicMock()
    monkeypatch.setattr("llm_prompts.telemetry.post", posted)
    telemetry.deliver(telemetry_popen.call_args.args[0][3])
    properties = json.loads(posted.call_args.args[0])["properties"]
    assert properties["from"]["llm-prompts"]["commit"] == B
    assert properties["to"]["llm-prompts"]["commit"] == B


def test_an_installing_command_captures_from_before_it_runs(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = {"commit": A}
    with telemetry.Run(lambda _: installed["commit"]) as run:
        run.begin("update", [], installs=True)
        installed["commit"] = B

    monkeypatch.setattr("llm_prompts.cli._get_installed_commit", lambda _: B)
    posted = MagicMock()
    monkeypatch.setattr("llm_prompts.telemetry.post", posted)
    telemetry.deliver(telemetry_popen.call_args.args[0][3])
    properties = json.loads(posted.call_args.args[0])["properties"]
    assert properties["from"]["llm-prompts"]["commit"] == A
    assert properties["to"]["llm-prompts"]["commit"] == B
