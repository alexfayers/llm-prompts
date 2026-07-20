"""Tests for CLI update check functionality."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


from llm_prompts.cli import (
    _check_for_updates,
    _collect_update_messages,
    _extract_git_url,
    _get_installed_commit,
    _local_source_messages,
    _remote_source_messages,
)


class TestExtractGitUrl:
    def test_git_plus_https(self) -> None:
        assert (
            _extract_git_url("git+https://github.com/user/repo.git")
            == "https://github.com/user/repo.git"
        )

    def test_git_plus_ssh(self) -> None:
        assert (
            _extract_git_url("git+ssh://git@github.com/user/repo.git")
            == "ssh://git@github.com/user/repo.git"
        )

    def test_plain_https(self) -> None:
        assert (
            _extract_git_url("https://github.com/user/repo.git")
            == "https://github.com/user/repo.git"
        )

    def test_local_path(self) -> None:
        assert _extract_git_url("~/git/llm-prompts") is None

    def test_relative_path(self) -> None:
        assert _extract_git_url("./local-package") is None

    def test_pypi_name(self) -> None:
        assert _extract_git_url("some-package") is None


class TestGetInstalledCommit:
    def test_finds_commit_from_vcs_info(self, tmp_path: Path) -> None:
        dist_info = (
            tmp_path
            / "llm-prompts"
            / "lib"
            / "python3.14"
            / "site-packages"
            / "my_tool-0.1.0.dist-info"
        )
        dist_info.mkdir(parents=True)
        direct_url = dist_info / "direct_url.json"
        direct_url.write_text(
            json.dumps(
                {
                    "url": "https://github.com/user/repo.git",
                    "vcs_info": {
                        "vcs": "git",
                        "commit_id": "abc123def456",
                    },
                }
            )
        )

        with patch("llm_prompts.cli.Path.home", return_value=tmp_path / "fake_home"):
            uv_tools = tmp_path / "fake_home" / ".local" / "share" / "uv" / "tools"
            uv_tools.mkdir(parents=True)
            (uv_tools / "my-tool").symlink_to(tmp_path / "llm-prompts")

            result = _get_installed_commit("my-tool")
            assert result == "abc123def456"

    def test_returns_none_for_editable_install(self, tmp_path: Path) -> None:
        dist_info = (
            tmp_path
            / "my-tool"
            / "lib"
            / "python3.14"
            / "site-packages"
            / "my_tool-0.1.0.dist-info"
        )
        dist_info.mkdir(parents=True)
        direct_url = dist_info / "direct_url.json"
        direct_url.write_text(
            json.dumps(
                {
                    "url": "file:///Users/someone/git/my-tool",
                    "dir_info": {"editable": True},
                }
            )
        )

        with patch("llm_prompts.cli.Path.home", return_value=tmp_path / "fake_home"):
            uv_tools = tmp_path / "fake_home" / ".local" / "share" / "uv" / "tools"
            uv_tools.mkdir(parents=True)
            (uv_tools / "my-tool").symlink_to(tmp_path / "my-tool")

            result = _get_installed_commit("my-tool")
            assert result is None

    def test_returns_none_when_not_installed(self, tmp_path: Path) -> None:
        with patch("llm_prompts.cli.Path.home", return_value=tmp_path / "fake_home"):
            uv_tools = tmp_path / "fake_home" / ".local" / "share" / "uv" / "tools"
            uv_tools.mkdir(parents=True)

            result = _get_installed_commit("nonexistent")
            assert result is None


class TestRemoteSourceMessages:
    def test_not_a_git_url(self) -> None:
        assert _remote_source_messages("pkg", "some-pypi-package") == []

    def test_not_installed(self) -> None:
        with patch("llm_prompts.cli._get_installed_commit", return_value=None):
            result = _remote_source_messages(
                "pkg", "git+https://github.com/user/repo.git"
            )
            assert result == ["[pkg] not installed (run `llm-prompts setup` first)"]

    def test_up_to_date(self) -> None:
        with patch("llm_prompts.cli._get_installed_commit", return_value="abc123"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="abc123\tHEAD\n",
                )
                result = _remote_source_messages(
                    "pkg", "git+https://github.com/user/repo.git"
                )
                assert result == []

    def test_update_available(self) -> None:
        with patch("llm_prompts.cli._get_installed_commit", return_value="abc123aa"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="def456bb\tHEAD\n",
                )
                result = _remote_source_messages(
                    "pkg", "git+https://github.com/user/repo.git"
                )
                assert result == ["[pkg] update available (abc123aa -> def456bb)"]

    def test_ls_remote_fails(self) -> None:
        with patch("llm_prompts.cli._get_installed_commit", return_value="abc123"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=128,
                    stdout="",
                )
                result = _remote_source_messages(
                    "pkg", "git+https://github.com/user/repo.git"
                )
                assert result == []


class TestLocalSourceMessages:
    def test_has_updates(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),
                MagicMock(returncode=0, stdout="3\n"),
            ]
            result = _local_source_messages("core", str(tmp_path))
            assert result == ["[core] 3 new commit(s) available"]

    def test_up_to_date(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),
                MagicMock(returncode=0, stdout="0\n"),
            ]
            result = _local_source_messages("core", str(tmp_path))
            assert result == []

    def test_no_git_dir(self, tmp_path: Path) -> None:
        assert _local_source_messages("core", str(tmp_path)) == []

    def test_rev_list_fails(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),
                MagicMock(returncode=128, stdout=""),
            ]
            result = _local_source_messages("core", str(tmp_path))
            assert result == []


class TestCollectUpdateMessages:
    def test_no_config(self) -> None:
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = False
            assert _collect_update_messages() == []

    def test_mixed_sources(self) -> None:
        config = [
            {"name": "core", "source": "~/git/llm-prompts"},
            {"name": "remote-pkg", "source": "git+https://github.com/user/repo.git"},
        ]
        with patch("llm_prompts.setup.CONFIG_PATH") as mock_config:
            mock_config.exists.return_value = True
            with patch("llm_prompts.setup._load_config", return_value=config):
                with patch(
                    "llm_prompts.cli._local_source_messages",
                    return_value=["[core] 2 new commit(s) available"],
                ) as mock_local:
                    with patch(
                        "llm_prompts.cli._remote_source_messages",
                        return_value=["[remote-pkg] update available (aa -> bb)"],
                    ) as mock_remote:
                        result = _collect_update_messages()

        assert result == [
            "[core] 2 new commit(s) available",
            "[remote-pkg] update available (aa -> bb)",
        ]
        mock_local.assert_called_once_with("core", "~/git/llm-prompts")
        mock_remote.assert_called_once_with(
            "remote-pkg", "git+https://github.com/user/repo.git"
        )


class TestCheckForUpdates:
    def test_prints_sentinel_when_no_messages(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("llm_prompts.cli._collect_update_messages", return_value=[]):
            result = _check_for_updates()
        assert result is False
        assert capsys.readouterr().out == "All tools are up to date.\n"

    def test_prints_each_message_no_sentinel(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("llm_prompts.cli._collect_update_messages", return_value=["a", "b"]):
            result = _check_for_updates()
        assert result is True
        assert capsys.readouterr().out == "a\nb\n"
