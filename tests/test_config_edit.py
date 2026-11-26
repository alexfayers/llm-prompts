"""Tests for loading, checking and saving the config file."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from llm_prompts import config_edit
from llm_prompts.exit_reason import ExitReason
from llm_prompts.setup import config_errors

_CONFIG = """\
# my tools
[[tools]]
name = "llm-prompts"
source = "https://github.com/example/llm-prompts.git"

[update]
auto = true  # keep updated

[pi]
runtime = "node"
"""


def _write_config(config_dir: Path) -> Path:
    path = config_dir / "config.toml"
    path.write_text(_CONFIG, encoding="utf-8")
    return path


def test_save_keeps_comments_and_unknown_tables(isolated_config_dir: Path) -> None:
    path = _write_config(isolated_config_dir)
    loaded = config_edit.load_doc()

    loaded.doc["update"]["auto"] = False
    config_edit.save_doc(loaded)

    assert path.read_text(encoding="utf-8") == _CONFIG.replace(
        "auto = true", "auto = false"
    )


def test_save_backs_up_the_previous_file(isolated_config_dir: Path) -> None:
    _write_config(isolated_config_dir)
    loaded = config_edit.load_doc()

    loaded.doc["update"]["auto"] = False
    assert config_edit.save_doc(loaded)

    [backup] = isolated_config_dir.glob("config.toml.bak-*")
    assert backup.read_text(encoding="utf-8") == _CONFIG


def test_save_skips_an_unchanged_doc(isolated_config_dir: Path) -> None:
    path = _write_config(isolated_config_dir)
    before = path.stat().st_mtime_ns

    assert not config_edit.save_doc(config_edit.load_doc())

    assert path.stat().st_mtime_ns == before
    assert not list(isolated_config_dir.glob("config.toml.bak-*"))


def test_save_creates_a_missing_file_without_backup(isolated_config_dir: Path) -> None:
    loaded = config_edit.load_doc()

    loaded.doc["update"] = {"auto": False}
    assert config_edit.save_doc(loaded)

    assert [p.name for p in isolated_config_dir.iterdir()] == ["config.toml"]


def test_load_rejects_invalid_toml(isolated_config_dir: Path) -> None:
    (isolated_config_dir / "config.toml").write_text("[tools", encoding="utf-8")

    with pytest.raises(ExitReason) as raised:
        config_edit.load_doc()

    assert raised.value.reason == "config_invalid"


def test_config_errors_accepts_a_valid_config(isolated_config_dir: Path) -> None:
    _write_config(isolated_config_dir)

    assert config_errors(config_edit.load_doc().doc.unwrap()) == []


def test_config_errors_needs_a_tool() -> None:
    assert config_errors({}) == ["Config must contain at least one [[tools]] entry."]


def test_config_errors_lists_tool_and_plugin_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    config = {
        "tools": [{"name": "local", "source": str(missing)}],
        "plugins": [{"name": "extra", "source": "not-a-url"}],
    }

    assert config_errors(config) == [
        f"[local] Path does not exist: {missing}",
        "[extra] plugin source must be a git URL: not-a-url",
    ]


def test_save_rejects_a_file_changed_since_load(isolated_config_dir: Path) -> None:
    path = _write_config(isolated_config_dir)
    loaded = config_edit.load_doc()
    newer = _CONFIG + "# added elsewhere\n"
    path.write_text(newer, encoding="utf-8")

    loaded.doc["update"]["auto"] = False
    with pytest.raises(ExitReason) as raised:
        config_edit.save_doc(loaded)

    assert raised.value.reason == "config_changed"
    assert path.read_text(encoding="utf-8") == newer


def test_save_rejects_a_file_created_since_load(isolated_config_dir: Path) -> None:
    loaded = config_edit.load_doc()
    path = _write_config(isolated_config_dir)

    loaded.doc["update"] = {"auto": False}
    with pytest.raises(ExitReason) as raised:
        config_edit.save_doc(loaded)

    assert raised.value.reason == "config_changed"
    assert path.read_text(encoding="utf-8") == _CONFIG


def test_saves_in_one_second_keep_every_backup(
    isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(isolated_config_dir)
    monkeypatch.setattr(config_edit, "_backup_stamp", lambda: "20260101T000000")

    for auto in (False, True):
        loaded = config_edit.load_doc()
        loaded.doc["update"]["auto"] = auto
        assert config_edit.save_doc(loaded)

    backups = sorted(isolated_config_dir.glob("config.toml.bak-*"))
    assert [b.read_text(encoding="utf-8") for b in backups] == [
        _CONFIG,
        _CONFIG.replace("auto = true", "auto = false"),
    ]


@pytest.mark.parametrize(
    ("config", "error"),
    [
        ({"tools": "x"}, "[[tools]] must be a list of tables"),
        ({"tools": ["x"]}, "[[tools]] entry 1 must be a table: 'x'"),
        ({"tools": [{"source": "/tmp"}]}, "[[tools]] entry 1 needs a name string"),
        ({"tools": [{"name": "a"}]}, "[[tools]] entry 1 needs a source string"),
        ({"plugins": {"a": 1}}, "[[plugins]] must be a list of tables"),
        ({"plugins": [3]}, "[[plugins]] entry 1 must be a table: 3"),
        ({"plugins": [{"name": 1}]}, "[[plugins]] entry 1 needs a name string"),
    ],
)
def test_config_errors_reports_malformed_entries(
    config: dict[str, object], error: str
) -> None:
    assert error in config_errors({"tools": [{"name": "a", "source": "/"}], **config})


def test_save_writes_backup_and_scratch_private_before_copying_modes(
    isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_config(isolated_config_dir)
    path.chmod(0o600)
    modes_before_copy: list[int] = []

    def record_mode(copy: Callable[..., None]) -> Callable[..., None]:
        def recording(src: Path, dst: Path, **kwargs: object) -> None:
            modes_before_copy.append(Path(dst).stat().st_mode & 0o777)
            copy(src, dst, **kwargs)

        return recording

    monkeypatch.setattr(shutil, "copystat", record_mode(shutil.copystat))
    monkeypatch.setattr(shutil, "copymode", record_mode(shutil.copymode))
    loaded = config_edit.load_doc()
    loaded.doc["update"]["auto"] = False
    config_edit.save_doc(loaded)

    [backup] = isolated_config_dir.glob("config.toml.bak-*")
    assert modes_before_copy == [0o600, 0o600]
    assert backup.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o600
