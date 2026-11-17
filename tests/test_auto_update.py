"""Tests for the automatic update at session start."""

import fcntl
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import FakeSubprocess, run_capturing_exit

from llm_prompts import auto_update, cli, plugins
from llm_prompts.main_sync import point_upstream


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _checkout(tmp_path: Path) -> Path:
    """Return a clone of a remote whose release tag the clone's main sits on."""
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q", "-b", "main")
    _git(remote, "commit", "-q", "--allow-empty", "-m", "base")
    _git(remote, "tag", "v0.1.0")
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True
    )
    point_upstream(clone)
    return clone


def _config(config_dir: Path, source: Path, extra: str = "") -> None:
    (config_dir / "config.toml").write_text(
        f'{extra}[[tools]]\nname = "llm-prompts"\nsource = "{source}"\n',
        encoding="utf-8",
    )


def test_a_running_fork_blocks(
    tmp_path: Path, isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(isolated_config_dir, Path("git+https://example.invalid/x.git"))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
    run = tmp_path / "agent" / "pi-context" / "run"
    run.mkdir(parents=True)
    (run / "handshake.json").write_text("{}", encoding="utf-8")
    assert auto_update.blocker("") == "a pi fork is running"
    (run / "finished").write_text("", encoding="utf-8")
    assert auto_update.blocker("") is None


def test_a_stale_fork_run_does_not_block(
    tmp_path: Path, isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(isolated_config_dir, Path("git+https://example.invalid/x.git"))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
    run = tmp_path / "agent" / "pi-context" / "run"
    run.mkdir(parents=True)
    handshake = run / "handshake.json"
    handshake.write_text("{}", encoding="utf-8")
    old = time.time() - auto_update.FORK_IDLE_SECONDS - 1
    os.utime(handshake, (old, old))
    assert auto_update.blocker("") is None
    (run / "session").mkdir()
    (run / "session" / "cold.jsonl").write_text("{}", encoding="utf-8")
    assert auto_update.blocker("") == "a pi fork is running"


@pytest.mark.real_io
def test_a_clean_local_checkout_does_not_block(
    tmp_path: Path, isolated_config_dir: Path
) -> None:
    _config(isolated_config_dir, _checkout(tmp_path))
    assert auto_update.blocker("") is None


@pytest.mark.real_io
def test_a_checkout_with_commits_from_an_older_version_blocks(
    tmp_path: Path, isolated_config_dir: Path
) -> None:
    clone = _checkout(tmp_path)
    _git(clone, "commit", "-q", "--allow-empty", "-m", "local change")
    _config(isolated_config_dir, clone)
    assert auto_update.blocker("") == "llm-prompts has local changes"


@pytest.mark.real_io
def test_uncommitted_edits_block(tmp_path: Path, isolated_config_dir: Path) -> None:
    clone = _checkout(tmp_path)
    (clone / "edited.txt").write_text("x", encoding="utf-8")
    _config(isolated_config_dir, clone)
    assert auto_update.blocker("") == "llm-prompts has local changes"


def test_turning_it_off_blocks(isolated_config_dir: Path) -> None:
    _config(
        isolated_config_dir,
        Path("git+https://example.invalid/x.git"),
        "[update]\nauto = false\n\n",
    )
    assert auto_update.blocker("") == "off"


def test_no_config_blocks() -> None:
    assert auto_update.blocker("") == "no config"


def test_a_failed_run_blocks_a_rerun_until_the_versions_move(
    tmp_path: Path, isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auto_update, "STATE_DIR", tmp_path)
    _config(isolated_config_dir, Path("git+https://example.invalid/x.git"))
    auto_update.record_failure("v1", "could not fetch")
    assert auto_update.blocker("v1") == "failed"
    assert auto_update.failure("v1") == "could not fetch"
    assert auto_update.blocker("v2") is None
    assert auto_update.failure("v2") is None


def test_start_spawns_a_detached_update_only_when_nothing_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned: list[dict[str, object]] = []
    monkeypatch.setattr(
        subprocess, "Popen", lambda argv, **kwargs: spawned.append(kwargs)
    )
    monkeypatch.setattr(auto_update, "blocker", lambda fingerprint: "off")
    assert not auto_update.start("v1")
    monkeypatch.setattr(auto_update, "blocker", lambda fingerprint: None)
    assert auto_update.start("v1")
    assert len(spawned) == 1 and spawned[0]["start_new_session"] is True


def _is_update(argv: list[str]) -> bool:
    return argv[-2:] == ["update", "--auto"]


@pytest.fixture
def unblocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the state at tmp_path, leave nothing blocking a run, and report the versions as v2 after it."""
    monkeypatch.setattr(auto_update, "STATE_DIR", tmp_path)
    monkeypatch.setattr(auto_update, "blocker", lambda fingerprint: None)
    monkeypatch.setattr(auto_update, "_fingerprint", lambda: "v2")
    return tmp_path


def test_a_failed_network_call_records_the_reason_and_logs_the_output(
    unblocked: Path, fake_subprocess: FakeSubprocess
) -> None:
    fake_subprocess.on_match(
        _is_update, stdout="Checking...\n[llm-prompts] could not fetch\n", returncode=1
    )
    auto_update.run("v2")
    assert auto_update.failure("v2") == "[llm-prompts] could not fetch"
    assert "could not fetch" in (unblocked / "auto-update.log").read_text()


def test_an_update_that_stops_partway_is_not_retried_at_its_new_versions(
    unblocked: Path, fake_subprocess: FakeSubprocess
) -> None:
    fake_subprocess.on_match(_is_update, stdout="Update stopped\n", returncode=1)
    auto_update.run("v1")
    assert auto_update.failure("v2") == "Update stopped"


def test_a_successful_run_clears_an_old_failure(
    unblocked: Path, fake_subprocess: FakeSubprocess
) -> None:
    auto_update.record_failure("v2", "could not fetch")
    fake_subprocess.on_match(_is_update)
    auto_update.run("v1")
    assert auto_update.failure("v2") is None


@contextmanager
def _held_by_another_process() -> Iterator[None]:
    """Hold the update lock the way a separate process would: its own open file, no handed-over fd."""
    auto_update.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (auto_update.STATE_DIR / "auto-update.lock").open("a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def test_a_run_while_another_process_holds_the_lock_skips_the_update(
    unblocked: Path, fake_subprocess: FakeSubprocess
) -> None:
    fake_subprocess.on_match(_is_update)
    with _held_by_another_process():
        auto_update.run("v1")
    assert not fake_subprocess.matching("update")


def test_a_run_rechecks_what_blocks_it_after_taking_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_subprocess: FakeSubprocess
) -> None:
    monkeypatch.setattr(auto_update, "STATE_DIR", tmp_path)
    monkeypatch.setattr(auto_update, "blocker", lambda fingerprint: "off")
    fake_subprocess.on_match(_is_update)
    auto_update.run("v1")
    assert not fake_subprocess.matching("update")


def test_a_non_bool_auto_setting_blocks(isolated_config_dir: Path) -> None:
    _config(
        isolated_config_dir,
        Path("git+https://example.invalid/x.git"),
        '[update]\nauto = "no"\n\n',
    )
    assert (
        auto_update.blocker("") == "config error: [update] auto must be true or false"
    )


def test_a_non_table_update_setting_blocks(isolated_config_dir: Path) -> None:
    _config(
        isolated_config_dir, Path("git+https://example.invalid/x.git"), "update = 1\n\n"
    )
    assert auto_update.blocker("") == "config error: [update] must be a table"


@pytest.mark.real_io
def test_a_live_session_holding_a_configured_checkout_blocks(
    tmp_path: Path, isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = _checkout(tmp_path)
    _config(isolated_config_dir, clone)
    locks = tmp_path / "checkout-locks.json"
    monkeypatch.setattr(auto_update, "_CHECKOUT_LOCKS", locks)
    held = {
        "git_dir": str(clone / ".git"),
        "name": "",
        "session": "s",
        "pid": os.getpid(),
    }
    locks.write_text(json.dumps([{**held, "at": time.time() - 3600}]))
    assert auto_update.blocker("") is None
    locks.write_text(json.dumps([{**held, "at": time.time()}]))
    assert auto_update.blocker("") == "a session is using llm-prompts"


@pytest.mark.parametrize(
    "argv",
    [
        ["update"],
        ["update", "--only", "x.md"],
        ["install", "kiro"],
        ["setup"],
        ["contribute", "sync", "--apply"],
    ],
)
def test_a_command_that_installs_refuses_while_another_holds_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    monkeypatch.setattr(auto_update, "STATE_DIR", tmp_path)
    with _held_by_another_process(), patch("sys.argv", ["llm-prompts", *argv]):
        assert "Another llm-prompts update is running" in str(
            run_capturing_exit(cli.main)
        )


def _plugin_checkout(tmp_path: Path, isolated_config_dir: Path) -> Path:
    """Clone a remote into the plugin-sources dir and list it as a plugin."""
    remote = tmp_path / "plugin-remote"
    remote.mkdir()
    _git(remote, "init", "-q", "-b", "main")
    _git(remote, "commit", "-q", "--allow-empty", "-m", "base")
    checkout = plugins._checkout_dir("p")
    checkout.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(checkout)],
        check=True,
        capture_output=True,
    )
    (isolated_config_dir / "config.toml").write_text(
        f'[[plugins]]\nname = "p"\nsource = "git+file://{remote}"\n',
        encoding="utf-8",
    )
    return checkout


@pytest.mark.real_io
def test_a_plugin_checkout_with_edits_or_unpushed_commits_blocks(
    tmp_path: Path, isolated_config_dir: Path
) -> None:
    checkout = _plugin_checkout(tmp_path, isolated_config_dir)
    assert auto_update.blocker("") is None
    _git(checkout, "commit", "-q", "--allow-empty", "-m", "mine")
    assert auto_update.blocker("") == "p has local changes"
    _git(checkout, "reset", "-q", "--hard", "HEAD~1")
    (checkout / "edit.txt").write_text("x")
    assert auto_update.blocker("") == "p has local changes"


@pytest.mark.real_io
def test_a_live_session_holding_a_plugin_checkout_blocks(
    tmp_path: Path, isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = _plugin_checkout(tmp_path, isolated_config_dir)
    locks = tmp_path / "checkout-locks.json"
    monkeypatch.setattr(auto_update, "_CHECKOUT_LOCKS", locks)
    locks.write_text(
        json.dumps(
            [{"git_dir": str(checkout / ".git"), "pid": os.getpid(), "at": time.time()}]
        )
    )
    assert auto_update.blocker("") == "a session is using p"


def test_the_update_runs_through_a_script_that_can_restart_itself(
    unblocked: Path, fake_subprocess: FakeSubprocess
) -> None:
    fake_subprocess.on_match(_is_update)
    auto_update.run("v1")
    [argv] = [argv for argv, _ in fake_subprocess.calls if _is_update(argv)]
    script = Path(argv[0])
    assert script.name == "llm-prompts" and os.access(script, os.X_OK)


_CHILD_TAKES_LOCK = (
    "from llm_prompts import auto_update\n"
    "from pathlib import Path\n"
    "import sys\n"
    "auto_update.STATE_DIR = Path(sys.argv[1])\n"
    "with auto_update.lock() as held:\n"
    "    print(held)\n"
)


@pytest.mark.real_io
@pytest.mark.parametrize(
    ("handed_over", "expected"), [(True, "True"), (False, "False")]
)
def test_a_child_keeps_the_lock_only_when_handed_its_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, handed_over: bool, expected: str
) -> None:
    monkeypatch.setattr(auto_update, "STATE_DIR", tmp_path)
    with auto_update.lock() as held:
        assert held
        fd = int(os.environ[auto_update.LOCK_FD_ENV])
        child = subprocess.run(
            [sys.executable, "-c", _CHILD_TAKES_LOCK, str(tmp_path)],
            pass_fds=(fd,) if handed_over else (),
            capture_output=True,
            text=True,
            check=True,
        )
    assert child.stdout.strip() == expected
    assert auto_update.LOCK_FD_ENV not in os.environ


def test_the_lock_file_survives_a_restart_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auto_update, "STATE_DIR", tmp_path)
    with auto_update.lock():
        assert os.get_inheritable(int(os.environ[auto_update.LOCK_FD_ENV]))
