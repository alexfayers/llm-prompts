"""Tests for the llm-prompts folders under the shared root."""

from __future__ import annotations

import errno
import shutil
from pathlib import Path

import pytest
from platformdirs import user_data_dir

from llm_prompts import home as home_module
from llm_prompts import tool_paths
from llm_prompts.benchmark import paths
from llm_prompts.home import Home


def _tool(base: Path, kind: str) -> Path:
    return base / "llm-prompts" / kind


def test_folders_sit_under_the_shared_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(tool_paths.ROOT_ENV, str(tmp_path))
    home = Home()

    assert home.tool_dir("config") == _tool(tmp_path, "config")
    assert home.live_dir("cache") == _tool(tmp_path, "cache")


def test_an_install_root_holds_its_own_shared_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(tool_paths.ROOT_ENV, str(tmp_path / "live"))
    home = Home()
    home.root = tmp_path / "install"

    assert home.tool_dir("data") == _tool(
        tmp_path / "install" / ".local" / "share" / "llm-prompts", "data"
    )
    assert home.live_dir("state") == _tool(tmp_path / "live", "state")


def test_a_process_outside_the_installed_tool_copies_nothing(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_prompts.setup._running_as_installed_tool", lambda: False)
    old = isolated_home / ".config" / "llm-prompts" / "config.toml"
    old.parent.mkdir(parents=True)
    old.write_text("x", encoding="utf-8")

    assert not (Home().tool_dir("config") / "config.toml").exists()
    assert old.exists()


def test_copies_old_files_into_their_kind_folders(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_prompts.setup._running_as_installed_tool", lambda: True)
    old_config = isolated_home / ".config" / "llm-prompts"
    old_data = Path(user_data_dir("llm-prompts"))
    old_watch = isolated_home / ".cache" / "llm-prompts" / "watch"
    for path in (
        old_config / "config.toml",
        old_config / "receipts.json.lock",
        old_config / "telemetry.json",
        old_data / "auto-update.log",
        old_watch / "pr.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    home = Home()

    assert (home.tool_dir("config") / "config.toml").exists()
    assert (home.tool_dir("data") / "receipts.json.lock").exists()
    assert (home.tool_dir("state") / "telemetry.json").exists()
    assert (home.tool_dir("state") / "auto-update.log").exists()
    assert (home.tool_dir("cache") / "watch" / "pr.json").exists()
    assert sorted(p.name for p in old_config.iterdir()) == [
        "config.toml",
        "receipts.json.lock",
        "telemetry.json",
    ]


def _installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("llm_prompts.setup._running_as_installed_tool", lambda: True)


def test_a_root_inside_the_old_config_folder_is_not_copied_into_itself(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _installed(monkeypatch)
    old_config = isolated_home / ".config" / "llm-prompts"
    (old_config / "root").mkdir(parents=True)
    (old_config / "config.toml").write_text("x", encoding="utf-8")
    monkeypatch.setenv(tool_paths.ROOT_ENV, str(old_config / "root"))

    Home().tool_dir("config")

    assert not list((old_config / "root").rglob("root"))


def test_a_symlink_to_an_old_file_is_copied_as_an_independent_file(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _installed(monkeypatch)
    old_data = Path(user_data_dir("llm-prompts"))
    old_data.mkdir(parents=True)
    legacy_log = isolated_home / ".config" / "llm-prompts" / "update.log"
    legacy_log.parent.mkdir(parents=True)
    legacy_log.write_text("old", encoding="utf-8")
    (old_data / "auto-update.log").symlink_to(legacy_log)

    copy = Home().tool_dir("state") / "auto-update.log"
    copy.write_text("new", encoding="utf-8")

    assert not copy.is_symlink()
    assert legacy_log.read_text(encoding="utf-8") == "old"


def test_a_failed_copy_is_reported_and_the_old_folder_stays_in_use(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _installed(monkeypatch)
    old_config = isolated_home / ".config" / "llm-prompts"
    old_config.mkdir(parents=True)
    (old_config / "config.toml").write_text("x", encoding="utf-8")
    with monkeypatch.context() as patch:
        patch.setattr(shutil, "copy2", _fail_copy)
        home = Home()

        assert home.tool_dir("config") == old_config
        assert home.config_dir() == old_config
    assert "denied" in capsys.readouterr().err

    assert (Home().tool_dir("config") / "config.toml").read_text(
        encoding="utf-8"
    ) == "x"
    assert Home().tool_dir("config") == _tool(tool_paths.root(), "config")


def _fail_copy(*_: object, **__: object) -> None:
    raise PermissionError(errno.EACCES, "denied")


def test_old_benchmark_output_and_variants_are_copied(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _installed(monkeypatch)
    results = isolated_home / ".local" / "state" / "llm-prompts" / "benchmark"
    variant = isolated_home / ".cache" / "llm-prompts" / "benchmark" / "variants"
    for path in (results / "runs" / "r1" / "results.jsonl", variant / "k" / "src"):
        path.parent.mkdir(parents=True)
        path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(home_module, "_HOME", Home())

    assert (paths.runs_dir() / "r1" / "results.jsonl").exists()
    assert (paths.variant_dir("k") / "src").exists()
    assert paths.state_dir() == home_module.live_dir("state", "benchmark")


def test_a_failed_copy_keeps_each_state_file_at_its_old_place(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _installed(monkeypatch)
    old_config = isolated_home / ".config" / "llm-prompts"
    old_data = Path(user_data_dir("llm-prompts"))
    old_state = isolated_home / ".local" / "state" / "llm-prompts" / "benchmark"
    old_cache = isolated_home / ".cache" / "llm-prompts" / "benchmark" / "variants"
    for path in (
        old_config / "telemetry.json",
        old_data / "auto-update.lock",
        old_state / "runs" / "r1",
        old_cache / "k",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(shutil, "copy2", _fail_copy)
    home = Home()

    assert home.live_dir("state", "auto-update.lock") == old_data / "auto-update.lock"
    assert home.live_dir("state", "telemetry.json") == old_config / "telemetry.json"
    assert home.live_dir("state", "benchmark") == old_state
    assert home.live_dir("cache", "benchmark") == old_cache.parent


def test_a_folder_that_copies_is_used_while_another_keeps_its_old_files(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _installed(monkeypatch)
    old_config = isolated_home / ".config" / "llm-prompts"
    old_cache = isolated_home / ".cache" / "llm-prompts" / "watch"
    for path in (old_config / "config.toml", old_cache / "pr.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    real_copy = shutil.copy2

    def copy(source: Path, target: Path) -> object:
        if Path(source).name == "pr.json":
            _fail_copy()
        return real_copy(source, target)

    monkeypatch.setattr(shutil, "copy2", copy)
    home = Home()

    assert home.config_dir() == _tool(tool_paths.root(), "config")
    assert (home.config_dir() / "config.toml").exists()
    assert home.live_dir("cache", "watch") == old_cache


def test_a_folder_with_nothing_to_copy_uses_its_new_path(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _installed(monkeypatch)

    assert Home().tool_dir("state") == _tool(tool_paths.root(), "state")


def test_a_root_that_cannot_be_created_is_reported_and_old_folders_stay_in_use(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _installed(monkeypatch)
    blocker = isolated_home / "blocker"
    blocker.write_text("", encoding="utf-8")
    old_config = isolated_home / ".config" / "llm-prompts"
    old_config.mkdir(parents=True)
    (old_config / "config.toml").write_text("x", encoding="utf-8")
    monkeypatch.setenv(tool_paths.ROOT_ENV, str(blocker / "root"))

    assert Home().tool_dir("config") == isolated_home / ".config" / "llm-prompts"
    assert "llm-prompts could not copy" in capsys.readouterr().err


def test_an_unreadable_new_folder_is_reported_and_old_folders_stay_in_use(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _installed(monkeypatch)
    old_config = isolated_home / ".config" / "llm-prompts"
    old_config.mkdir(parents=True)
    (old_config / "config.toml").write_text("x", encoding="utf-8")
    unreadable = tool_paths.root() / "llm-prompts" / "config"
    unreadable.mkdir(parents=True)
    unreadable.chmod(0)
    try:
        assert Home().tool_dir("config") == old_config
    finally:
        unreadable.chmod(0o700)
    assert "llm-prompts could not copy" in capsys.readouterr().err


def test_an_error_in_one_folder_keeps_a_published_folder_on_its_new_path(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _installed(monkeypatch)
    old_config = isolated_home / ".config" / "llm-prompts"
    old_cache = isolated_home / ".cache" / "llm-prompts" / "watch"
    for path in (old_config / "config.toml", old_cache / "pr.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    cache = tool_paths.root() / "llm-prompts" / "cache"
    cache.parent.mkdir(parents=True)
    cache.write_text("blocker", encoding="utf-8")
    home = Home()

    assert (home.config_dir() / "config.toml").exists()
    assert home.live_dir("cache", "watch") == old_cache
