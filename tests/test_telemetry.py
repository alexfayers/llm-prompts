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
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest
import truststore
from conftest import FakeSubprocess, run_capturing_exit

from llm_prompts import cli, github_api, mcp, telemetry

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
    monkeypatch.setattr("llm_prompts.telemetry.run", fake_subprocess.run)
    fake_subprocess.on("status", returncode=128)

    monkeypatch.setattr("llm_prompts.cli._get_installed_commit", lambda _: A)
    with telemetry.Run(lambda _: A) as run:
        run.begin("update", [], installs=True)

    posted = MagicMock()
    monkeypatch.setattr("llm_prompts.telemetry.post", posted)
    telemetry.deliver(telemetry_popen.call_args.args[0][3])
    properties = json.loads(posted.call_args.args[0])["properties"]
    assert set(properties) == {
        *("command", "from", "to", "agents", "overlay_count", "overlays", "outcome"),
        "run_id",
        *("flags", "duration_s", "os", "python", "schema", "$process_person_profile"),
    }
    assert properties["from"]["cline-hooks"] == {
        "commit": None,
        "base": None,
        "local": True,
        "dirty": None,
        "ahead": None,
    }
    assert properties["from"]["llm-prompts"] == {
        "commit": A,
        "base": A,
        "local": False,
        "dirty": False,
        "ahead": None,
    }
    assert properties["overlay_count"] == 4
    assert properties["overlays"] == {
        "pub-overlay": {
            "commit": A,
            "base": A,
            "local": False,
            "dirty": False,
            "ahead": None,
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
        expected = {
            "commit": None,
            "base": base,
            "local": True,
            "dirty": dirty,
            "ahead": 1,
        }
        assert sent["from"]["cline-hooks"] == expected
        assert sent["to"]["cline-hooks"] == expected
        assert sent["from"]["mcp-memory"] == {
            "commit": None,
            "base": None,
            "local": True,
            "dirty": None,
            "ahead": None,
        }
        assert str(tmp_path) not in posted.call_args.args[0]
        assert head not in posted.call_args.args[0]


@pytest.mark.real_io
def test_a_checkout_without_origin_main_names_no_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    identity = ("-c", "user.name=t", "-c", "user.email=t@t")
    _git(tmp_path, *identity, "commit", "-q", "--allow-empty", "-m", "x")
    (tmp_path / "f").write_text("x")

    state = telemetry._checkout_state(str(tmp_path))

    assert state == {
        "commit": None,
        "base": None,
        "local": True,
        "dirty": True,
        "ahead": None,
    }


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
        (["update", "--only", "/synthetic/rule.md"], True, "size_guard_failed"),
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
    assert raised["properties"]["llm_prompts_commit"]["base"] == A
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
        (json.JSONDecodeError("Expecting value", "", 0), "Expecting value: line 1"),
        (http.client.IncompleteRead(b"abc", 5), "IncompleteRead(3 bytes read"),
        (subprocess.CalledProcessError(2, ["synthetic-tool"]), "exit status 2"),
        (json.JSONDecodeError("word " * 100, "", 0), "word word"),
        (ValueError("plain message"), None),
    ],
)
def test_only_exception_types_with_known_formats_send_a_capped_message(
    telemetry_popen: MagicMock, failure: BaseException, value: str | None
) -> None:
    _failing_update(failure)

    sent = _events(telemetry_popen)[1]["properties"]["$exception_list"][0].get("value")
    assert (sent is None) == (value is None)
    assert value is None or value in str(sent)
    assert len(sent or "") <= telemetry._MAX_MESSAGE_LENGTH
    assert "synthetic-tool" not in json.dumps(_events(telemetry_popen))


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

    _failing_update(json.JSONDecodeError(f"{generic} {known}", "", 0))

    value = _events(telemetry_popen)[1]["properties"]["$exception_list"][0].get("value")
    for leak in [*generic.split(), *known.split(), home]:
        assert leak not in value
