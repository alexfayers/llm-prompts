"""Tests for the interactive settings editor."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, Input, Static

from llm_prompts.config_edit import load_doc
from llm_prompts.settings_app import SettingsApp

_TOOL = '[[tools]]\nname = "a"\nsource = "https://github.com/example/a.git"\n'


def _write_config(config_dir: Path, text: str) -> Path:
    path = config_dir / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_switching_a_setting_and_saving_keeps_the_rest_of_the_file(
    isolated_config_dir: Path,
) -> None:
    path = _write_config(
        isolated_config_dir,
        f'# my tools\n{_TOOL}\n[update]\nauto = true  # keep me\n\n[pi]\nruntime = "node"\n',
    )

    async def edit() -> None:
        app = SettingsApp(load_doc())
        async with app.run_test() as pilot:
            await pilot.click("#update-auto")
            await pilot.click("#review")
            await pilot.click("#save")
        assert app.return_value is True

    asyncio.run(edit())

    assert path.read_text(encoding="utf-8") == (
        f'# my tools\n{_TOOL}\n[update]\nauto = false  # keep me\n\n[pi]\nruntime = "node"\n'
    )
    assert len(list(isolated_config_dir.glob("config.toml.bak-*"))) == 1


def _review(*steps: tuple[str, str]) -> str:
    """Run the editor, apply ``steps`` of (widget id, typed text), open the review and return its text."""

    async def edit() -> str:
        app = SettingsApp(load_doc())
        async with app.run_test() as pilot:
            for widget_id, text in steps:
                app.query_one(widget_id, Input).value = text
            await pilot.click("#review")
            await pilot.pause()
            saves = app.screen.query("#save").results(Button)
            return "\n".join(
                [str(static.render()) for static in app.screen.query(Static)]
                + [f"save disabled: {save.disabled}" for save in saves]
            )

    return asyncio.run(edit())


def test_an_invalid_value_blocks_the_save(isolated_config_dir: Path) -> None:
    path = _write_config(isolated_config_dir, _TOOL)

    screen = _review(("#benchmark-jobs", "0"))

    assert "benchmark.jobs must be at least 1\n" in screen
    assert "got 0" not in screen
    assert screen.endswith("save disabled: True")
    assert path.read_text(encoding="utf-8") == _TOOL


def test_the_review_shows_only_the_edited_settings(
    isolated_config_dir: Path,
) -> None:
    _write_config(
        isolated_config_dir,
        '[[tools]]\nname = "a"\nsource = "https://example.com/a.git"\n'
        'token = "hunter2"\n[update]\nauto = 1\n[reviews]\nmax_in_flight = 3\n',
    )

    screen = _review(("#reviews-max_in_flight", ""), ("#benchmark-jobs", "2"))

    assert screen.startswith(
        "reviews.max_in_flight = 5 (default)\nbenchmark.jobs = 2\n"
    )
    assert "hunter2" not in screen
    assert "update.auto" not in screen
    assert screen.endswith("save disabled: False")


def test_other_config_errors_block_the_save_without_their_values(
    isolated_config_dir: Path,
) -> None:
    _write_config(
        isolated_config_dir,
        '[[tools]]\nname = "a"\nsource = "./no-such-dir-hunter2"\n'
        '[[tools]]\nname = "b"\nsource = "pypi-hunter2"\n'
        '[[tools]]\nname = "c"\nsource = 5\n'
        '[[plugins]]\nname = "p"\nsource = "plain-hunter2"\n'
        '[[plugins]]\nsource = "https://example.com/hunter2.git"\n'
        '[[plugins]]\nname = "q"\nsource = "https://example.com/q.git"\n'
        '[plugins.frontmatter_overrides.s]\nkey = ["hunter2"]\n'
        '[reviews]\nmax_in_flight = 3\n[benchmark]\njobs = "hunter2"\n',
    )

    screen = _review(("#reviews-max_in_flight", "4"))

    assert screen == (
        "reviews.max_in_flight = 4\n"
        "[[tools]] entry 1: source is invalid\n"
        "[[tools]] entry 2: source is invalid\n"
        "[[tools]] entry 3: source is invalid\n"
        "[[plugins]] entry 1: source is invalid\n"
        "[[plugins]] entry 2: name is invalid\n"
        "[[plugins]] entry 3: frontmatter_overrides is invalid\n"
        "benchmark.jobs must be at least 1\n"
        "save disabled: True"
    )


@pytest.mark.parametrize("text", ["-", "--1"])
def test_a_number_field_that_is_not_a_number_stays_on_the_editor(
    isolated_config_dir: Path, text: str
) -> None:
    _write_config(isolated_config_dir, f"{_TOOL}[benchmark]\njobs = 3\n")

    screen = _review(("#benchmark-jobs", text))

    assert "benchmark.jobs must be a whole number" in screen
    assert "save disabled" not in screen


def test_a_failed_write_keeps_the_editor_open(
    isolated_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_config(isolated_config_dir, _TOOL)

    def fail(*_: object) -> None:
        raise PermissionError(13, "Permission denied", "/secret/path")

    monkeypatch.setattr("llm_prompts.config_edit.write_text_atomic", fail)

    async def edit() -> None:
        app = SettingsApp(load_doc())
        async with app.run_test() as pilot:
            await pilot.click("#telemetry-enabled")
            await pilot.press("ctrl+s", "ctrl+s")
            await pilot.pause()
            assert app.is_running
            assert str(app.screen.query_one("#errors", Static).render()) == (
                f"Could not save {path}: Permission denied"
            )

    asyncio.run(edit())

    assert path.read_text(encoding="utf-8") == _TOOL


def test_a_save_after_the_file_changed_keeps_the_newer_file(
    isolated_config_dir: Path,
) -> None:
    path = _write_config(isolated_config_dir, _TOOL)
    newer = f"{_TOOL}[update]\nauto = true\n"

    async def edit() -> None:
        app = SettingsApp(load_doc())
        async with app.run_test() as pilot:
            await pilot.click("#telemetry-enabled")
            await pilot.click("#review")
            path.write_text(newer, encoding="utf-8")
            await pilot.click("#save")
            await pilot.pause()
            assert "changed since it was loaded" in str(
                app.screen.query_one("#errors", Static).render()
            )

    asyncio.run(edit())

    assert path.read_text(encoding="utf-8") == newer


def test_keys_open_the_review_and_save(isolated_config_dir: Path) -> None:
    path = _write_config(isolated_config_dir, _TOOL)

    async def edit() -> None:
        app = SettingsApp(load_doc())
        async with app.run_test() as pilot:
            await pilot.click("#telemetry-enabled")
            await pilot.press("ctrl+s", "ctrl+s")
        assert app.return_value is True

    asyncio.run(edit())

    assert (
        path.read_text(encoding="utf-8") == f"{_TOOL}\n[telemetry]\nenabled = false\n"
    )


def _save(*steps: tuple[str, str]) -> None:
    """Run the editor, type ``steps`` of (widget id, text), then review and save."""

    async def edit() -> None:
        app = SettingsApp(load_doc())
        async with app.run_test() as pilot:
            for widget_id, text in steps:
                app.query_one(widget_id, Input).value = text
            await pilot.press("ctrl+s", "ctrl+s")
        assert app.return_value is True

    asyncio.run(edit())


def test_editing_the_per_repo_review_limits_keeps_the_other_keys(
    isolated_config_dir: Path,
) -> None:
    path = _write_config(
        isolated_config_dir,
        f'{_TOOL}[reviews]\nmax_in_flight = 3\n[reviews.repos]\n"o/a" = 1\n"o/b" = 2\n',
    )

    assert "reviews.repos = o/a=4, o/c=2" in _review(("#reviews-repos", "o/a=4, o/c=2"))
    _save(("#reviews-repos", "o/a=4, o/c=2"))

    assert path.read_text(encoding="utf-8") == (
        f'{_TOOL}[reviews]\nmax_in_flight = 3\n[reviews.repos]\n"o/a" = 4\n"o/c" = 2\n'
    )


def test_a_per_repo_limit_that_is_not_a_number_stays_on_the_editor(
    isolated_config_dir: Path,
) -> None:
    _write_config(isolated_config_dir, _TOOL)

    screen = _review(("#reviews-repos", "o/a=x"))

    assert "reviews.repos must be scope=number pairs" in screen
    assert "save disabled" not in screen


_TWO_TOOLS = (
    '[[tools]]\nname = "a"  # first\nsource = "https://github.com/example/a.git"\n\n'
    '[[tools]]\nname = "b"\nsource = "https://github.com/example/b.git"\n'
    'token = "hunter2"\n\n[update]\nauto = true\n'
)


def _edit_entries(table: str, *steps: tuple[str, str]) -> str:
    """Open the ``table`` screen, run ``steps`` and open the review.

    Each step is ("type", "<widget id>=<text>") or ("click", "<widget id>").
    Returns the review's text.
    """

    async def edit() -> str:
        app = SettingsApp(load_doc())
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.click(f"#{table}")
            for action, arg in steps:
                if action == "click":
                    await pilot.click(arg)
                else:
                    widget_id, _, text = arg.partition("=")
                    app.screen.query_one(widget_id, Input).value = text
                await pilot.pause()
            await pilot.press("escape")
            await pilot.click("#review")
            await pilot.pause()
            text = "\n".join(str(s.render()) for s in app.screen.query(Static))
            await pilot.press("ctrl+s")
        return text

    return asyncio.run(edit())


def test_tools_can_be_edited_added_moved_and_removed(
    isolated_config_dir: Path,
) -> None:
    path = _write_config(isolated_config_dir, _TWO_TOOLS)

    screen = _edit_entries(
        "tools",
        ("type", "#tools-1-ref=v1.2.0"),
        ("click", "#up-1"),
        ("click", "#add"),
        ("type", "#tools-2-name=c"),
        ("type", "#tools-2-source=https://github.com/example/c.git"),
        ("click", "#remove-1"),
    )

    assert "[[tools]] = b, c\nb: ref changed\nc: added" in screen
    assert "hunter2" not in screen
    assert "github.com" not in screen
    assert path.read_text(encoding="utf-8") == (
        '[[tools]]\nname = "b"\nsource = "https://github.com/example/b.git"\n'
        'token = "hunter2"\nref = "v1.2.0"\n\n\n'
        '[[tools]]\nname = "c"\nsource = "https://github.com/example/c.git"\n\n'
        "[update]\nauto = true\n"
    )


def test_plugin_skills_are_saved_as_a_list_and_overrides_are_kept(
    isolated_config_dir: Path,
) -> None:
    plugin = (
        '[[plugins]]\nname = "p"\nsource = "https://github.com/example/p.git"\n'
        '[plugins.frontmatter_overrides.s]\nkey = "v"\n'
    )
    path = _write_config(isolated_config_dir, f"{_TOOL}\n{plugin}")

    screen = _edit_entries("plugins", ("type", "#plugins-0-skills=s, t"))

    assert "[[plugins]] = p\np: skills changed" in screen
    assert path.read_text(encoding="utf-8") == (
        f'{_TOOL}\n[[plugins]]\nname = "p"\nsource = "https://github.com/example/p.git"\n'
        'skills = ["s", "t"]\n\n[plugins.frontmatter_overrides.s]\nkey = "v"\n'
    )


def test_a_new_entry_without_a_source_blocks_the_save(
    isolated_config_dir: Path,
) -> None:
    path = _write_config(isolated_config_dir, _TOOL)

    screen = _edit_entries("plugins", ("click", "#add"), ("type", "#plugins-0-name=p"))

    assert "[[plugins]] entry 1: source is invalid" in screen
    assert path.read_text(encoding="utf-8") == _TOOL
