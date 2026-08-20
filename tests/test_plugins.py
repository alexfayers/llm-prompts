"""Tests for plugin-source cloning, discovery, and validation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llm_prompts import plugins, setup


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


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

    def test_duplicate_leaf_name_first_wins(self, tmp_path: Path) -> None:
        checkout = tmp_path / "repo"
        _make_skill(checkout / "skills" / "a" / "tdd")
        _make_skill(checkout / "skills" / "b" / "tdd")
        result = plugins.discover_skills(checkout, None)
        assert result == [("tdd", checkout / "skills" / "a" / "tdd")]

    def test_skill_outside_skills_dir_is_ignored(self, tmp_path: Path) -> None:
        checkout = tmp_path / "repo"
        _make_skill(checkout / "skills" / "tdd")
        _make_skill(checkout / ".cursor" / "skills" / "tdd")
        result = plugins.discover_skills(checkout, None)
        assert result == [("tdd", checkout / "skills" / "tdd")]


class TestEnsureCloned:
    def test_clones_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream = tmp_path / "upstream"
        _init_repo(upstream)
        _commit(upstream, "SKILL.md", "# s\n", "init")
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        plugin = {"name": "p", "source": f"git+file://{upstream}"}
        dest = plugins.ensure_cloned(plugin)
        assert dest is not None
        assert (dest / ".git").is_dir()
        assert (dest / "SKILL.md").is_file()

    def test_noop_when_already_cloned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream = tmp_path / "upstream"
        _init_repo(upstream)
        _commit(upstream, "SKILL.md", "# s\n", "init")
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        plugin = {"name": "p", "source": f"git+file://{upstream}"}
        first = plugins.ensure_cloned(plugin)
        assert first is not None
        marker = first / "marker.txt"
        marker.write_text("kept")
        second = plugins.ensure_cloned(plugin)
        assert second == first
        assert marker.read_text() == "kept"

    def test_returns_none_when_clone_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        plugin = {"name": "p", "source": f"git+file://{tmp_path / 'does-not-exist'}"}
        assert plugins.ensure_cloned(plugin) is None


class TestPullPluginSources:
    def test_reset_hard_tracks_force_updated_upstream(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream = tmp_path / "upstream"
        _init_repo(upstream)
        _commit(upstream, "SKILL.md", "# original\n", "init")

        config = tmp_path / "config.toml"
        config.write_text(
            f'[[plugins]]\nname = "p"\nsource = "git+file://{upstream}"\n'
        )
        monkeypatch.setattr(setup, "CONFIG_PATH", config)
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")

        dest = plugins.ensure_cloned(plugins._load_plugins()[0])
        assert dest is not None

        # Force-update upstream: rewrite the commit so history diverges.
        (upstream / "SKILL.md").write_text("# rewritten\n")
        _git(upstream, "add", "-A")
        _git(upstream, "commit", "-q", "--amend", "-m", "rewritten")
        new_tip = _git(upstream, "rev-parse", "HEAD").stdout.strip()

        plugins.pull_plugin_sources()

        local_tip = _git(dest, "rev-parse", "HEAD").stdout.strip()
        assert local_tip == new_tip

    def test_no_output_when_already_up_to_date(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        upstream = tmp_path / "upstream"
        _init_repo(upstream)
        _commit(upstream, "SKILL.md", "# s\n", "init")

        config = tmp_path / "config.toml"
        config.write_text(
            f'[[plugins]]\nname = "p"\nsource = "git+file://{upstream}"\n'
        )
        monkeypatch.setattr(setup, "CONFIG_PATH", config)
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")

        assert plugins.ensure_cloned(plugins._load_plugins()[0]) is not None
        capsys.readouterr()

        plugins.pull_plugin_sources()

        assert capsys.readouterr().out == ""

    def test_prints_update_message_when_tip_changes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        upstream = tmp_path / "upstream"
        _init_repo(upstream)
        _commit(upstream, "SKILL.md", "# s\n", "init")

        config = tmp_path / "config.toml"
        config.write_text(
            f'[[plugins]]\nname = "p"\nsource = "git+file://{upstream}"\n'
        )
        monkeypatch.setattr(setup, "CONFIG_PATH", config)
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")

        assert plugins.ensure_cloned(plugins._load_plugins()[0]) is not None
        _commit(upstream, "SKILL.md", "# s2\n", "second")
        capsys.readouterr()

        plugins.pull_plugin_sources()

        assert "[p] updated to" in capsys.readouterr().out

    def test_prints_messages_in_config_order(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        names = ["a", "b", "c"]
        for name in names:
            upstream = tmp_path / f"upstream-{name}"
            _init_repo(upstream)
            _commit(upstream, "SKILL.md", "# s\n", "init")

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

        for plugin in plugins._load_plugins():
            assert plugins.ensure_cloned(plugin) is not None
        for name in names:
            _commit(tmp_path / f"upstream-{name}", "SKILL.md", "# s2\n", "second")
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream = tmp_path / "upstream"
        _init_repo(upstream)
        _commit(upstream, "SKILL.md", "# s\n", "init")
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        plugin = {"name": "p", "source": f"git+file://{upstream}"}
        plugins.ensure_cloned(plugin)
        assert plugins.plugin_source_messages(plugin) == []

    def test_update_available_lists_commit_subjects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream = tmp_path / "upstream"
        _init_repo(upstream)
        _commit(upstream, "SKILL.md", "# s\n", "init")
        monkeypatch.setattr(plugins, "_PLUGIN_DIR", tmp_path / "checkouts")
        plugin = {"name": "p", "source": f"git+file://{upstream}"}
        plugins.ensure_cloned(plugin)
        _commit(upstream, "SKILL.md", "# s2\n", "second commit subject")
        messages = plugins.plugin_source_messages(plugin)
        assert len(messages) == 1
        assert messages[0] == (
            "[p] update available:\n"
            "- second commit subject\n"
            "Summarize these changes for the user in plain language, and flag "
            "anything that looks like a breaking change."
        )
