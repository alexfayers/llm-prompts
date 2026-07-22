"""Tests for the uninstall CLI subcommand wiring."""

from __future__ import annotations

from unittest.mock import patch

from llm_prompts.cli import main


def test_uninstall_dispatches_single_agent() -> None:
    with patch("sys.argv", ["llm-prompts", "uninstall", "kiro"]):
        with patch("llm_prompts.install.uninstall") as mock_uninstall:
            main()
    mock_uninstall.assert_called_once_with(["kiro"], verbose=False)


def test_uninstall_all_dispatches_none() -> None:
    with patch("sys.argv", ["llm-prompts", "uninstall", "all"]):
        with patch("llm_prompts.install.uninstall") as mock_uninstall:
            main()
    mock_uninstall.assert_called_once_with(None, verbose=False)


def test_uninstall_passes_verbose_flag() -> None:
    with patch("sys.argv", ["llm-prompts", "uninstall", "kiro", "--verbose"]):
        with patch("llm_prompts.install.uninstall") as mock_uninstall:
            main()
    mock_uninstall.assert_called_once_with(["kiro"], verbose=True)
