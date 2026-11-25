"""Tests for migrating git-sourced tools to local clones."""

from __future__ import annotations

import base64
import hashlib
import subprocess
import tomllib
from pathlib import Path

import pytest
from conftest import FakeSubprocess

from llm_prompts import clones, setup
from llm_prompts.exit_reason import ExitReason

pytestmark = pytest.mark.usefixtures("real_clone_migration")


@pytest.fixture(autouse=True)
def _package_names_are_tool_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clones, "package_name", lambda tool: str(tool["name"]))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A remote with a release tag and one commit after it."""
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q", "-b", "main")
    _git(remote, "commit", "-q", "--allow-empty", "-m", "base")
    _git(remote, "tag", "v0.1.0")
    _git(remote, "commit", "-q", "--allow-empty", "-m", "unreleased")
    return remote


def _write_config(config_dir: Path, *sources: str) -> None:
    blocks = "".join(
        f'# note {i}\n[[tools]]\nname = "tool{i}"\nsource = "{source}"\n\n'
        for i, source in enumerate(sources)
    )
    (config_dir / "config.toml").write_text(blocks, encoding="utf-8")


def _migrate(*, dry_run: bool = False) -> bool:
    return clones.migrate(setup._load_config(), dry_run=dry_run)


def _blocked(*, dry_run: bool = False) -> bool:
    try:
        clones.block_on_installed_edits(setup._load_config(), dry_run=dry_run)
    except ExitReason as raised:
        assert raised.reason == "installed_edits"
        return True
    return False


def _sources() -> list[str]:
    return [tool["source"] for tool in setup.read_config()["tools"]]


@pytest.mark.real_io
def test_a_git_source_becomes_a_clone_at_its_release(
    remote: Path,
    isolated_config_dir: Path,
    isolated_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(isolated_config_dir, f"git+file://{remote}")
    assert _migrate() is True
    clone = isolated_home / ".llm-prompts" / "tool0"
    assert _git(clone, "rev-parse", "HEAD") == _git(remote, "rev-parse", "v0.1.0")
    assert _sources() == ["~/.llm-prompts/tool0"]
    assert "# note 0" in (isolated_config_dir / "config.toml").read_text("utf-8")
    out = capsys.readouterr().out
    assert f"[tool0] cloned it to {clone}" in out
    assert str(remote) not in out
    assert 'source = "~/.llm-prompts/tool0"' in out


@pytest.mark.real_io
def test_a_second_run_changes_nothing(
    remote: Path, isolated_config_dir: Path, isolated_home: Path
) -> None:
    _write_config(isolated_config_dir, f"git+file://{remote}")
    _migrate()
    clone = isolated_home / ".llm-prompts" / "tool0"
    (clone / "notes.txt").write_text("mine", encoding="utf-8")
    _git(clone, "commit", "-q", "--allow-empty", "-m", "local")
    head = _git(clone, "rev-parse", "HEAD")
    assert _migrate() is False
    assert _git(clone, "rev-parse", "HEAD") == head
    assert (clone / "notes.txt").read_text("utf-8") == "mine"


@pytest.mark.real_io
def test_an_existing_clone_with_local_edits_is_reused_untouched(
    remote: Path,
    isolated_config_dir: Path,
    isolated_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clone = isolated_home / ".llm-prompts" / "tool0"
    subprocess.run(
        ["git", "clone", "-q", f"file://{remote}", str(clone)],
        check=True,
        capture_output=True,
    )
    _git(clone, "commit", "-q", "--allow-empty", "-m", "local")
    (clone / "scratch.txt").write_text("mine", encoding="utf-8")
    head = _git(clone, "rev-parse", "HEAD")
    _write_config(isolated_config_dir, f"git+file://{remote}")
    assert _migrate() is True
    assert _git(clone, "rev-parse", "HEAD") == head
    assert (clone / "scratch.txt").exists()
    assert _sources() == ["~/.llm-prompts/tool0"]
    assert f"reusing the clone at {clone}" in capsys.readouterr().out


@pytest.mark.real_io
def test_a_folder_holding_another_repository_keeps_the_git_source(
    remote: Path,
    tmp_path: Path,
    isolated_config_dir: Path,
    isolated_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    clone = isolated_home / ".llm-prompts" / "tool0"
    clone.parent.mkdir()
    subprocess.run(
        ["git", "clone", "-q", str(other), str(clone)],
        check=True,
        capture_output=True,
    )
    _write_config(isolated_config_dir, f"git+file://{remote}")
    assert _migrate() is False
    assert _sources() == [f"git+file://{remote}"]
    assert "Keeping its git source" in capsys.readouterr().err


@pytest.mark.real_io
def test_a_folder_holding_a_file_keeps_the_git_source(
    remote: Path, isolated_config_dir: Path, isolated_home: Path
) -> None:
    (isolated_home / ".llm-prompts").mkdir()
    (isolated_home / ".llm-prompts" / "tool0").write_text("x", encoding="utf-8")
    _write_config(isolated_config_dir, f"git+file://{remote}")
    assert _migrate() is False
    assert _sources() == [f"git+file://{remote}"]


@pytest.mark.real_io
def test_a_failed_clone_keeps_the_git_source_and_migrates_the_rest(
    remote: Path,
    tmp_path: Path,
    isolated_config_dir: Path,
    isolated_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = f"git+file://{tmp_path / 'missing'}"
    _write_config(isolated_config_dir, missing, f"git+file://{remote}")
    assert _migrate() is True
    assert _sources() == [missing, "~/.llm-prompts/tool1"]
    assert "[tool0] clone failed" in capsys.readouterr().err


@pytest.mark.real_io
def test_pinned_and_local_sources_are_left_alone(
    remote: Path, isolated_config_dir: Path, isolated_home: Path
) -> None:
    pinned = f"git+file://{remote}@v0.1.0"
    (isolated_config_dir / "config.toml").write_text(
        f'[[tools]]\nname = "a"\nsource = "{pinned}"\n\n'
        f'[[tools]]\nname = "b"\nsource = "git+file://{remote}"\nref = "main"\n\n'
        '[[tools]]\nname = "c"\nsource = "~/git/c"\n',
        encoding="utf-8",
    )
    assert _migrate() is False
    assert not (isolated_home / ".llm-prompts").exists()


@pytest.mark.real_io
def test_a_dry_run_clones_and_edits_nothing(
    remote: Path,
    isolated_config_dir: Path,
    isolated_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(isolated_config_dir, f"git+file://{remote}")
    assert _migrate(dry_run=True) is False
    assert not (isolated_home / ".llm-prompts").exists()
    assert _sources() == [f"git+file://{remote}"]
    assert "[tool0] would clone" in capsys.readouterr().out


def test_the_config_stays_valid_toml_when_tools_share_other_tables(
    isolated_config_dir: Path,
) -> None:
    text = '[update]\nauto = false\n\n[[tools]]\nsource = "git+x"\nname = "a"\n\n[[plugins]]\nname = "a"\nsource = "git+p"\n'
    repointed = clones._repoint(text, "a", "~/.llm-prompts/a")
    assert repointed is not None
    parsed = tomllib.loads(repointed)
    assert parsed["tools"][0]["source"] == "~/.llm-prompts/a"
    assert parsed["plugins"][0]["source"] == "git+p"


def test_setup_migrates_before_installing_and_uses_the_new_sources(
    isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(isolated_config_dir, "git+https://example.invalid/a.git")
    monkeypatch.setattr(setup, "_require_uv", lambda: None)

    def migrate(tools: list[dict[str, str]], *, dry_run: bool = False) -> bool:
        (isolated_config_dir / "config.toml").write_text(
            '[[tools]]\nname = "tool0"\nsource = "~/.llm-prompts/tool0"\n',
            encoding="utf-8",
        )
        return True

    def stop(tools: list[dict[str, str]]) -> set[str]:
        raise _Reached([tool["source"] for tool in tools])

    monkeypatch.setattr(clones, "migrate", migrate)
    monkeypatch.setattr(setup, "detect_changed_local_tools", stop)
    with pytest.raises(_Reached) as reached:
        setup.run_setup()
    assert reached.value.args[0] == ["~/.llm-prompts/tool0"]


class _Reached(Exception):
    pass


def _install(name: str, files: dict[str, str]) -> Path:
    """Install a package into the shared env of tool0 with a RECORD for ``files``."""
    site = setup._uv_tools_dir() / "tool0" / "lib" / "site-packages"
    dist_info = site / f"{name}-1.0.dist-info"
    dist_info.mkdir(parents=True)
    rows = []
    for path, content in files.items():
        (site / path).parent.mkdir(parents=True, exist_ok=True)
        (site / path).write_text(content, encoding="utf-8")
        digest = base64.urlsafe_b64encode(hashlib.sha256(content.encode()).digest())
        rows.append(f"{path},sha256={digest.rstrip(b'=').decode()},{len(content)}")
    (dist_info / "RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return site


@pytest.mark.real_io
def test_an_installed_copy_with_edits_blocks_the_run_and_names_the_files(
    remote: Path,
    isolated_config_dir: Path,
    isolated_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    site = _install("tool0", {"tool0/rules.md": "shipped", "tool0/skill.md": "x"})
    (site / "tool0" / "rules.md").write_text("mine", encoding="utf-8")
    _write_config(isolated_config_dir, f"git+file://{remote}")
    assert _blocked() is True
    assert _sources() == [f"git+file://{remote}"]
    assert not (isolated_home / ".llm-prompts").exists()
    err = capsys.readouterr().err
    assert "tool0/rules.md" in err
    assert "tool0/skill.md" not in err


@pytest.mark.real_io
def test_a_dry_run_warns_of_edits_without_blocking(
    remote: Path, isolated_config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = _install("tool0", {"tool0/rules.md": "shipped"})
    (site / "tool0" / "rules.md").write_text("mine", encoding="utf-8")
    _write_config(isolated_config_dir, f"git+file://{remote}")
    assert _blocked(dry_run=True) is False
    assert "tool0/rules.md" in capsys.readouterr().err


@pytest.mark.real_io
def test_a_deleted_installed_file_counts_as_an_edit(
    remote: Path, isolated_config_dir: Path
) -> None:
    site = _install("tool0", {"tool0/rules.md": "shipped"})
    (site / "tool0" / "rules.md").unlink()
    _write_config(isolated_config_dir, f"git+file://{remote}")
    assert _blocked() is True


@pytest.mark.real_io
def test_an_unedited_installed_copy_does_not_block(
    remote: Path, isolated_config_dir: Path
) -> None:
    _install("tool0", {"tool0/rules.md": "shipped"})
    _write_config(isolated_config_dir, f"git+file://{remote}")
    assert _blocked() is False
    assert _migrate() is True


@pytest.mark.real_io
def test_edits_in_one_installed_tool_block_the_whole_run(
    remote: Path,
    isolated_config_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    site = _install("tool1", {"tool1/rules.md": "shipped"})
    (site / "tool1" / "rules.md").write_text("mine", encoding="utf-8")
    _write_config(
        isolated_config_dir,
        f"git+file://{remote}",
        f"git+file://{remote}@v0.1.0",
        "~/git/local",
    )
    assert _blocked() is True
    assert "[tool1] its installed copy has edits" in capsys.readouterr().err


@pytest.mark.real_io
def test_a_config_without_git_sources_is_not_checked(
    isolated_config_dir: Path,
) -> None:
    site = _install("tool0", {"tool0/rules.md": "shipped"})
    (site / "tool0" / "rules.md").write_text("mine", encoding="utf-8")
    _write_config(isolated_config_dir, "/local/path")
    assert _blocked() is False


@pytest.mark.real_io
def test_setup_stops_before_upgrading_or_reinstalling_over_edits(
    remote: Path,
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_subprocess: FakeSubprocess,
) -> None:
    site = _install("tool0", {"tool0/rules.md": "shipped"})
    (site / "tool0" / "rules.md").write_text("mine", encoding="utf-8")
    _write_config(isolated_config_dir, f"git+file://{remote}@v0.1.0")
    monkeypatch.setattr(setup, "_require_uv", lambda: None)
    with pytest.raises(ExitReason) as raised:
        setup.run_setup()
    assert raised.value.reason == "installed_edits"
    assert fake_subprocess.matching("uv") == []


def test_only_the_source_value_changes(isolated_config_dir: Path) -> None:
    text = '[[tools]]\nname = "a" # first\nsource = "git+x" # keep me\ntest = """\nsource = 1\n"""\n'
    repointed = clones._repoint(text, "a", "~/.llm-prompts/a")
    assert repointed == text.replace('"git+x"', '"~/.llm-prompts/a"')


@pytest.mark.parametrize(
    "text",
    [
        '[[tools]]\nname = "a"\nsource = """\ngit+x"""\n',
        '[[tools]]\nname = "a"\nsource = "git+x" extra\n',
        '[[tools]]\nname = "b"\nsource = "git+x"\n',
        '[[tools]]\nname = "a"\nnote = """\n[[tools]]\nname = "a"\nsource = "y"\n"""\n',
    ],
)
def test_an_edit_that_would_not_leave_valid_config_is_refused(text: str) -> None:
    assert clones._repoint(text, "a", "~/.llm-prompts/a") is None


@pytest.mark.real_io
def test_the_config_keeps_its_permissions_and_leaves_no_temp_file(
    remote: Path, isolated_config_dir: Path
) -> None:
    _write_config(isolated_config_dir, f"git+file://{remote}")
    config = isolated_config_dir / "config.toml"
    config.chmod(0o600)
    assert _migrate() is True
    assert config.stat().st_mode & 0o777 == 0o600
    assert [path.name for path in isolated_config_dir.iterdir()] == ["config.toml"]


@pytest.mark.real_io
def test_credentials_in_a_url_never_reach_the_output(
    tmp_path: Path,
    isolated_config_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url = f"git+file://user:secret@{tmp_path / 'missing'}"
    _write_config(isolated_config_dir, url)
    _migrate(dry_run=True)
    _migrate()
    out, err = capsys.readouterr()
    assert "secret" not in out + err


def test_a_failed_clone_logs_a_fixed_warning_without_git_output(
    isolated_config_dir: Path,
    fake_subprocess: FakeSubprocess,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_subprocess.on(
        "clone",
        returncode=128,
        stderr="fatal: unable to access 'https://host/r.git/?token=secret'",
    )
    _write_config(isolated_config_dir, "git+https://host/r.git?token=secret")
    assert _migrate() is False
    out, err = capsys.readouterr()
    assert "secret" not in out + err
    assert "[tool0] clone failed. Keeping its git source." in err


def test_a_stalled_clone_is_tried_once_and_keeps_the_git_source(
    isolated_config_dir: Path,
    isolated_home: Path,
    fake_subprocess: FakeSubprocess,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_subprocess.on(
        "clone",
        side_effect=subprocess.TimeoutExpired(["git", "clone", "https://u:p@h/r"], 1),
    )
    _write_config(isolated_config_dir, "git+https://u:p@example.invalid/r.git")
    assert _migrate() is False
    assert len(fake_subprocess.matching("clone")) == 1
    _, kwargs = fake_subprocess.calls[0]
    assert kwargs["timeout"] == clones.CLONE_TIMEOUT
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert not (isolated_home / ".llm-prompts" / "tool0").exists()
    err = capsys.readouterr().err
    assert "Keeping its git source" in err
    assert "p@" not in err
    assert "h/r" not in err


@pytest.mark.real_io
def test_crlf_line_endings_survive_the_edit(
    remote: Path, isolated_config_dir: Path
) -> None:
    config = isolated_config_dir / "config.toml"
    original = (
        f'# c\r\n[[tools]]\r\nname = "tool0"\r\nsource = "git+file://{remote}"\r\n'
    )
    config.write_bytes(original.encode())
    assert _migrate() is True
    assert (
        config.read_bytes()
        == original.replace(f"git+file://{remote}", "~/.llm-prompts/tool0").encode()
    )
