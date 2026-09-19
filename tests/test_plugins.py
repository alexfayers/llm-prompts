"""Tests for plugin-source cloning, discovery, and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeSubprocess

from llm_prompts import plugins, setup


class TestLoadPlugins:
    def test_no_config_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(setup, "CONFIG_PATH", tmp_path / "config.toml")
        assert plugins._load_plugins() == []

    def test_config_without_plugins_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "config.toml"
        config.write_text('[[tools]]\nname = "x"\nsource = "https://x.git"\n')
        monkeypatch.setattr(setup, "CONFIG_PATH", config)
        assert plugins._load_plugins() == []

    def test_config_with_plugins_returns_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "config.toml"
        config.write_text(
            '[[plugins]]\nname = "a"\nsource = "https://a.git"\n\n'
            '[[plugins]]\nname = "b"\nsource = "https://b.git"\n'
        )
        monkeypatch.setattr(setup, "CONFIG_PATH", config)
        result = plugins._load_plugins()
        assert [p["name"] for p in result] == ["a", "b"]


class TestValidatePlugins:
    def test_missing_name_is_error(self) -> None:
        errors = plugins._validate_plugins([{"source": "https://a.git"}])
        assert len(errors) == 1

    def test_non_git_source_is_error(self) -> None:
        errors = plugins._validate_plugins([{"name": "a", "source": "~/local/path"}])
        assert len(errors) == 1
        assert "a" in errors[0]

    def test_valid_git_url_has_no_errors(self) -> None:
        errors = plugins._validate_plugins(
            [{"name": "a", "source": "https://github.com/u/r.git"}]
        )
        assert errors == []

    def test_non_table_frontmatter_overrides_is_error(self) -> None:
        errors = plugins._validate_plugins(
            [
                {
                    "name": "a",
                    "source": "https://github.com/u/r.git",
                    "frontmatter_overrides": "nope",
                }
            ]
        )
        assert len(errors) == 1
        assert "frontmatter_overrides" in errors[0]

    def test_non_table_value_under_skill_name_is_error(self) -> None:
        errors = plugins._validate_plugins(
            [
                {
                    "name": "a",
                    "source": "https://github.com/u/r.git",
                    "frontmatter_overrides": {"skill-a": "nope"},
                }
            ]
        )
        assert len(errors) == 1
        assert "skill-a" in errors[0]

    def test_non_scalar_override_value_is_error(self) -> None:
        errors = plugins._validate_plugins(
            [
                {
                    "name": "a",
                    "source": "https://github.com/u/r.git",
                    "frontmatter_overrides": {"skill-a": {"key": [1, 2]}},
                }
            ]
        )
        assert len(errors) == 1
        assert "key" in errors[0]

    def test_str_bool_int_mix_scoped_to_one_skill_has_no_errors(self) -> None:
        errors = plugins._validate_plugins(
            [
                {
                    "name": "a",
                    "source": "https://github.com/u/r.git",
                    "frontmatter_overrides": {
                        "skill-a": {
                            "disable-model-invocation": False,
                            "description": "custom",
                            "priority": 1,
                        }
                    },
                }
            ]
        )
        assert errors == []


class TestStringifyOverride:
    def test_true_becomes_lowercase_true(self) -> None:
        assert plugins._stringify_override(True) == "true"

    def test_false_becomes_lowercase_false(self) -> None:
        assert plugins._stringify_override(False) == "false"

    def test_int_stringified(self) -> None:
        assert plugins._stringify_override(3) == "3"

    def test_str_passed_through(self) -> None:
        assert plugins._stringify_override("x") == "x"


def _make_skill(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text("# skill\n")


class TestDiscoverSkills:
    def test_single_skill_at_root_uses_checkout_name(self, tmp_path: Path) -> None:
        checkout = tmp_path / "i-have-adhd"
        checkout.mkdir()
        (checkout / "SKILL.md").write_text("# skill\n")
        result = plugins.discover_skills(checkout, None)
        assert result == [("i-have-adhd", checkout)]

    def test_nested_skills_use_leaf_names(self, tmp_path: Path) -> None:
        checkout = tmp_path / "repo"
        _make_skill(checkout / "skills" / "engineering" / "tdd")
        _make_skill(checkout / "skills" / "productivity" / "focus")
        result = plugins.discover_skills(checkout, None)
        names = sorted(name for name, _ in result)
        assert names == ["focus", "tdd"]

    def test_subset_filters_to_requested(self, tmp_path: Path) -> None:
        checkout = tmp_path / "repo"
        _make_skill(checkout / "skills" / "tdd")
        _make_skill(checkout / "skills" / "focus")
        result = plugins.discover_skills(checkout, ["tdd"])
        assert [name for name, _ in result] == ["tdd"]

    def test_unknown_subset_name_raises_listing_available(self, tmp_path: Path) -> None:
        checkout = tmp_path / "repo"
        _make_skill(checkout / "skills" / "tdd")
        with pytest.raises(ValueError) as excinfo:
            plugins.discover_skills(checkout, ["nope"])
        message = str(excinfo.value)
        assert "nope" in message
        assert "tdd" in message

    def test_duplicate_leaf_name_first_wins(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        checkout = tmp_path / "repo"
        _make_skill(checkout / "skills" / "a" / "tdd")
        _make_skill(checkout / "skills" / "b" / "tdd")
        result = plugins.discover_skills(checkout, None)
        assert result == [("tdd", checkout / "skills" / "a" / "tdd")]
        assert "Duplicate skill name 'tdd'" in capsys.readouterr().err

    def test_skill_outside_skills_dir_is_ignored(self, tmp_path: Path) -> None:
        checkout = tmp_path / "repo"
        _make_skill(checkout / "skills" / "tdd")
        _make_skill(checkout / ".cursor" / "skills" / "tdd")
        result = plugins.discover_skills(checkout, None)
        assert result == [("tdd", checkout / "skills" / "tdd")]

    def test_skills_dir_takes_precedence_over_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        checkout = tmp_path / "example-plugin"
        checkout.mkdir()
        (checkout / "SKILL.md").write_text("# root\n")
        _make_skill(checkout / "skills" / "example-plugin")
        result = plugins.discover_skills(checkout, None)
        assert result == [("example-plugin", checkout / "skills" / "example-plugin")]
        assert "Duplicate" not in capsys.readouterr().err

    def test_empty_skills_dir_falls_back_to_root(self, tmp_path: Path) -> None:
        checkout = tmp_path / "repo"
        (checkout / "skills").mkdir(parents=True)
        (checkout / "SKILL.md").write_text("# root\n")
        result = plugins.discover_skills(checkout, None)
        assert result == [("repo", checkout)]

    def test_symlinked_same_file_skipped_silently(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        checkout = tmp_path / "example-plugin"
        real = checkout / "skills" / "alpha" / "shared"
        _make_skill(real)
        alias = checkout / "skills" / "beta" / "shared"
        alias.mkdir(parents=True)
        (alias / "SKILL.md").symlink_to(real / "SKILL.md")
        result = plugins.discover_skills(checkout, None)
        assert result == [("shared", real)]
        assert "Duplicate" not in capsys.readouterr().err

    def test_different_names_same_file_both_kept(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        checkout = tmp_path / "example-plugin"
        real = checkout / "skills" / "alpha"
        _make_skill(real)
        alias = checkout / "skills" / "beta"
        alias.mkdir(parents=True)
        (alias / "SKILL.md").symlink_to(real / "SKILL.md")
        result = plugins.discover_skills(checkout, None)
        names = sorted(name for name, _ in result)
        assert names == ["alpha", "beta"]
        assert "Duplicate" not in capsys.readouterr().err


class TestEnsureCloned:
    def test_clones_when_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_subprocess: FakeSubprocess,
    ) -> None:
        upstream = tmp_path / "upstream"
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        plugin = {"name": "p", "source": f"git+file://{upstream}"}
        dest = plugins.ensure_cloned(plugin)
        assert dest is not None
        fake_subprocess.assert_sequence("clone")
        assert fake_subprocess.commands[0] == [
            "git",
            "clone",
            f"file://{upstream}",
            str(dest),
        ]

    def test_noop_when_already_cloned(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_subprocess: FakeSubprocess,
    ) -> None:
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        plugin = {"name": "p", "source": f"git+file://{tmp_path / 'upstream'}"}
        dest = plugins._checkout_dir("p")
        (dest / ".git").mkdir(parents=True)

        result = plugins.ensure_cloned(plugin)

        assert result == dest
        assert fake_subprocess.matching("clone") == []

    def test_returns_none_when_clone_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_subprocess: FakeSubprocess,
    ) -> None:
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        fake_subprocess.on("clone", returncode=1, stderr="fatal: repository not found")
        plugin = {"name": "p", "source": f"git+file://{tmp_path / 'does-not-exist'}"}
        assert plugins.ensure_cloned(plugin) is None


class TestPullPluginSources:
    def test_reset_hard_tracks_force_updated_upstream(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        upstream = tmp_path / "upstream"
        config = tmp_path / "config.toml"
        config.write_text(
            f'[[plugins]]\nname = "p"\nsource = "git+file://{upstream}"\n'
        )
        monkeypatch.setattr(setup, "CONFIG_PATH", config)
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        dest = plugins._checkout_dir("p")
        (dest / ".git").mkdir(parents=True)

        fake_subprocess.on(
            "rev-parse", "--short", "HEAD", stdout=["aaaaaaa\n", "bbbbbbb\n"]
        )
        fake_subprocess.on(
            "rev-parse", "--abbrev-ref", "origin/HEAD", stdout="origin/main\n"
        )

        plugins.pull_plugin_sources()

        fake_subprocess.assert_sequence(
            "rev-parse --short HEAD",
            "fetch",
            "rev-parse --abbrev-ref",
            "reset --hard",
            "rev-parse --short HEAD",
        )
        assert "[p] updated to bbbbbbb" in capsys.readouterr().out

    def test_no_output_when_already_up_to_date(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        upstream = tmp_path / "upstream"
        config = tmp_path / "config.toml"
        config.write_text(
            f'[[plugins]]\nname = "p"\nsource = "git+file://{upstream}"\n'
        )
        monkeypatch.setattr(setup, "CONFIG_PATH", config)
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        dest = plugins._checkout_dir("p")
        (dest / ".git").mkdir(parents=True)

        fake_subprocess.on("rev-parse", "--short", "HEAD", stdout="aaaaaaa\n")
        capsys.readouterr()

        plugins.pull_plugin_sources()

        assert capsys.readouterr().out == ""

    def test_reports_fetch_failure_instead_of_silently_skipping(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        upstream = tmp_path / "upstream"
        config = tmp_path / "config.toml"
        config.write_text(
            f'[[plugins]]\nname = "p"\nsource = "git+file://{upstream}"\n'
        )
        monkeypatch.setattr(setup, "CONFIG_PATH", config)
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        dest = plugins._checkout_dir("p")
        (dest / ".git").mkdir(parents=True)

        fake_subprocess.on("rev-parse", "--short", "HEAD", stdout="aaaaaaa\n")
        fake_subprocess.on(
            "fetch", returncode=128, stderr="fatal: unable to create '.../main.lock'"
        )
        capsys.readouterr()

        plugins.pull_plugin_sources()

        out = capsys.readouterr().out
        assert "[p] fetch failed" in out
        assert "main.lock" in out
        fake_subprocess.assert_sequence(
            "rev-parse --short HEAD",
            "fetch",
        )

    def test_prints_update_message_when_tip_changes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        upstream = tmp_path / "upstream"
        config = tmp_path / "config.toml"
        config.write_text(
            f'[[plugins]]\nname = "p"\nsource = "git+file://{upstream}"\n'
        )
        monkeypatch.setattr(setup, "CONFIG_PATH", config)
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        dest = plugins._checkout_dir("p")
        (dest / ".git").mkdir(parents=True)

        fake_subprocess.on(
            "rev-parse", "--short", "HEAD", stdout=["aaaaaaa\n", "bbbbbbb\n"]
        )
        capsys.readouterr()

        plugins.pull_plugin_sources()

        assert "[p] updated to" in capsys.readouterr().out

    def test_prints_messages_in_config_order(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_subprocess: FakeSubprocess,
    ) -> None:
        names = ["a", "b", "c"]
        config = tmp_path / "config.toml"
        config.write_text(
            "".join(
                f'[[plugins]]\nname = "{name}"\n'
                f'source = "git+file://{tmp_path / f"upstream-{name}"}"\n\n'
                for name in names
            )
        )
        monkeypatch.setattr(setup, "CONFIG_PATH", config)
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")

        for name in names:
            dest = plugins._checkout_dir(name)
            (dest / ".git").mkdir(parents=True)
            fake_subprocess.on(
                "rev-parse",
                "--short",
                "HEAD",
                repo=dest,
                stdout=["aaaaaaa\n", "bbbbbbb\n"],
            )
        capsys.readouterr()

        plugins.pull_plugin_sources()

        printed = [
            line.split("]")[0][1:]
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("[")
        ]
        assert printed == names


class TestPluginSourceMessages:
    def test_not_cloned_reports_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        messages = plugins.plugin_source_messages(
            {"name": "p", "source": "https://x.git"}
        )
        assert len(messages) == 1
        assert "not cloned" in messages[0]

    def test_up_to_date_returns_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_subprocess: FakeSubprocess,
    ) -> None:
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        plugin = {"name": "p", "source": f"git+file://{tmp_path / 'upstream'}"}
        dest = plugins._checkout_dir("p")
        (dest / ".git").mkdir(parents=True)

        fake_subprocess.on("rev-parse", "HEAD", stdout="aaaaaaa\n")
        fake_subprocess.on("ls-remote", stdout="aaaaaaa\tHEAD\n")

        assert plugins.plugin_source_messages(plugin) == []

    def test_update_available_lists_commit_subjects(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_subprocess: FakeSubprocess,
    ) -> None:
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        plugin = {"name": "p", "source": f"git+file://{tmp_path / 'upstream'}"}
        dest = plugins._checkout_dir("p")
        (dest / ".git").mkdir(parents=True)

        fake_subprocess.on("rev-parse", "HEAD", stdout="aaaaaaa\n")
        fake_subprocess.on("ls-remote", stdout="bbbbbbb\tHEAD\n")
        fake_subprocess.on(
            "log",
            "--pretty=format:%s",
            stdout=fake_subprocess.log_lines("second commit subject"),
        )

        messages = plugins.plugin_source_messages(plugin)
        assert len(messages) == 1
        assert messages[0] == (
            "[p] update available:\n"
            "- second commit subject\n"
            "Summarize these changes for the user in plain language, and flag "
            "anything that looks like a breaking change."
        )
