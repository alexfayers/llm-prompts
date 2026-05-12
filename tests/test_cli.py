"""Tests for CLI update check functionality."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock


from llm_prompts.cli import _extract_git_url, _get_installed_commit, _check_remote_source


class TestExtractGitUrl:
    def test_git_plus_https(self) -> None:
        assert _extract_git_url("git+https://github.com/user/repo.git") == "https://github.com/user/repo.git"

    def test_git_plus_ssh(self) -> None:
        assert _extract_git_url("git+ssh://git@github.com/user/repo.git") == "ssh://git@github.com/user/repo.git"

    def test_plain_https(self) -> None:
        assert _extract_git_url("https://github.com/user/repo.git") == "https://github.com/user/repo.git"

    def test_local_path(self) -> None:
        assert _extract_git_url("~/git/llm-prompts") is None

    def test_relative_path(self) -> None:
        assert _extract_git_url("./local-package") is None

    def test_pypi_name(self) -> None:
        assert _extract_git_url("some-package") is None


class TestGetInstalledCommit:
    def test_finds_commit_from_vcs_info(self, tmp_path: Path) -> None:
        dist_info = tmp_path / "llm-prompts" / "lib" / "python3.14" / "site-packages" / "my_tool-0.1.0.dist-info"
        dist_info.mkdir(parents=True)
        direct_url = dist_info / "direct_url.json"
        direct_url.write_text(json.dumps({
            "url": "https://github.com/user/repo.git",
            "vcs_info": {
                "vcs": "git",
                "commit_id": "abc123def456",
            },
        }))

        with patch("llm_prompts.cli.Path.home", return_value=tmp_path / "fake_home"):
            uv_tools = tmp_path / "fake_home" / ".local" / "share" / "uv" / "tools"
            uv_tools.mkdir(parents=True)
            (uv_tools / "my-tool").symlink_to(tmp_path / "llm-prompts")

            result = _get_installed_commit("my-tool")
            assert result == "abc123def456"

    def test_returns_none_for_editable_install(self, tmp_path: Path) -> None:
        dist_info = tmp_path / "my-tool" / "lib" / "python3.14" / "site-packages" / "my_tool-0.1.0.dist-info"
        dist_info.mkdir(parents=True)
        direct_url = dist_info / "direct_url.json"
        direct_url.write_text(json.dumps({
            "url": "file:///Users/someone/git/my-tool",
            "dir_info": {"editable": True},
        }))

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


class TestCheckRemoteSource:
    def test_not_a_git_url(self) -> None:
        assert _check_remote_source("pkg", "some-pypi-package") is False

    def test_not_installed(self) -> None:
        with patch("llm_prompts.cli._get_installed_commit", return_value=None):
            result = _check_remote_source("pkg", "git+https://github.com/user/repo.git")
            assert result is True

    def test_up_to_date(self) -> None:
        with patch("llm_prompts.cli._get_installed_commit", return_value="abc123"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="abc123\tHEAD\n",
                )
                result = _check_remote_source("pkg", "git+https://github.com/user/repo.git")
                assert result is False

    def test_update_available(self) -> None:
        with patch("llm_prompts.cli._get_installed_commit", return_value="abc123aa"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="def456bb\tHEAD\n",
                )
                result = _check_remote_source("pkg", "git+https://github.com/user/repo.git")
                assert result is True

    def test_ls_remote_fails(self) -> None:
        with patch("llm_prompts.cli._get_installed_commit", return_value="abc123"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=128,
                    stdout="",
                )
                result = _check_remote_source("pkg", "git+https://github.com/user/repo.git")
                assert result is False
