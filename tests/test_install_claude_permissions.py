"""Tests for seeding default Claude Code permissions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from llm_prompts import manifest
from llm_prompts.install import (
    _claude_default_permissions,
    _seed_claude_permissions,
    prompts_dir,
    uninstall,
)
from llm_prompts.install import main as install_main
from llm_prompts.manifest import (
    ClaudePermissionState,
    read_manifest,
    record_claude_permissions,
    write_manifest,
)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    return home


def _defaults(directory: Path, **lists: list[str]) -> Path:
    path = directory / "claude-code" / "permissions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lists), encoding="utf-8")
    return directory


def _permissions(home: Path) -> dict[str, list[str]]:
    settings = json.loads((home / ".claude" / "settings.json").read_text("utf-8"))
    permissions: dict[str, list[str]] = settings["permissions"]
    return permissions


def _state(
    home: Path, owned: dict[str, list[str]], pending: dict[str, list[str]]
) -> dict[str, ClaudePermissionState]:
    settings = (home / ".claude" / "settings.json").resolve()
    return {str(settings): {"owned": owned, "pending": pending}}


def _without_digest(
    states: dict[str, ClaudePermissionState],
) -> dict[str, ClaudePermissionState]:
    return {
        path: {"owned": state["owned"], "pending": state["pending"]}
        for path, state in states.items()
    }


def _owned(home: Path, **rules: list[str]) -> dict[str, ClaudePermissionState]:
    return _state(home, rules, {})


def _write_settings(home: Path, settings: object) -> None:
    (home / ".claude" / "settings.json").write_text(json.dumps(settings), "utf-8")


class TestSeedClaudePermissions:
    def test_adds_missing_entries_and_keeps_the_users(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)"], ask=["Bash(rm *)"])
        _write_settings(home, {"model": "opus", "permissions": {"allow": ["Bash(x)"]}})

        with patch("llm_prompts.install.Path.home", return_value=home):
            added = _seed_claude_permissions([core], None)

        assert _permissions(home) == {
            "allow": ["Bash(x)", "Bash(ls *)"],
            "ask": ["Bash(rm *)"],
        }
        assert added == _owned(home, allow=["Bash(ls *)"], ask=["Bash(rm *)"])
        settings = json.loads((home / ".claude" / "settings.json").read_text("utf-8"))
        assert settings["model"] == "opus"

    def test_creates_the_settings_file_and_merges_overlays(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)"])
        overlay = _defaults(
            tmp_path / "overlay", allow=["Bash(ls *)", "Bash(wc *)"], deny=["Bash(x)"]
        )

        with patch("llm_prompts.install.Path.home", return_value=home):
            added = _seed_claude_permissions([core, overlay], None)

        assert _permissions(home) == {
            "allow": ["Bash(ls *)", "Bash(wc *)"],
            "deny": ["Bash(x)"],
        }
        assert added == _owned(home, **_permissions(home))

    def test_skips_a_rule_the_user_lists_in_another_list(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)"])
        _write_settings(home, {"permissions": {"deny": ["Bash(ls *)"]}})

        with patch("llm_prompts.install.Path.home", return_value=home):
            added = _seed_claude_permissions([core], None)

        assert _permissions(home) == {"deny": ["Bash(ls *)"]}
        assert added is None

    def test_does_not_add_a_rule_the_user_removed(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)", "Bash(wc *)"])
        _write_settings(home, {"permissions": {"allow": ["Bash(wc *)"]}})

        with patch("llm_prompts.install.Path.home", return_value=home):
            added = _seed_claude_permissions([core], _owned(home, allow=["Bash(ls *)"]))

        assert _permissions(home) == {"allow": ["Bash(wc *)"]}
        assert added == _owned(home, allow=["Bash(ls *)"])

    def test_writes_through_a_symlink(self, home: Path, tmp_path: Path) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)"])
        target = tmp_path / "dotfiles" / "settings.json"
        target.parent.mkdir()
        target.write_text("{}", encoding="utf-8")
        link = home / ".claude" / "settings.json"
        link.symlink_to(target)

        with patch("llm_prompts.install.Path.home", return_value=home):
            _seed_claude_permissions([core], None)

        assert link.is_symlink()
        assert json.loads(target.read_text("utf-8")) == {
            "permissions": {"allow": ["Bash(ls *)"]}
        }

    def test_unparseable_settings_are_left_alone(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)"])
        settings = home / ".claude" / "settings.json"
        settings.write_text("{oops", encoding="utf-8")

        with patch("llm_prompts.install.Path.home", return_value=home):
            previous = _owned(home, allow=["Bash(old)"])
            added = _seed_claude_permissions([core], previous)

        assert settings.read_text("utf-8") == "{oops"
        assert added == previous


class TestInstallAndUninstall:
    def test_install_records_added_rules_and_uninstall_removes_only_those(
        self, home: Path, tmp_path: Path
    ) -> None:
        overlay = _defaults(tmp_path / "overlay", allow=["Bash(ls *)", "Bash(wc *)"])
        _write_settings(home, {"permissions": {"allow": ["Bash(wc *)", "Bash(mine)"]}})

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths", return_value=[overlay]
            ),
        ):
            install_main(["claude-code"])

            assert "Bash(ls *)" in _permissions(home)["allow"]
            assert read_manifest()["claude-code"]["claude_permissions"] == _owned(
                home, allow=["Bash(ls *)"]
            )

            uninstall(["claude-code"])

        assert _permissions(home)["allow"] == ["Bash(wc *)", "Bash(mine)"]

    def test_uninstall_after_a_symlink_change_cleans_the_old_target_only(
        self, home: Path, tmp_path: Path
    ) -> None:
        overlay = _defaults(tmp_path / "overlay", allow=["Bash(ls *)"])
        first = tmp_path / "first.json"
        second = tmp_path / "second.json"
        first.write_text("{}", encoding="utf-8")
        second.write_text(
            json.dumps({"permissions": {"allow": ["Bash(ls *)"]}}), encoding="utf-8"
        )
        link = home / ".claude" / "settings.json"
        link.symlink_to(first)

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths", return_value=[overlay]
            ),
        ):
            install_main(["claude-code"])
            link.unlink()
            link.symlink_to(second)

            uninstall(["claude-code"])

        assert json.loads(first.read_text("utf-8"))["permissions"] == {"allow": []}
        assert json.loads(second.read_text("utf-8")) == {
            "permissions": {"allow": ["Bash(ls *)"]}
        }

    def test_uninstall_skips_a_recorded_path_that_became_a_symlink(
        self, home: Path, tmp_path: Path
    ) -> None:
        overlay = _defaults(tmp_path / "overlay", allow=["Bash(ls *)"])
        other = tmp_path / "other.json"
        other.write_text(
            json.dumps({"permissions": {"allow": ["Bash(ls *)"]}}), encoding="utf-8"
        )
        settings = home / ".claude" / "settings.json"

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths", return_value=[overlay]
            ),
        ):
            install_main(["claude-code"])
            recorded = _owned(home, allow=["Bash(ls *)"])
            settings.unlink()
            settings.symlink_to(other)

            uninstall(["claude-code"])

        assert settings.is_symlink()
        assert json.loads(other.read_text("utf-8")) == {
            "permissions": {"allow": ["Bash(ls *)"]}
        }
        assert read_manifest()["claude-code"]["claude_permissions"] == recorded

    def test_uninstall_keeps_the_record_of_unparseable_settings_for_a_retry(
        self, home: Path, tmp_path: Path
    ) -> None:
        overlay = _defaults(tmp_path / "overlay", allow=["Bash(ls *)"])
        settings = home / ".claude" / "settings.json"

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths", return_value=[overlay]
            ),
        ):
            install_main(["claude-code"])
            good = settings.read_text("utf-8")
            settings.write_text("{oops", encoding="utf-8")

            uninstall(["claude-code"])
            assert read_manifest()["claude-code"]["claude_permissions"] == _owned(
                home, allow=["Bash(ls *)"]
            )

            settings.write_text(good, encoding="utf-8")
            uninstall(["claude-code"])

        assert _permissions(home)["allow"] == []
        assert "claude-code" not in read_manifest()

    def test_uninstall_settles_pending_rules_before_removing_the_update_rule(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)"])
        _write_settings(
            home, {"permissions": {"allow": ["Bash(llm-prompts update *)"]}}
        )
        calls: list[object] = []

        def record_then_interrupt(states: object) -> None:
            calls.append(states)
            if len(calls) == 2:
                raise KeyboardInterrupt
            record_claude_permissions(states)  # type: ignore[arg-type]

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.manifest.record_claude_permissions",
                side_effect=record_then_interrupt,
            ),
            pytest.raises(KeyboardInterrupt),
        ):
            _seed_claude_permissions([core], None)

        with patch("llm_prompts.install.Path.home", return_value=home):
            uninstall(["claude-code"])

        assert _permissions(home)["allow"] == []

    def test_uninstall_replaces_the_entry_with_retry_records_in_one_write(
        self, home: Path, tmp_path: Path
    ) -> None:
        overlay = _defaults(tmp_path / "overlay", allow=["Bash(ls *)"])
        settings = home / ".claude" / "settings.json"
        saves: list[int] = []
        real_save = manifest._save

        def second_save_fails(agents: object) -> None:
            saves.append(1)
            if len(saves) == 2:
                raise OSError("disk")
            real_save(agents)  # type: ignore[arg-type]

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths", return_value=[overlay]
            ),
        ):
            install_main(["claude-code"])
            recorded = _owned(home, allow=["Bash(ls *)"])
            settings.write_text("{oops", encoding="utf-8")
            saves.clear()
            with patch("llm_prompts.manifest._save", side_effect=second_save_fails):
                uninstall(["claude-code"])

        assert read_manifest()["claude-code"]["claude_permissions"] == recorded

    def test_uninstall_leaves_a_file_alone_when_its_cleanup_failed(
        self, home: Path, tmp_path: Path
    ) -> None:
        overlay = _defaults(tmp_path / "overlay", allow=["Bash(ls *)"])
        settings = home / ".claude" / "settings.json"

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths", return_value=[overlay]
            ),
        ):
            install_main(["claude-code"])
            recorded = _owned(home, allow=["Bash(ls *)"])
            _write_settings(
                home,
                {
                    "permissions": {
                        "allow": ["Bash(ls *)", "Bash(llm-prompts update *)"]
                    }
                },
            )
            before = settings.read_text("utf-8")
            with patch(
                "llm_prompts.install.write_text_atomic", side_effect=OSError("ro")
            ):
                uninstall(["claude-code"])

        assert settings.read_text("utf-8") == before
        assert read_manifest()["claude-code"]["claude_permissions"] == recorded

    def test_update_after_a_symlink_change_keeps_ownership_of_the_old_target(
        self, home: Path, tmp_path: Path
    ) -> None:
        overlay = _defaults(tmp_path / "overlay", allow=["Bash(ls *)"])
        first = tmp_path / "first.json"
        second = tmp_path / "second.json"
        first.write_text("{}", encoding="utf-8")
        second.write_text("{}", encoding="utf-8")
        link = home / ".claude" / "settings.json"
        link.symlink_to(first)

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths", return_value=[overlay]
            ),
        ):
            install_main(["claude-code"])
            link.unlink()
            link.symlink_to(second)
            install_main(["claude-code"])

            assert set(read_manifest()["claude-code"]["claude_permissions"]) == {
                str(first.resolve()),
                str(second.resolve()),
            }

            uninstall(["claude-code"])

        for target in (first, second):
            assert json.loads(target.read_text("utf-8"))["permissions"] == {"allow": []}

    def test_a_failed_manifest_write_leaves_the_rules_owned(
        self, home: Path, tmp_path: Path
    ) -> None:
        overlay = _defaults(tmp_path / "overlay", allow=["Bash(ls *)"])

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths", return_value=[overlay]
            ),
            patch("llm_prompts.manifest.write_manifest", side_effect=OSError("disk")),
        ):
            install_main(["claude-code"])

        assert _permissions(home)["allow"] == ["Bash(ls *)"]
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install._discover_overlay_paths", return_value=[overlay]
            ),
        ):
            install_main(["claude-code"])
            uninstall(["claude-code"])

        assert _permissions(home)["allow"] == []

    def test_a_failed_settings_write_records_nothing(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)"])

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install.write_text_atomic", side_effect=OSError("ro")),
        ):
            added = _seed_claude_permissions([core], None)

        assert added is None
        assert "claude_permissions" not in read_manifest().get("claude-code", {})


class TestInterruptedSeeding:
    def test_a_rule_never_written_is_not_owned_after_the_next_run(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)"])
        write_manifest("claude-code", [])

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install.write_text_atomic", side_effect=KeyboardInterrupt
            ),
            pytest.raises(KeyboardInterrupt),
        ):
            _seed_claude_permissions([core], None)

        recorded = read_manifest()["claude-code"]["claude_permissions"]
        assert _without_digest(recorded) == _state(home, {}, {"allow": ["Bash(ls *)"]})

        with patch("llm_prompts.install.Path.home", return_value=home):
            settled = _seed_claude_permissions([tmp_path / "none"], recorded)

        assert settled is None

    def test_a_matching_rule_the_user_adds_after_the_interruption_is_not_claimed(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)"])
        write_manifest("claude-code", [])

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch(
                "llm_prompts.install.write_text_atomic", side_effect=KeyboardInterrupt
            ),
            pytest.raises(KeyboardInterrupt),
        ):
            _seed_claude_permissions([core], None)
        recorded = read_manifest()["claude-code"]["claude_permissions"]
        _write_settings(home, {"permissions": {"allow": ["Bash(ls *)"]}})

        with patch("llm_prompts.install.Path.home", return_value=home):
            settled = _seed_claude_permissions([core], recorded)

        assert settled is None

    def test_a_rule_written_before_the_interruption_is_owned_after_the_next_run(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(ls *)"])
        calls: list[object] = []

        def record_then_interrupt(states: object) -> None:
            calls.append(states)
            if len(calls) == 2:
                raise KeyboardInterrupt
            record_claude_permissions(states)  # type: ignore[arg-type]

        write_manifest("claude-code", [])
        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.manifest.record_claude_permissions") as patched,
            pytest.raises(KeyboardInterrupt),
        ):
            patched.side_effect = record_then_interrupt
            _seed_claude_permissions([core], None)

        recorded = read_manifest()["claude-code"]["claude_permissions"]
        assert _without_digest(recorded) == _state(home, {}, {"allow": ["Bash(ls *)"]})

        with patch("llm_prompts.install.Path.home", return_value=home):
            settled = _seed_claude_permissions([core], recorded)

        assert settled == _owned(home, allow=["Bash(ls *)"])


class TestDefaultListConflicts:
    def test_a_rule_goes_to_the_strictest_list_that_declares_it(
        self, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", allow=["Bash(a)", "Bash(b)"])
        overlay = _defaults(tmp_path / "overlay", ask=["Bash(a)"], deny=["Bash(b)"])

        assert _claude_default_permissions([core, overlay]) == {
            "deny": ["Bash(b)"],
            "ask": ["Bash(a)"],
            "allow": [],
        }

    def test_a_default_moved_between_lists_is_not_restored(
        self, home: Path, tmp_path: Path
    ) -> None:
        core = _defaults(tmp_path / "core", ask=["Bash(ls *)"])
        _write_settings(home, {})

        with patch("llm_prompts.install.Path.home", return_value=home):
            added = _seed_claude_permissions([core], _owned(home, allow=["Bash(ls *)"]))

        settings = home / ".claude" / "settings.json"
        assert json.loads(settings.read_text("utf-8")) == {}
        assert added == _owned(home, allow=["Bash(ls *)"])


def test_shipped_defaults_list_each_rule_once() -> None:
    shipped = _claude_default_permissions([prompts_dir("llm_prompts")])

    rules = [rule for name in ("allow", "ask", "deny") for rule in shipped[name]]
    assert shipped["allow"]
    assert len(rules) == len(set(rules))
