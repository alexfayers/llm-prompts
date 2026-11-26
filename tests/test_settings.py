"""Tests for the settings command."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from conftest import run_capturing_exit

from llm_prompts.cli import main


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int | str | None:
    monkeypatch.setattr(sys, "argv", ["llm-prompts", "settings", *args])
    return run_capturing_exit(main)


def _write_config(config_dir: Path, text: str) -> None:
    (config_dir / "config.toml").write_text(text, encoding="utf-8")


def test_check_prints_values_with_defaults(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(
        isolated_config_dir,
        '[[tools]]\nname = "llm-prompts"\nsource = "https://github.com/example/a.git"\n'
        '[update]\nauto = false\n[reviews.repos]\n"example/a" = 2\n'
        '[pi]\nruntime = "node"\n',
    )

    assert _run(monkeypatch, "--check") in (None, 0)

    out = capsys.readouterr().out
    assert out == (
        f"Config: {isolated_config_dir / 'config.toml'}\n"
        "\n"
        "Tools:\n"
        "  llm-prompts  https://github.com/example/a.git\n"
        "Plugins: none\n"
        "\n"
        "update.auto = false\n"
        "telemetry.enabled = true (default)\n"
        "reviews.max_in_flight = 5 (default)\n"
        "reviews.repos.example/a = 2\n"
        "benchmark.jobs = 4 (default)\n"
    )


def test_check_lists_errors_and_exits_nonzero(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(isolated_config_dir, "[update]\nauto = true\n")

    assert _run(monkeypatch, "--check") == 1

    captured = capsys.readouterr()
    assert "Tools: none\n" in captured.out
    assert captured.err == "Config must contain at least one [[tools]] entry.\n"


def test_check_reports_a_missing_config(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(monkeypatch, "--check") == 1

    assert capsys.readouterr().err == (
        "Config must contain at least one [[tools]] entry.\n"
    )


def test_check_reports_invalid_toml(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(isolated_config_dir, "[tools")

    result = _run(monkeypatch, "--check")

    assert isinstance(result, str)
    assert "is not valid TOML" in result


def test_without_a_terminal_it_prints_the_report(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(isolated_config_dir, "[update]\nauto = true\n")

    assert _run(monkeypatch) == 1

    assert capsys.readouterr().out.startswith("Config: ")


def test_interactive_without_the_extra_says_how_to_install_it(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("llm_prompts.settings._has_terminal", lambda: True)
    monkeypatch.setitem(sys.modules, "textual", None)

    result = _run(monkeypatch)

    assert result == (
        "The settings editor needs the llm-prompts[tui] extra, which adds textual. "
        "Run `llm-prompts settings --check` to print the config instead."
    )


def test_check_redacts_credentials_in_sources_and_errors(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(
        isolated_config_dir,
        '[[tools]]\nname = "a"\nsource = "https://user:hunter2@example.com/a.git"\n'
        '[[tools]]\nname = "b"\nsource = "ssh://git@example.com/b.git"\n'
        '[[tools]]\nname = "c"\nsource = "https://example.com/c.git?access_token=s3cret"\n'
        '[[plugins]]\nname = "p"\nsource = "ftp://tok3n@example.com/p"\n',
    )

    assert _run(monkeypatch, "--check") == 1

    captured = capsys.readouterr()
    assert "  a  https://<redacted>@example.com/a.git\n" in captured.out
    assert "  b  ssh://git@example.com/b.git\n" in captured.out
    assert "hunter2" not in captured.out + captured.err
    assert "tok3n" not in captured.out + captured.err
    assert "  c  https://example.com/c.git?<redacted>\n" in captured.out
    assert "s3cret" not in captured.out + captured.err
    assert "ftp://<redacted>@example.com/p" in captured.err


def test_check_rejects_a_benchmark_value_that_is_not_a_table(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_config(
        isolated_config_dir,
        "benchmark = false\n"
        '[[tools]]\nname = "a"\nsource = "https://github.com/example/a.git"\n',
    )

    assert _run(monkeypatch, "--check") == 1

    assert "[benchmark] must be a table" in capsys.readouterr().err


@pytest.mark.parametrize("jobs", ["0", "-1", '"4"'])
def test_check_rejects_benchmark_jobs_below_one(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    jobs: str,
) -> None:
    _write_config(
        isolated_config_dir,
        '[[tools]]\nname = "a"\nsource = "https://github.com/example/a.git"\n'
        f"[benchmark]\njobs = {jobs}\n",
    )

    assert _run(monkeypatch, "--check") == 1

    assert "benchmark.jobs must be at least 1, got" in capsys.readouterr().err


def test_in_a_terminal_it_opens_the_editor(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from llm_prompts.settings_app import SettingsApp

    opened: list[SettingsApp] = []
    monkeypatch.setattr("llm_prompts.settings._has_terminal", lambda: True)
    monkeypatch.setattr(SettingsApp, "run", lambda app: opened.append(app))

    assert _run(monkeypatch) in (None, 0)

    assert len(opened) == 1
    assert capsys.readouterr().out == ""


def test_in_a_terminal_invalid_toml_exits_without_the_editor(
    isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(isolated_config_dir, "[tools")
    monkeypatch.setattr("llm_prompts.settings._has_terminal", lambda: True)

    result = _run(monkeypatch)

    assert isinstance(result, str)
    assert "is not valid TOML" in result


def test_saving_changed_tools_or_plugins_says_how_to_install_them(
    isolated_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from llm_prompts.settings_app import SettingsApp

    def saved(app: SettingsApp) -> bool:
        app.entries_changed = True
        return True

    monkeypatch.setattr("llm_prompts.settings._has_terminal", lambda: True)
    monkeypatch.setattr(SettingsApp, "run", saved)

    assert _run(monkeypatch) in (None, 0)

    assert capsys.readouterr().out == (
        "Run `llm-prompts install <agent>` to install the changed tools and plugins.\n"
    )
