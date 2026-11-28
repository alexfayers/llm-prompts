"""Tests for anonymous usage telemetry."""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest
import truststore
from conftest import FakeSubprocess, run_capturing_exit, spooled_events

from llm_prompts import (
    cli,
    github_api,
    install,
    mcp,
    setup,
    telemetry,
    telemetry_core,
)
from llm_prompts.cli import _pull_local_sources
from llm_prompts.exit_reason import REASONS, ExitReason, Reason

A, B = "a" * 40, "b" * 40
EVENT: dict[str, Any] = {"event": "command_run", "properties": {}}
OPT_OUTS = ("DO_NOT_TRACK", "LLM_PROMPTS_NO_TELEMETRY", "CI")


def _props(popen: MagicMock) -> dict[str, Any]:
    properties: dict[str, Any] = _events(popen)[0]["properties"]
    return properties


def _events(popen: MagicMock) -> list[dict[str, Any]]:
    """Return the sent events, with placeholders resolved as the detached sender does."""
    return [
        json.loads(telemetry_core.resolve_versions(json.dumps(event)))
        for event in spooled_events(popen)
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

    with patch("llm_prompts.telemetry_core.read_config", return_value=config):
        assert telemetry_core.enabled() is expected


def test_event_carries_only_allowlisted_properties(
    telemetry_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    fake_subprocess: FakeSubprocess,
) -> None:
    tools = [
        {"name": "cline-hooks", "source": "/synthetic/hooks"},
        {"name": "acme-secret-overlay", "source": "~/synthetic/overlay"},
        {"name": "acme-internal", "source": "git+ssh://git.internal.example/acme"},
        {"name": "pub-overlay", "source": "git+https://github.com/acme/pub.git"},
        {"name": "local-pub", "source": "~/synthetic/pub"},
    ]
    monkeypatch.setattr("llm_prompts.telemetry.read_config", lambda: {"tools": tools})
    monkeypatch.setattr("llm_prompts.telemetry_core.run", fake_subprocess.run)
    fake_subprocess.on("status", returncode=128)

    monkeypatch.setattr("llm_prompts.cli._get_installed_version", lambda _: (A, None))
    with telemetry.Run(lambda _: (A, "v0.4.0")) as run:
        run.begin("update", [], installs=True)

    posted = MagicMock()
    monkeypatch.setattr("llm_prompts.telemetry_core.post", posted)
    telemetry_core.flush()
    properties = json.loads(posted.call_args.args[0])["properties"]
    assert set(properties) == {
        *("command", "from", "to", "agents", "overlay_count", "overlays", "outcome"),
        *("exit_reason", "auto_update"),
        "run_id",
        *("flags", "duration_s", "os", "python", "schema", "$process_person_profile"),
    }
    assert properties["from"]["cline-hooks"] == {
        "commit": None,
        "base": None,
        "local": True,
        "dirty": None,
        "ahead": None,
        "release": None,
    }
    assert properties["from"]["llm-prompts"] == {
        "commit": A,
        "base": A,
        "local": False,
        "dirty": False,
        "ahead": None,
        "release": "v0.4.0",
    }
    assert properties["overlay_count"] == 4
    assert properties["overlays"] == {
        "pub-overlay": {
            "commit": A,
            "base": A,
            "local": False,
            "dirty": False,
            "ahead": None,
            "release": None,
        }
    }
    assert properties["schema"] == 2
    assert "acme-internal" not in json.dumps(properties)
    assert "acme-secret" not in json.dumps(properties)
    assert "synthetic" not in json.dumps(properties)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.mark.real_io
def test_a_git_checkout_source_reports_its_base_on_origin_main_and_whether_it_is_dirty(
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
    base = _git(repo, "rev-parse", "HEAD")
    for tag in ("v0.9.0", "v0.10.0", "v1.0.0-rc1"):
        _git(repo, "tag", tag)
    commit = ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q")
    _git(repo, *commit, "--allow-empty", "-m", "y")
    _git(repo, "tag", "v2.0.0")
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
            patch("llm_prompts.telemetry_core.run", side_effect=AssertionError),
            telemetry.Run(lambda _: (A, None)) as run,
        ):
            run.begin("update", [])
        posted = MagicMock()
        monkeypatch.setattr("llm_prompts.telemetry_core.post", posted)
        telemetry_core.flush()
        sent = json.loads(posted.call_args.args[0])["properties"]
        telemetry_popen.reset_mock()
        expected = {
            "commit": None,
            "base": base,
            "local": True,
            "dirty": dirty,
            "ahead": 1,
            "release": "v0.10.0",
        }
        assert sent["from"]["cline-hooks"] == expected
        assert sent["to"]["cline-hooks"] == expected
        assert sent["from"]["mcp-memory"] == {
            "commit": None,
            "base": None,
            "local": True,
            "dirty": None,
            "ahead": None,
            "release": None,
        }
        assert str(tmp_path) not in posted.call_args.args[0]
        assert head not in posted.call_args.args[0]


@pytest.mark.real_io
def test_a_checkout_without_origin_main_names_no_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    identity = ("-c", "user.name=t", "-c", "user.email=t@t")
    _git(tmp_path, *identity, "commit", "-q", "--allow-empty", "-m", "x")
    (tmp_path / "f").write_text("x")

    state = telemetry_core._checkout_state(str(tmp_path))

    assert state == {
        "commit": None,
        "base": None,
        "local": True,
        "dirty": True,
        "ahead": None,
        "release": None,
    }


def test_post_verifies_certificates_with_the_system_trust_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urlopen = MagicMock()
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    assert telemetry_core.post("{}") is True

    assert isinstance(urlopen.call_args.kwargs["context"], truststore.SSLContext)


@pytest.mark.usefixtures("telemetry_popen")
def test_debug_mode_shows_why_a_post_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    telemetry_core.save_opt_state()
    monkeypatch.setenv("LLM_PROMPTS_TELEMETRY_DEBUG", "1")
    monkeypatch.setattr(
        "urllib.request.urlopen", MagicMock(side_effect=URLError("no cert"))
    )

    telemetry_core.send(EVENT, "id-1")

    err = capsys.readouterr().err
    assert "telemetry sent: False" in err
    assert "no cert" in err


@pytest.mark.parametrize("debug", ["0", "1"])
def test_send_spawns_a_detached_sender_unless_debugging(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch, debug: str
) -> None:
    telemetry_core.save_opt_state()
    urlopen = MagicMock(side_effect=URLError("offline"))
    monkeypatch.setenv("LLM_PROMPTS_TELEMETRY_DEBUG", debug)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    telemetry_core.send(EVENT, "id-1")

    assert urlopen.called is (debug == "1")
    assert telemetry_popen.called is (debug == "0")
    if debug == "0":
        kwargs = telemetry_popen.call_args.kwargs
        assert kwargs["start_new_session"] is True
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert not [n for n in kwargs["env"] if n.startswith("LLM_PROMPTS_")]


def test_the_parent_never_waits_on_the_sender(telemetry_popen: MagicMock) -> None:
    telemetry_core.send(EVENT, "id-1")

    assert telemetry_popen.return_value.mock_calls == []


@pytest.mark.parametrize("saved", ["{}", "[]", "not json"])
def test_an_unreadable_install_id_is_a_first_run_that_sends_nothing(
    telemetry_popen: MagicMock, isolated_config_dir: Any, saved: str
) -> None:
    (isolated_config_dir / "telemetry.json").write_text(saved, encoding="utf-8")

    for expected_sends in (0, 1):
        with telemetry.Run(lambda _: (A, None)) as run:
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

    with telemetry.Run(lambda _: (A, None)) as run:
        run.begin("update", [])

    telemetry_popen.assert_not_called()
    assert telemetry.RESUME_ENV not in os.environ


def test_a_resume_state_without_releases_still_sends_its_from_commits(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"commits": dict.fromkeys(telemetry_core.TRACKED, A)}
    monkeypatch.setenv(telemetry.RESUME_ENV, json.dumps(state))

    with telemetry.Run(lambda _: (B, "v9.9.9")) as run:
        run.begin("update", [], installs=True)

    assert _props(telemetry_popen)["from"]["llm-prompts"]["commit"] == A
    assert _props(telemetry_popen)["from"]["llm-prompts"]["release"] is None


def test_an_install_with_no_agents_sends_nothing_and_leaves_no_trace(
    telemetry_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    isolated_config_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("llm_prompts.telemetry.read_manifest", dict)
    state = isolated_config_dir / "telemetry.json"
    state.unlink()

    with pytest.raises(ValueError), telemetry.Run(lambda _: (A, None)) as run:
        run.begin("update", [])
        raise ValueError

    telemetry_popen.assert_not_called()
    assert not state.exists()
    assert capsys.readouterr().err == ""


@pytest.mark.usefixtures("stubbed_cli")
def test_a_rooted_install_sends_nothing_and_leaves_no_trace(
    telemetry_popen: MagicMock,
    isolated_config_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = isolated_config_dir / "telemetry.json"
    state.unlink()

    _main("install", "kiro", "--root=/synthetic/root", "--no-update")

    telemetry_popen.assert_not_called()
    assert not state.exists()
    assert "telemetry" not in capsys.readouterr().err


def test_a_failing_report_sends_nothing_and_keeps_the_command_result(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "llm_prompts.telemetry.read_manifest", MagicMock(side_effect=KeyError)
    )

    with telemetry.Run(lambda _: (A, None)) as run:
        run.begin("update", [])

    telemetry_popen.assert_not_called()


@pytest.fixture
def stubbed_cli(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub everything the commands touch outside telemetry."""
    for target in (
        "llm_prompts.cli._pull_local_sources",
        "llm_prompts.cli._check_for_updates",
        "llm_prompts.cli._print_update_status",
        "llm_prompts.cli._reconfigure_agents",
        "llm_prompts.plugins.pull_plugin_sources",
        "llm_prompts.setup.detect_stale_local_tools",
        "llm_prompts.setup.detect_changed_configured_tools",
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
        (["update"], "size_guard_failed", "size_guard_failed"),
        (["update"], "pi_package_failed", "pi_package_failed"),
        (["update"], "install_failed", "install_failed"),
        (["update"], ValueError("secret"), "error:ValueError"),
        (["setup"], False, "ok"),
        (["install", "kiro", "--no-update"], False, "ok"),
        (["install", "kiro"], False, None),
        (["update", "--check"], False, "ok"),
        (["update", "--only", "/synthetic/rule.md"], False, "ok"),
        (["setup", "--dry-run"], False, "ok"),
        (["check"], False, "ok"),
        (
            ["update", "--only", "/synthetic/rule.md"],
            "size_guard_failed",
            "size_guard_failed",
        ),
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
    _main(
        "install", "kiro", "--agent-config=/synthetic/agent.json", "--no-update", "-v"
    )

    flags = _props(telemetry_popen)["flags"]
    assert flags == ["--agent-config", "--no-update", "-v"]
    assert "synthetic" not in json.dumps(_props(telemetry_popen))


@pytest.mark.usefixtures("stubbed_cli")
def test_an_automatic_update_is_marked_in_its_event(telemetry_popen: MagicMock) -> None:
    with contextlib.suppress(SystemExit):
        _main("update", "--auto")

    assert _props(telemetry_popen)["flags"] == ["--auto"]


def test_a_failed_command_also_sends_an_exception_event_without_paths(
    telemetry_popen: MagicMock,
    stubbed_cli: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = str(Path.home())
    failure = _own(ValueError)(f"cannot read {home}/secret.md")

    with (
        patch("llm_prompts.install.main", side_effect=failure),
        contextlib.suppress(ValueError),
    ):
        _main("update")
    monkeypatch.setattr("llm_prompts.cli._get_installed_version", lambda _: (A, None))

    raised = next(e for e in _events(telemetry_popen) if e["event"] == "$exception")
    (item,) = raised["properties"]["$exception_list"]
    assert item["type"] == "OwnError"
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
    assert raised["properties"]["llm_prompts_commit"]["base"] == A
    command = next(e for e in _events(telemetry_popen) if e["event"] == "command_run")
    assert raised["properties"]["versions"] == command["properties"]["to"]
    assert {"llm-prompts", "cline-hooks", "mcp-memory"} <= set(
        raised["properties"]["versions"]
    )
    sent = json.dumps(_events(telemetry_popen))
    assert home not in sent
    assert "secret.md" not in sent
    assert item["value"].startswith("cannot read ")


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


@pytest.mark.usefixtures("stubbed_cli")
def test_an_interrupt_sends_no_event(telemetry_popen: MagicMock) -> None:
    with (
        patch("llm_prompts.install.main", side_effect=KeyboardInterrupt()),
        contextlib.suppress(KeyboardInterrupt),
    ):
        _main("update")

    assert _events(telemetry_popen) == []


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
        patch(
            "llm_prompts.cli._get_installed_version",
            lambda _: (installed["commit"], None),
        ),
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
    lookups = MagicMock(return_value=(A, None))
    with telemetry.Run(lookups) as run:
        run.begin("startup-check", [])
    lookups.assert_not_called()

    monkeypatch.setattr("llm_prompts.cli._get_installed_version", lambda _: (B, None))
    posted = MagicMock()
    monkeypatch.setattr("llm_prompts.telemetry_core.post", posted)
    telemetry_core.flush()
    properties = json.loads(posted.call_args.args[0])["properties"]
    assert properties["from"]["llm-prompts"]["commit"] == B
    assert properties["to"]["llm-prompts"]["commit"] == B


def test_an_installing_command_captures_from_before_it_runs(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = {"commit": A}
    with telemetry.Run(lambda _: (installed["commit"], None)) as run:
        run.begin("update", [], installs=True)
        installed["commit"] = B

    monkeypatch.setattr("llm_prompts.cli._get_installed_version", lambda _: (B, None))
    posted = MagicMock()
    monkeypatch.setattr("llm_prompts.telemetry_core.post", posted)
    telemetry_core.flush()
    properties = json.loads(posted.call_args.args[0])["properties"]
    assert properties["from"]["llm-prompts"]["commit"] == A
    assert properties["to"]["llm-prompts"]["commit"] == B


@pytest.mark.usefixtures("stubbed_cli")
@pytest.mark.parametrize(
    ("argv", "outcome"),
    [(["check"], "check_failed"), (["contribute", "list"], "usage_error")],
)
def test_a_failed_gate_or_usage_error_is_not_reported_as_an_error(
    telemetry_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    outcome: str,
) -> None:
    monkeypatch.setattr(
        "llm_prompts.size_guard.check",
        lambda _: MagicMock(passed=False, report=""),
    )
    monkeypatch.setattr("llm_prompts.setup._load_config", list)

    assert _main(*argv) == 1

    assert telemetry_popen.call_count == 1
    assert _props(telemetry_popen)["outcome"] == outcome


@pytest.mark.usefixtures("stubbed_cli")
@pytest.mark.parametrize(
    ("argv", "tools", "reason"),
    [
        (["contribute", "list"], [], "no_contribute_targets"),
        (["contribute", "list", "--tool", "x"], [], "tool_not_configured"),
        (
            ["contribute", "list", "--tool", "x"],
            [{"name": "x", "source": "git+https://example.com/x"}],
            "tool_not_local",
        ),
        (["contribute", "list", "--tool", "x"], "no_prompts", "no_prompts_dir"),
    ],
)
def test_an_early_exit_reports_a_fixed_reason_code(
    telemetry_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    argv: list[str],
    tools: Any,
    reason: str,
) -> None:
    if tools == "no_prompts":
        tools = [{"name": "x", "source": str(tmp_path)}]
    monkeypatch.setattr("llm_prompts.setup._load_config", lambda: tools)

    assert _main(*argv) == 1

    assert _props(telemetry_popen)["exit_reason"] == reason
    assert reason in REASONS


@pytest.mark.parametrize(
    ("reason", "config", "call"),
    [
        ("uv_missing", {}, setup._require_uv),
        ("config_missing", None, setup._load_config),
        ("config_no_tools", {}, setup._load_config),
        ("config_exists", {}, setup.init_config),
        (
            "invalid_tool_paths",
            {"tools": [{"name": "x", "source": "/synthetic/x"}]},
            setup.run_setup,
        ),
        ("tool_install_failed", {}, lambda: setup._run_install(MagicMock())),
        (
            "agent_config_missing",
            {},
            lambda: install.patch_kiro_agent_config("/synthetic/x"),
        ),
    ],
)
def test_setup_and_install_exits_carry_a_fixed_reason_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reason: str,
    config: dict[str, Any] | None,
    call: Callable[[], object],
) -> None:
    config_file = tmp_path / "config.toml"
    if config is not None:
        config_file.touch()
    monkeypatch.setattr("llm_prompts.setup.config_path", lambda: config_file)
    monkeypatch.setattr("llm_prompts.setup.read_config", lambda: config)
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr("subprocess.run", lambda *_, **__: MagicMock(returncode=1))

    with pytest.raises(ExitReason) as raised:
        call()

    assert raised.value.reason == reason
    assert reason in REASONS


@pytest.mark.usefixtures("stubbed_cli")
@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (None, None),
        (SystemExit(0), None),
        (SystemExit(1), "other"),
        (SystemExit("free text with /a/path"), "other"),
        (ExitReason("no_push_access", "free text with /a/path"), "no_push_access"),
    ],
)
def test_only_a_fixed_reason_code_is_sent_for_an_exit(
    telemetry_popen: MagicMock, failure: BaseException | None, reason: str | None
) -> None:
    with patch("llm_prompts.install.main", side_effect=[failure or False]):
        _main("update")

    assert _props(telemetry_popen)["exit_reason"] == reason
    assert "free text" not in json.dumps(_events(telemetry_popen))


@pytest.mark.usefixtures("stubbed_cli")
@pytest.mark.parametrize(
    ("reason", "outcome"),
    [
        ("record_locked", "stopped"),
        ("copy_blocked", "stopped"),
    ],
)
def test_a_designed_stop_is_not_reported_as_an_error(
    telemetry_popen: MagicMock, reason: Reason, outcome: str
) -> None:
    with patch("llm_prompts.install.main", side_effect=[ExitReason(reason)]):
        _main("update")

    assert _props(telemetry_popen)["outcome"] == outcome
    assert _props(telemetry_popen)["exit_reason"] == reason


@pytest.mark.usefixtures("stubbed_cli")
def test_an_update_with_only_removed_agents_reports_no_installed_agents(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_prompts.manifest.read_manifest", lambda: {"cline": {}})
    monkeypatch.setattr("llm_prompts.telemetry.read_manifest", lambda: {"cline": {}})

    _main("update")

    assert _props(telemetry_popen)["exit_reason"] == "no_installed_agents"


def _own(error: type[Exception]) -> type[Exception]:
    """Return a subclass of `error` that looks defined in llm_prompts."""
    return type("OwnError", (error,), {"__module__": "llm_prompts.synthetic"})


def _failing_update(failure: BaseException | Callable[..., object]) -> None:
    with (
        patch("llm_prompts.install.main", side_effect=failure),
        contextlib.suppress(Exception),
    ):
        _main("update")


def _error(cause: BaseException | None = None, *, hide: bool = False) -> ValueError:
    error = ValueError()
    error.__context__ = cause
    error.__suppress_context__ = hide
    return error


@pytest.mark.usefixtures("stubbed_cli")
@pytest.mark.parametrize(
    ("failure", "listed", "service"),
    [
        (lambda *_, **__: mcp._post("http://x", "x", {}, {}), 1, "mcp"),
        (lambda *_, **__: github_api.request("GET", "/x"), 2, "github"),
        (lambda *_, **__: mcp.pi_tool_name(None), 1, None),  # type: ignore[arg-type]
        (_error(_error(_error(_error(_error(_error()))))), 4, None),
        (_error(_error()), 2, None),
        (_error(_error(), hide=True), 1, None),
    ],
)
def test_an_exception_event_repeats_the_run_context_lists_causes_and_names_a_service(
    telemetry_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException | Callable[..., object],
    listed: int,
    service: str | None,
) -> None:
    offline = MagicMock(side_effect=URLError("down"))
    monkeypatch.setattr("llm_prompts.mcp.urlopen", offline)
    monkeypatch.setattr("llm_prompts.github_api.urlopen", offline)
    monkeypatch.setattr("llm_prompts.github_api.token", lambda: "synthetic-token")

    _failing_update(failure)

    ran, raised = (e["properties"] for e in _events(telemetry_popen))
    assert re.fullmatch(r"[0-9a-f]{12}", raised["run_id"])
    context = telemetry._EXCEPTION_CONTEXT
    assert {k: raised[k] for k in context} == {k: ran[k] for k in context}
    assert len(raised["$exception_list"]) == listed
    assert raised["dependency"] == service


@pytest.mark.usefixtures("stubbed_cli")
@pytest.mark.parametrize(
    ("failure", "value"),
    [
        (
            _own(json.JSONDecodeError)("Expecting value", "", 0),
            "Expecting value: line 1",
        ),
        (_own(http.client.IncompleteRead)(b"abc", 5), "OwnError(3 bytes read"),
        (_own(json.JSONDecodeError)("word " * 100, "", 0), "word word"),
        (_own(ValueError)("plain message"), "plain message"),
    ],
)
def test_our_exception_types_send_a_capped_scrubbed_message(
    telemetry_popen: MagicMock, failure: BaseException, value: str
) -> None:
    _failing_update(failure)

    sent = _events(telemetry_popen)[1]["properties"]["$exception_list"][0]["value"]
    assert value in sent
    assert len(sent) <= telemetry_core._MAX_MESSAGE_LENGTH


@pytest.mark.usefixtures("stubbed_cli")
def test_a_sent_message_never_carries_local_values_or_generic_identifiers(
    telemetry_popen: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = str(Path.home())
    generic = (
        f"{home}/notes.md /srv/data.json C:\\Users\\x\\a.txt "
        "https://host.example/p?t=a a@b.example 203.0.113.7 2001:db8::1 "
        "deadbeefdeadbeefdeadbeef 4111111111111111"
    )
    monkeypatch.setenv("SYNTHETIC_SECRET", "plain-env-secret")
    monkeypatch.setattr(
        "llm_prompts.telemetry.read_config",
        lambda: {"tools": [{"source": "plain-config-value"}]},
    )
    known = f"plain-env-secret {platform.node()} plain-config-value"

    _failing_update(_own(json.JSONDecodeError)(f"{generic} {known}", "", 0))

    value = _events(telemetry_popen)[1]["properties"]["$exception_list"][0].get("value")
    for leak in [*generic.split(), *known.split(), home]:
        assert leak not in value


@pytest.mark.real_io
def test_an_opted_out_run_skips_the_network_modules() -> None:
    check = (
        "import sys; from llm_prompts import telemetry\n"
        "with telemetry.Run(lambda _: (None, None)) as run: run.begin('x', [])\n"
        "print(sorted({'ssl', 'truststore'} & set(sys.modules)))"
    )
    env = {**os.environ, "LLM_PROMPTS_NO_TELEMETRY": "1"}
    completed = subprocess.run(
        [sys.executable, "-c", check],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert completed.stdout.strip() == "[]"


SESSION = {
    "role": "writer",
    "model": "acme-proxy/claude-opus-4-1",
    "calls": 4,
    "cost": 0.5,
    "context": 40000,
    "peak": 16000,
    "cacheRead": 30000,
    "compactions": 1,
    "wallMs": 90500,
    "inferenceMs": 40000,
    "commandMs": 30000,
    "userMs": 15000,
}


def _fresh_record(isolated_config_dir: Path) -> None:
    record = {"install_id": "synthetic-id", "opted_out": False, "at": time.time()}
    (isolated_config_dir / "telemetry.json").write_text(json.dumps(record))


def test_a_spooled_pi_session_posts_its_numbers_under_its_own_id_and_time(
    telemetry_popen: MagicMock,
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_record(isolated_config_dir)
    posted = MagicMock(return_value=True)
    monkeypatch.setattr("llm_prompts.telemetry_core.post", posted)
    monkeypatch.setattr("llm_prompts.cli._get_installed_version", lambda _: (A, None))
    spool = telemetry_core.spool_dir()
    spool.mkdir()
    entry = {
        "kind": "pi-stats",
        "at": 1_700_000_000_000,
        "uuid": "u-1",
        "stats": SESSION,
    }
    (spool / f"{time.time_ns()}-u-1.json").write_text(json.dumps(entry))

    _main("session-telemetry")

    event = json.loads(posted.call_args.args[0])
    assert (event["event"], event["uuid"]) == ("pi_session", "u-1")
    assert event["timestamp"] == "2023-11-14T22:13:20+00:00"
    assert event["properties"]["role"] == "writer"
    assert event["properties"]["llm_prompts"]["commit"] == A
    assert not list(spool.iterdir())
    telemetry_popen.assert_not_called()


@pytest.mark.parametrize(
    ("role", "model", "tier"),
    [
        ("writer", "acme-proxy/claude-opus-4-1", "opus"),
        ("main", "anthropic/claude-sonnet-4-5", "sonnet"),
        ("acme-team-role", "acme-internal/secret-model", "other"),
    ],
)
def test_a_pi_session_sends_only_its_numbers_role_tier_and_version(
    telemetry_popen: MagicMock,
    isolated_config_dir: Path,
    role: str,
    model: str,
    tier: str,
) -> None:
    _fresh_record(isolated_config_dir)

    _main("session-telemetry", json.dumps({**SESSION, "role": role, "model": model}))

    [event] = _events(telemetry_popen)
    properties = event["properties"]
    assert event["event"] == "pi_session"
    assert set(properties) == {
        *("role", "model_tier", "calls", "cost", "cost_per_call", "context_avg"),
        *("context_peak", "cache_read_share", "compactions", "wall_s"),
        *("inference_s", "command_wait_s", "user_wait_s"),
        *("inference_share", "command_wait_share", "user_wait_share"),
        *("llm_prompts", "cline_hooks", "mcp_memory"),
        *("os", "python", "schema", "$process_person_profile"),
    }
    assert properties["role"] == (role if role != "acme-team-role" else "other")
    assert properties["model_tier"] == tier
    assert (properties["calls"], properties["cost"]) == (4, 0.5)
    assert (properties["cost_per_call"], properties["context_avg"]) == (0.125, 10000)
    assert (properties["context_peak"], properties["cache_read_share"]) == (16000, 0.75)
    assert (properties["compactions"], properties["wall_s"]) == (1, 90.5)
    waits = ("inference_s", "command_wait_s", "user_wait_s")
    assert [properties[k] for k in waits] == [40.0, 30.0, 15.0]
    shares = ("inference_share", "command_wait_share", "user_wait_share")
    assert [properties[k] for k in shares] == [0.442, 0.331, 0.166]
    for tool in ("llm_prompts", "cline_hooks", "mcp_memory"):
        assert set(properties[tool]) >= {"commit", "release"}
    assert "acme" not in json.dumps(properties)


@pytest.mark.parametrize("time_to_pr", [125, None])
def test_an_opened_pr_sends_only_its_time_role_tier_and_version(
    telemetry_popen: MagicMock,
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    time_to_pr: int | None,
) -> None:
    _fresh_record(isolated_config_dir)
    started = "" if time_to_pr is None else str(int((time.time() - time_to_pr) * 1000))
    monkeypatch.setenv(telemetry.SESSION_START_ENV, started)
    monkeypatch.setenv("PI_CONTEXT_ROLE", "writer")
    monkeypatch.setenv("PI_MODEL", "acme-claude-sonnet-4-5")

    _main("session-telemetry", json.dumps({"event": "pr_opened"}))

    [event] = _events(telemetry_popen)
    properties = event["properties"]
    assert event["event"] == "pr_opened"
    assert set(properties) == {
        *("role", "model_tier", "time_to_pr_s"),
        *("llm_prompts", "cline_hooks", "mcp_memory"),
        *("os", "python", "schema", "$process_person_profile"),
    }
    assert (properties["role"], properties["model_tier"]) == ("writer", "sonnet")
    assert properties["time_to_pr_s"] == pytest.approx(time_to_pr, abs=5)
    assert "acme" not in json.dumps(properties)


@pytest.mark.parametrize("opt_out", ["DO_NOT_TRACK", "stale"])
def test_an_opted_out_pi_session_sends_nothing(
    telemetry_popen: MagicMock,
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    opt_out: str,
) -> None:
    if opt_out == "stale":
        record = {"install_id": "synthetic-id", "opted_out": False, "at": 0}
        (isolated_config_dir / "telemetry.json").write_text(json.dumps(record))
    else:
        _fresh_record(isolated_config_dir)
        monkeypatch.setenv(opt_out, "1")

    _main("session-telemetry", json.dumps(SESSION))
    _main("session-telemetry", json.dumps({"event": "pr_opened"}))
    telemetry.send_pr_review(rounds=1, clean=True, deferred=0)

    assert not telemetry_popen.called


@pytest.mark.usefixtures("stubbed_cli")
@pytest.mark.parametrize(
    ("route", "behind", "reason"),
    [
        (("fetch",), "0", "source_fetch_failed"),
        (("merge", "--ff-only"), "1", "source_merge_failed"),
    ],
)
def test_a_source_sync_stop_sends_the_fixed_code_of_its_cause(
    telemetry_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    route: tuple[str, ...],
    behind: str,
    reason: str,
) -> None:
    clone = tmp_path / "acme-clone"
    (clone / ".git").mkdir(parents=True)
    fake = FakeSubprocess()
    fake.on(*route, side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30))
    fake.on("rev-list", "--count", stdout=f"{behind}\n")
    monkeypatch.setattr("subprocess.run", fake.run)
    monkeypatch.setattr("llm_prompts.cli._pull_local_sources", _pull_local_sources)
    monkeypatch.setenv("LLM_PROMPTS_CONTRIBUTE_RECORD", str(tmp_path / "record.json"))
    monkeypatch.setattr(
        "llm_prompts.setup._load_config",
        lambda *_: [{"name": "core", "source": str(clone), "ref": "acme-branch"}],
    )

    assert _main("update") == 1

    assert _props(telemetry_popen)["outcome"] == "source_sync_failed"
    assert _props(telemetry_popen)["exit_reason"] == reason
    assert reason in REASONS
    assert "acme" not in json.dumps(_events(telemetry_popen))
