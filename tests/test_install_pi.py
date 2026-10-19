"""Tests for the pi install target."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from llm_prompts import manifest as manifest_module
from llm_prompts.install import (
    _expanded_definition,
    _linked_content,
    _parse_roles,
    _pi_agent_dir,
    _requirements_met,
    _split_npm_source,
    get_managed_dirs,
    prompts_dir,
    uninstall,
)
from llm_prompts.install import main as install_main
from llm_prompts.render_template import strip_gating_keys
from llm_prompts.size_guard import CheckResult, Violation, check
from llm_prompts.size_limits import PI_ROLE_PROMPT_BYTES, RULE_BYTES

_CORE_FRAGMENT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "settings.json"
)

_SEED_RELATIVE = (
    Path(".pi") / "agent" / "extensions" / "pi-permission-system" / "config.json"
)

_REAL_WHICH = shutil.which

_CLAUDE_ONLY_TOOLS = (
    "AskUserQuestion",
    "SendMessage",
    "TaskCreate",
    "TaskStop",
    "EnterPlanMode",
    "ExitPlanMode",
    "ListAgents",
)


def _install(
    home: Path,
    manifest: Path,
    overlays: list[Path] | None = None,
    *,
    herdr: bool = True,
    pi: str | None = None,
    only: Path | None = None,
    targets: list[str] | None = None,
) -> bool:
    """Run `install` into a fake home with overlays and manifest redirected."""

    def which(command: str) -> str | None:
        if command == "herdr":
            return "/usr/bin/herdr" if herdr else None
        if command == "pi":
            return pi
        if command == "cline-hook":
            return None
        return _REAL_WHICH(command)

    outer = subprocess.run

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[1:] == ["install", "pi"]:
            extensions = Path(kwargs["env"]["PI_CODING_AGENT_DIR"]) / "extensions"
            extensions.mkdir(parents=True, exist_ok=True)
            (extensions / "cline-hooks.ts").touch()
            return subprocess.CompletedProcess(cmd, 0)
        result = outer(cmd, **kwargs)
        if cmd[1:2] == ["install"] and result.returncode == 0:
            package = _split_npm_source(cmd[2])[0]
            (_pi_agent_dir() / "npm/node_modules" / package).mkdir(
                parents=True, exist_ok=True
            )
        return result

    with (
        patch("llm_prompts.install.subprocess.run", side_effect=run),
        patch("llm_prompts.install.Path.home", return_value=home),
        patch("llm_prompts.install.shutil.which", side_effect=which),
        patch(
            "llm_prompts.install._discover_overlay_paths", return_value=overlays or []
        ),
        patch("llm_prompts.manifest.manifest_path", return_value=manifest),
    ):
        return install_main(targets or ["pi"], only=only)


def _overlay(root: Path, packages: list[str], **settings: Any) -> Path:
    """Build an overlay declaring the given pi packages and settings, returning its prompts dir."""
    fragment = root / "pi" / "settings.json"
    fragment.parent.mkdir(parents=True, exist_ok=True)
    fragment.write_text(
        json.dumps({"packages": packages, **settings}), encoding="utf-8"
    )
    return root


def _settings(home: Path) -> dict[str, Any]:
    """Read pi's global settings from a fake home."""
    path = home / ".pi" / "agent" / "settings.json"
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _core_seed() -> Path:
    """Return the core seed file for the permission policy."""
    return (
        _CORE_FRAGMENT.parent
        / "seed"
        / "extensions"
        / "pi-permission-system"
        / "config.json"
    )


def _core_packages() -> list[str]:
    """Return the core packages pi installs."""
    return [
        "npm:pi-herdsman@0.22.0",
        "npm:pi-ask-user@0.16.0",
        "npm:tower-do@0.7.0",
        "npm:pi-notify@1.4.0",
        "npm:pi-lsp-extension@1.4.0",
        "npm:@henryqw/pi-herdr-tools@1.0.5",
        "npm:@gotgenes/pi-permission-system@40.1.1",
        "npm:pi-zentui@0.30.0",
        "npm:pi-web-access@0.38.0",
        "npm:pi-compact-tools@0.14.2",
        "npm:@aliou/pi-processes@0.13.2",
        "npm:pi-context-usage@2.1.0",
        "npm:pi-cache-insight@1.1.0",
    ]


@pytest.fixture
def pi_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Install pi into a fake home, yielding it."""
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    _install(home, tmp_path / "installed.json")
    yield home


class TestPiInstallLayout:
    def test_installs_agents_md_and_one_file_per_rule(self, pi_home: Path) -> None:
        agent_dir = pi_home / ".pi" / "agent"
        assert (agent_dir / "AGENTS.md").is_file()
        assert (agent_dir / "rules" / "coding.md").is_file()

    def test_skills_materialize_into_pi_skills(self, pi_home: Path) -> None:
        skills = pi_home / ".pi" / "agent" / "skills"
        assert (skills / "tdd" / "SKILL.md").is_file()
        assert (skills / "git-usage" / "SKILL.md").is_file()

    def test_workflows_install_as_prompt_templates(self, pi_home: Path) -> None:
        prompts = pi_home / ".pi" / "agent" / "prompts"
        assert (prompts / "simplify.md").is_file()

    def test_reinstall_removes_stale_prompt(
        self, pi_home: Path, tmp_path: Path
    ) -> None:
        stray = pi_home / ".pi" / "agent" / "prompts" / "stray.md"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text("stale", encoding="utf-8")
        manifest = tmp_path / "installed.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["agents"]["pi"]["files"].append(str(stray))
        manifest.write_text(json.dumps(data), encoding="utf-8")

        _install(pi_home, manifest)

        assert not stray.exists()


class TestPiAgentDirOverride:
    def test_installs_under_pi_coding_agent_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_dir = tmp_path / "custom-agent"
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))
        home = tmp_path / "home"
        home.mkdir()

        _install(home, tmp_path / "installed.json")

        assert (agent_dir / "AGENTS.md").is_file()
        assert (agent_dir / "skills" / "tdd" / "SKILL.md").is_file()
        assert not (home / ".pi").exists()


class TestPiManagedDirs:
    def test_includes_skills_not_bare_agent_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        with patch("llm_prompts.install.Path.home", return_value=home):
            managed = set(get_managed_dirs())

        agent_dir = home / ".pi" / "agent"
        assert agent_dir / "skills" in managed
        assert agent_dir not in managed


class TestRequiresAbsentCommand:
    @pytest.mark.parametrize(("herdr", "expected"), [(False, True), (True, False)])
    def test_gate_open_only_when_command_absent(
        self, herdr: bool, expected: bool
    ) -> None:
        found = "/usr/bin/herdr" if herdr else None
        with patch("llm_prompts.install.shutil.which", return_value=found):
            assert (
                _requirements_met({"requires_absent_command": "herdr"}, "pi")
                is expected
            )


class TestPiPackages:
    def test_declared_packages_land_in_pi_settings(self, pi_home: Path) -> None:
        assert _settings(pi_home)["packages"] == _core_packages()

    def test_herdr_packages_install_without_herdr_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        home.mkdir()

        _install(home, tmp_path / "installed.json", herdr=False)

        packages = _settings(home)["packages"]
        assert packages == _core_packages()
        assert not any("pi-subagents" in package for package in packages)

    def test_missing_herdr_warns_and_still_installs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        home.mkdir()

        failed = _install(home, tmp_path / "installed.json", herdr=False)

        assert not failed
        assert "herdr` not found" in capsys.readouterr().err
        assert (home / ".pi" / "agent" / "AGENTS.md").is_file()

    def test_herdr_on_path_does_not_warn(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        home.mkdir()

        _install(home, tmp_path / "installed.json")

        assert "herdr` not found" not in capsys.readouterr().err

    def test_default_model_fills_when_absent_and_keeps_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        settings_path = home / ".pi" / "agent" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps({"defaultModel": "user/model"}), encoding="utf-8"
        )
        overlay = _overlay(
            tmp_path / "o", [], defaultProvider="acme", defaultModel="acme/large"
        )

        _install(home, tmp_path / "installed.json", [overlay])

        settings = _settings(home)
        assert settings["defaultProvider"] == "acme"
        assert settings["defaultModel"] == "user/model"

    def test_default_tools_seeded_when_absent_and_kept_when_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        overlay = _overlay(tmp_path / "o", [], defaultTools=["+acme"])

        fresh = tmp_path / "fresh"
        _install(fresh, tmp_path / "fresh.json", [overlay])
        assert _settings(fresh)["defaultTools"] == ["+acme"]

        home = tmp_path / "home"
        settings_path = home / ".pi" / "agent" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps({"defaultTools": ["read"]}), encoding="utf-8"
        )
        _install(home, tmp_path / "installed.json", [overlay])
        assert _settings(home)["defaultTools"] == ["read"]

    def test_core_fragment_defaults_tools_to_codemode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"

        _install(home, tmp_path / "installed.json")

        assert _settings(home)["defaultTools"] == ["+codemode"]

    def test_core_fragment_seeds_modes_and_telemetry_but_keeps_user_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        fresh = tmp_path / "fresh"
        _install(fresh, tmp_path / "fresh.json")
        fresh_settings = _settings(fresh)
        assert fresh_settings["steeringMode"] == "all"
        assert fresh_settings["followUpMode"] == "all"
        assert fresh_settings["cacheWarming"] == "idle"
        assert fresh_settings["enableInstallTelemetry"] is False
        failing: subprocess.CompletedProcess[str] = subprocess.CompletedProcess([], 1)
        with (
            patch("llm_prompts.install.subprocess.run", return_value=failing),
            pytest.raises(ValueError, match="pi-permission-system"),
        ):
            _install(tmp_path / "bare", tmp_path / "bare.json", pi="/usr/bin/pi")

        home = tmp_path / "home"
        settings_path = home / ".pi" / "agent" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps(
                {
                    "steeringMode": "one-at-a-time",
                    "followUpMode": "one-at-a-time",
                    "cacheWarming": "streaming",
                    "enableInstallTelemetry": True,
                }
            ),
            encoding="utf-8",
        )
        _install(home, tmp_path / "installed.json")
        settings = _settings(home)
        assert settings["steeringMode"] == "one-at-a-time"
        assert settings["followUpMode"] == "one-at-a-time"
        assert settings["cacheWarming"] == "streaming"
        assert settings["enableInstallTelemetry"] is True

    def test_user_settings_and_packages_are_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        settings_path = home / ".pi" / "agent" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        user_entry = {"source": "npm:user-pkg", "extensions": []}
        settings_path.write_text(
            json.dumps({"theme": "dark", "packages": [user_entry]}), encoding="utf-8"
        )

        _install(home, tmp_path / "installed.json")

        settings = _settings(home)
        assert settings["theme"] == "dark"
        assert settings["packages"] == [user_entry, *_core_packages()]

    def test_overlay_packages_are_added_and_dropped_when_undeclared(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        overlay = tmp_path / "overlay"

        _install(home, manifest, [_overlay(overlay, ["npm:overlay-pkg"])])
        assert "npm:overlay-pkg" in _settings(home)["packages"]

        _install(home, manifest, [_overlay(overlay, [])])
        assert _settings(home)["packages"] == _core_packages()

    def test_uninstall_removes_only_managed_packages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        _install(home, manifest)
        settings_path = home / ".pi" / "agent" / "settings.json"
        settings = _settings(home)
        settings["packages"].append("npm:user-pkg")
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.manifest.manifest_path", return_value=manifest),
        ):
            uninstall(["pi"])

        assert _settings(home)["packages"] == ["npm:user-pkg"]


class TestPiExtensions:
    def test_overlay_extension_is_installed_and_removed_when_undeclared(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        overlay = tmp_path / "overlay"
        source = overlay / "pi" / "extensions" / "acme-guard.ts"
        source.parent.mkdir(parents=True)
        source.write_text("pi.registerProvider(x)\n", encoding="utf-8")
        agent = overlay / "shared" / "agents" / "a.md"
        agent.parent.mkdir(parents=True)
        agent.write_text("---\nname: a\nextensions: []\n---\n\nb\n", encoding="utf-8")
        installed = home / ".pi" / "agent" / "extensions" / "acme-guard.ts"
        listed = home / ".pi" / "agent" / "agents" / "a.md"

        _install(home, manifest, [overlay])
        assert installed.read_text(encoding="utf-8") == "pi.registerProvider(x)\n"
        assert str(installed) in _frontmatter(listed)["extensions"]

        source.unlink()
        _install(home, manifest, [overlay])
        assert not installed.exists()
        assert str(installed) not in _frontmatter(listed)["extensions"]

    def test_core_net_guard_extension_is_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        source = _CORE_FRAGMENT.parent / "extensions" / "net-guard.ts"

        _install(home, tmp_path / "installed.json")

        installed = home / ".pi" / "agent" / "extensions" / "net-guard.ts"
        assert installed.read_text(encoding="utf-8") == source.read_text(
            encoding="utf-8"
        )

    def test_core_compact_now_extension_is_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        source = _CORE_FRAGMENT.parent / "extensions" / "compact-now.ts"

        _install(home, tmp_path / "installed.json")

        installed = home / ".pi" / "agent" / "extensions" / "compact-now.ts"
        assert installed.read_text(encoding="utf-8") == source.read_text(
            encoding="utf-8"
        )

    def test_compact_now_extension_registers_tool_that_compacts(self) -> None:
        source = (_CORE_FRAGMENT.parent / "extensions" / "compact-now.ts").read_text(
            encoding="utf-8"
        )

        assert 'name: "compact_now"' in source
        assert ".compact(" in source

    def test_unmanaged_extension_with_same_name_is_not_overwritten(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        overlay = tmp_path / "overlay"
        source = overlay / "pi" / "extensions" / "acme-guard.ts"
        source.parent.mkdir(parents=True)
        source.write_text("export default () => {};\n", encoding="utf-8")
        existing = home / ".pi" / "agent" / "extensions" / "acme-guard.ts"
        existing.parent.mkdir(parents=True)
        existing.write_text("// another tool's file\n", encoding="utf-8")

        _install(home, tmp_path / "installed.json", [overlay])

        assert existing.read_text(encoding="utf-8") == "// another tool's file\n"


def _claude_plugins(
    home: Path, plugins: dict[str, bool], installed: dict[str, Path | None]
) -> None:
    """Write fake Claude settings enabling plugins and their install records."""
    claude = home / ".claude"
    (claude / "plugins").mkdir(parents=True, exist_ok=True)
    (claude / "settings.json").write_text(
        json.dumps({"enabledPlugins": plugins}), encoding="utf-8"
    )
    records = {
        key: [{"installPath": str(path)}] for key, path in installed.items() if path
    }
    (claude / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": records}), encoding="utf-8"
    )


def _plugin_dir(tmp_path: Path, name: str, *, skills: bool = True) -> Path:
    """Create a fake plugin install dir, with a skills dir by default."""
    path = tmp_path / "plugins" / name
    (path / "skills" / "demo").mkdir(parents=True) if skills else path.mkdir(
        parents=True
    )
    return path


class TestPiPluginSkills:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)

    def test_enabled_plugin_skills_dir_is_added(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        plugin = _plugin_dir(tmp_path, "alpha")
        _claude_plugins(home, {"alpha@acme": True}, {"alpha@acme": plugin})

        _install(home, tmp_path / "installed.json")

        assert _settings(home)["skills"] == [str(plugin / "skills")]

    def test_disabled_plugin_entry_is_removed_and_user_entries_kept(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        plugin = _plugin_dir(tmp_path, "alpha")
        _claude_plugins(home, {"alpha@acme": True}, {"alpha@acme": plugin})
        _install(home, manifest)
        settings_path = home / ".pi" / "agent" / "settings.json"
        settings = _settings(home)
        settings["skills"].append("/mine/skills")
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        _claude_plugins(home, {"alpha@acme": False}, {"alpha@acme": plugin})
        _install(home, manifest)

        assert _settings(home)["skills"] == ["/mine/skills"]

    def test_uninstall_removes_only_managed_skills(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        plugin = _plugin_dir(tmp_path, "alpha")
        _claude_plugins(home, {"alpha@acme": True}, {"alpha@acme": plugin})
        _install(home, manifest)

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.manifest.manifest_path", return_value=manifest),
        ):
            uninstall(["pi"])

        assert _settings(home)["skills"] == []

    def test_uninstalled_or_skill_less_plugins_are_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / "home"
        bare = _plugin_dir(tmp_path, "bare", skills=False)
        _claude_plugins(
            home,
            {"gone@acme": True, "bare@acme": True, "off@acme": False},
            {"gone@acme": None, "bare@acme": bare},
        )

        _install(home, tmp_path / "installed.json")

        assert "skills" not in _settings(home)
        assert "gone@acme" in capsys.readouterr().err

    def test_unparseable_claude_files_change_nothing(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        plugin = _plugin_dir(tmp_path, "alpha")
        _claude_plugins(home, {"alpha@acme": True}, {"alpha@acme": plugin})
        _install(home, manifest)
        (home / ".claude" / "settings.json").write_text("{", encoding="utf-8")

        _install(home, manifest)

        assert _settings(home)["skills"] == [str(plugin / "skills")]


class TestPiPluginMcpServers:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)

    @staticmethod
    def _mcp(plugin: Path, content: str) -> None:
        (plugin / ".mcp.json").write_text(content, encoding="utf-8")

    @staticmethod
    def _pi_servers(home: Path) -> dict[str, Any]:
        path = home / ".pi" / "agent" / "mcp.json"
        return dict(json.loads(path.read_text(encoding="utf-8"))["mcpServers"])

    def test_enabled_plugin_servers_are_added_with_pi_keys_only(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        plugin = _plugin_dir(tmp_path, "alpha")
        self._mcp(
            plugin,
            json.dumps(
                {
                    "mcpServers": {
                        "ok": {"command": "a", "args": ["x"], "extra": 1},
                        "sse": {"type": "sse", "url": "https://example.test"},
                    }
                }
            ),
        )
        _claude_plugins(home, {"alpha@acme": True}, {"alpha@acme": plugin})

        _install(home, tmp_path / "installed.json")

        assert self._pi_servers(home) == {"ok": {"command": "a", "args": ["x"]}}

    def test_claude_json_wins_over_plugin_and_existing_pi_entries_stay(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        (home / ".pi" / "agent").mkdir(parents=True)
        (home / ".pi" / "agent" / "mcp.json").write_text(
            json.dumps({"mcpServers": {"mine": {"command": "mine"}}}),
            encoding="utf-8",
        )
        (home / ".claude.json").write_text(
            json.dumps({"mcpServers": {"dup": {"command": "user"}}}),
            encoding="utf-8",
        )
        plugin = _plugin_dir(tmp_path, "alpha")
        self._mcp(
            plugin,
            json.dumps(
                {
                    "mcpServers": {
                        "dup": {"command": "plugin"},
                        "mine": {"command": "plugin"},
                    }
                }
            ),
        )
        _claude_plugins(home, {"alpha@acme": True}, {"alpha@acme": plugin})

        _install(home, tmp_path / "installed.json")

        assert self._pi_servers(home) == {
            "mine": {"command": "mine"},
            "dup": {"command": "user"},
        }

    def test_missing_or_invalid_mcp_json_is_skipped_without_values(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / "home"
        bad = _plugin_dir(tmp_path, "bad")
        self._mcp(bad, '{"mcpServers": {"s": {"command": "c", "env": {"K": "s3cret"')
        none = _plugin_dir(tmp_path, "none")
        good = _plugin_dir(tmp_path, "good")
        self._mcp(
            good,
            json.dumps({"mcpServers": {"g": {"command": "c", "env": {"K": "s3cret"}}}}),
        )
        _claude_plugins(
            home,
            {"bad@acme": True, "none@acme": True, "good@acme": True},
            {"bad@acme": bad, "none@acme": none, "good@acme": good},
        )

        _install(home, tmp_path / "installed.json")

        assert list(self._pi_servers(home)) == ["g"]
        captured = capsys.readouterr()
        assert "s3cret" not in captured.out + captured.err
        assert "bad/.mcp.json" in captured.err


class TestPiMcpServers:
    @staticmethod
    def _claude(home: Path, servers: dict[str, Any]) -> None:
        (home / ".claude.json").write_text(
            json.dumps(
                {
                    "mcpServers": servers,
                    "projects": {"/x": {"mcpServers": {"p": {"command": "p"}}}},
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _pi_servers(home: Path) -> dict[str, Any]:
        path = home / ".pi" / "agent" / "mcp.json"
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def _run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        servers: dict[str, Any] | None,
        existing: dict[str, Any] | None = None,
    ) -> Path:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        (home / ".pi" / "agent").mkdir(parents=True)
        if existing is not None:
            (home / ".pi" / "agent" / "mcp.json").write_text(
                json.dumps(existing), encoding="utf-8"
            )
        if servers is not None:
            self._claude(home, servers)
        _install(home, tmp_path / "installed.json")
        return home

    def test_adds_missing_servers_with_pi_keys_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = self._run(
            tmp_path,
            monkeypatch,
            {
                "alpha": {
                    "type": "stdio",
                    "command": "a",
                    "args": ["x"],
                    "env": {"K": "v"},
                    "extra": 1,
                },
                "beta": {
                    "type": "http",
                    "url": "https://example.test",
                    "headers": {"H": "v"},
                },
            },
        )
        assert self._pi_servers(home)["mcpServers"] == {
            "alpha": {
                "type": "stdio",
                "command": "a",
                "args": ["x"],
                "env": {"K": "v"},
            },
            "beta": {
                "type": "http",
                "url": "https://example.test",
                "headers": {"H": "v"},
            },
        }

    def test_keeps_existing_entries_and_other_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        existing = {
            "imports": [],
            "mcpServers": {"alpha": {"command": "mine", "exposure": "direct"}},
        }
        home = self._run(
            tmp_path,
            monkeypatch,
            {"alpha": {"command": "theirs"}, "beta": {"command": "b"}},
            existing,
        )
        assert self._pi_servers(home) == {
            "imports": [],
            "mcpServers": {
                "alpha": {"command": "mine", "exposure": "direct"},
                "beta": {"command": "b"},
            },
        }

    def test_skips_sse_and_unusable_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = self._run(
            tmp_path,
            monkeypatch,
            {"s": {"type": "sse", "url": "https://example.test"}, "n": {"env": {}}},
        )
        assert (
            not (home / ".pi" / "agent" / "mcp.json").exists()
            or self._pi_servers(home).get("mcpServers", {}) == {}
        )

    def test_no_claude_file_leaves_pi_config_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = self._run(tmp_path, monkeypatch, None)
        assert not (home / ".pi" / "agent" / "mcp.json").exists()

    def test_never_logs_values(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._run(
            tmp_path,
            monkeypatch,
            {"alpha": {"command": "a", "env": {"K": "sekret-value"}}},
        )
        assert "sekret-value" not in capsys.readouterr().err


class TestPiSeedFiles:
    def test_permission_seed_registers_the_diff_preview_link_and_never_elides_the_dialog(
        self,
    ) -> None:
        seed = json.loads(_core_seed().read_text(encoding="utf-8"))
        assert "diff-preview" in seed["authorizerChain"]
        assert seed["promptMaxRows"] == seed["promptFieldMaxWidth"] == 1_000_000

    def test_permission_seed_gates_shell_writes_like_the_write_tool(self) -> None:
        permission = json.loads(_core_seed().read_text(encoding="utf-8"))["permission"]
        assert permission["path_write"] == permission["write"]

    def test_permission_seed_gates_mutating_llm_prompts_subcommands_but_not_check(
        self,
    ) -> None:
        bash = json.loads(_core_seed().read_text(encoding="utf-8"))["permission"][
            "bash"
        ]
        for subcommand in ("install", "setup", "update", "uninstall", "contribute"):
            assert bash[f"llm-prompts {subcommand} *"] == "ask"
        assert not any(rule.startswith("llm-prompts check") for rule in bash)

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("llm-prompts update --check", "allow"),
            ("llm-prompts update --check --force", "ask"),
            ("llm-prompts update", "ask"),
            ("llm-prompts update --only x.md", "ask"),
            ("llm-prompts setup --dry-run", "allow"),
            ("llm-prompts setup -n", "allow"),
            ("llm-prompts setup --dry-run tool", "ask"),
            ("llm-prompts setup", "ask"),
            ("llm-prompts contribute list", "allow"),
            ("llm-prompts contribute sync", "allow"),
            ("llm-prompts contribute update", "allow"),
            ("llm-prompts contribute sync --apply", "ask"),
            ("llm-prompts contribute update --apply", "ask"),
            ("llm-prompts contribute sync --cleanup b", "ask"),
            ("llm-prompts install --help", "allow"),
            ("llm-prompts uninstall -h", "allow"),
            ("llm-prompts install pi", "ask"),
            ("llm-prompts uninstall pi", "ask"),
        ],
    )
    def test_permission_seed_allows_only_read_only_llm_prompts_variants(
        self, command: str, expected: str
    ) -> None:
        bash = json.loads(_core_seed().read_text(encoding="utf-8"))["permission"][
            "bash"
        ]
        decision = "allow"
        for pattern, action in bash.items():
            if re.fullmatch(
                ".*".join(re.escape(part) for part in pattern.split("*")), command
            ):
                decision = action
        assert decision == expected

    def test_seed_files_written_only_when_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        core_seed = _core_seed()
        seeded = home / _SEED_RELATIVE

        _install(home, manifest)
        assert json.loads(seeded.read_text(encoding="utf-8")) == json.loads(
            core_seed.read_text(encoding="utf-8")
        )

        seeded.write_text('{"edited": true}', encoding="utf-8")
        _install(home, manifest)
        assert seeded.read_text(encoding="utf-8") == '{"edited": true}'

        overlay = tmp_path / "overlay"
        overlay_seed = overlay / "pi" / "seed" / "extensions" / "pi-permission-system"
        overlay_seed.mkdir(parents=True)
        (overlay_seed / "config.json").write_text('{"overlay": true}', encoding="utf-8")
        fresh_home = tmp_path / "fresh"
        fresh_home.mkdir()
        _install(fresh_home, tmp_path / "fresh.json", [overlay])
        assert (fresh_home / _SEED_RELATIVE).read_text(encoding="utf-8") == (
            '{"overlay": true}'
        )

    def test_seed_adds_only_keys_not_offered_before_in_the_files_own_format(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        seeded = home / _SEED_RELATIVE
        _install(home, manifest)
        user: dict[str, Any] = {"permission": {"*": "ask", "edit": {"*": "deny"}}}
        seeded.write_text(json.dumps(user, indent="\t"), encoding="utf-8")
        newer = (
            tmp_path
            / "newer"
            / "pi"
            / "seed"
            / seeded.relative_to(home / ".pi" / "agent")
        )
        newer.parent.mkdir(parents=True)
        newer.write_text(
            json.dumps(
                {"permission": {"bash": {"*": "allow"}, "novel": {}}, "newTop": 1}
            ),
            encoding="utf-8",
        )

        _install(home, manifest, [tmp_path / "newer"])

        user["permission"]["novel"] = {}
        user["newTop"] = 1
        assert seeded.read_text(encoding="utf-8") == json.dumps(user, indent="\t")

    def test_seed_adds_every_missing_key_once_when_the_manifest_has_no_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        seeded = home / _SEED_RELATIVE
        _install(home, manifest)
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
        del recorded["agents"]["pi"]["pi_seeded_keys"]
        manifest.write_text(json.dumps(recorded), encoding="utf-8")
        seeded.write_text('{"permission": {"*": "ask"}}', encoding="utf-8")

        _install(home, manifest)

        user = json.loads(seeded.read_text(encoding="utf-8"))
        assert user["permission"]["*"] == "ask"
        assert "path_write" in user["permission"]
        del user["permission"]["path_write"]
        seeded.write_text(json.dumps(user), encoding="utf-8")
        _install(home, manifest)
        assert "path_write" not in seeded.read_text(encoding="utf-8")

    def test_compact_tools_seed_collapses_every_tool_including_codemode_and_herdsman(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        home.mkdir()

        _install(home, tmp_path / "installed.json")

        config = json.loads(
            (home / ".pi" / "agent" / "compact-tools.json").read_text(encoding="utf-8")
        )
        custom_tools = config.get("custom_tools", {})
        assert custom_tools.get("exclude", []) == []
        assert custom_tools.get("enabled", True) is True
        assert config["style"] == "compact"

    def test_zentui_seed_ships_footer_format_and_keeps_other_surfaces_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        home.mkdir()

        _install(home, tmp_path / "installed.json")

        components = json.loads(
            (home / ".pi" / "agent" / "zentui.json").read_text(encoding="utf-8")
        )["components"]
        starship = components["footer"]["styles"]["starship"]
        assert components["footer"]["style"] == "starship"
        assert starship["format"].startswith("$cwd")
        assert "$model" in starship["format"]
        assert starship["extensionStatuses"]["colorModes"]["context-total"] == "zentui"
        assert starship["format"].index("$context") < starship["format"].index(
            "$tree_context"
        )
        for name in ("tree_context", "tree_cost"):
            assert f"${name}" in starship["format"]
            assert starship["variables"][name].startswith("llm-prompts/context-total:")
        seeded = json.loads(
            (home / ".pi" / "agent" / "context-total.json").read_text(encoding="utf-8")
        )
        assert seeded["footer"] is True
        assert not components["editor"]["enabled"]

    def test_net_guard_seed_blocks_and_allows_known_plugins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        home.mkdir()

        _install(home, tmp_path / "installed.json")

        config = json.loads(
            (home / ".pi" / "agent" / "net-guard.json").read_text(encoding="utf-8")
        )
        assert config["mode"] == "block"
        assert "pi-web-access" in config["allow"]
        assert {"pi-herdsman", "pi-compact-tools"}.isdisjoint(config["allow"])

    def test_seed_files_survive_uninstall_and_reinstall(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        home.mkdir()
        manifest = tmp_path / "installed.json"
        _install(home, manifest)
        seeded = home / _SEED_RELATIVE
        seeded.write_text('{"edited": true}', encoding="utf-8")

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.manifest.manifest_path", return_value=manifest),
        ):
            uninstall(["pi"])
        _install(home, manifest)

        assert json.loads(seeded.read_text(encoding="utf-8"))["edited"] is True


class TestPiWording:
    def test_installed_text_names_no_claude_only_tools(self, pi_home: Path) -> None:
        agent_dir = pi_home / ".pi" / "agent"
        installed = [
            agent_dir / "AGENTS.md",
            *agent_dir.glob("agents/*.md"),
            *agent_dir.glob("skills/*/SKILL.md"),
        ]
        for path in installed:
            text = path.read_text(encoding="utf-8")
            for tool in _CLAUDE_ONLY_TOOLS:
                assert tool not in text, f"{path.name} names {tool}"

    def test_rules_carry_pi_question_tools(self, pi_home: Path) -> None:
        rules = (pi_home / ".pi" / "agent" / "AGENTS.md").read_text(encoding="utf-8")
        assert "`ask_user`" in rules


class TestPiAgents:
    def test_agent_frontmatter_is_valid_yaml(self, pi_home: Path) -> None:
        for path in (pi_home / ".pi" / "agent" / "agents").glob("*.md"):
            frontmatter = path.read_text(encoding="utf-8").split("---\n")[1]
            assert yaml.safe_load(frontmatter)["name"], path.name

    def test_pi_only_explore_is_read_only_and_not_installed_for_claude_code(
        self, pi_home: Path, tmp_path: Path
    ) -> None:
        path = pi_home / ".pi" / "agent" / "agents" / "Explore.md"
        explore = _frontmatter(path)
        assert "bash" not in explore["tools"]
        assert {"lsp_symbols", "lsp_definition", "lsp_references"} <= set(
            explore["tools"]
        )
        assert explore["inheritProjectContext"] is False
        assert explore["model"] == "haiku"
        assert "thinking: off\n" in path.read_text(encoding="utf-8")

        claude_home = tmp_path / "claude-home"
        claude_home.mkdir()
        with (
            patch("llm_prompts.install.Path.home", return_value=claude_home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=[]),
        ):
            install_main(["claude-code"])
        assert not (claude_home / ".claude" / "agents" / "Explore.md").exists()

    def test_only_reasoner_and_coordinator_may_spawn_explore(
        self, pi_home: Path
    ) -> None:
        agents = pi_home / ".pi" / "agent" / "agents"
        spawners = {
            path.name.split("-")[0].removesuffix(".md")
            for path in agents.glob("*.md")
            if "Explore" in _frontmatter(path).get("agents", [])
        }
        assert spawners == {"reasoner", "coordinator"}

    @pytest.mark.parametrize("role", ["worker", "surveyor", "reasoner", "reviewer"])
    def test_each_role_installs_one_definition_and_a_variants_entry(
        self, pi_home: Path, role: str
    ) -> None:
        agent_dir = pi_home / ".pi" / "agent"
        agents = agent_dir / "agents"
        variants = json.loads((agent_dir / "agent-role-variants.json").read_text())
        coordinator = _frontmatter(agents / "coordinator-sonnet-low.md")
        definition = _frontmatter(agents / f"{role}.md")
        assert not list(agents.glob(f"{role}-*.md"))
        assert not {"model", "thinking"} & definition.keys()
        assert f"[spawn as {role}@<model>:<effort> - " in definition["description"]
        assert variants[role]
        assert role in coordinator["agents"]
        assert coordinator["extensions"][0].endswith("role-switch.ts")

    def test_overlay_models_resolve_tiers_last_overlay_winning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        overlays = []
        for name, models in (
            ("first", {"sonnet": "acme/small", "opus": "acme/first-large"}),
            ("second", {"opus": "acme/second-large", "haiku": "acme/fast"}),
        ):
            overlay = tmp_path / name
            (overlay / "pi").mkdir(parents=True)
            (overlay / "pi" / "agent-models.json").write_text(
                json.dumps(models), encoding="utf-8"
            )
            overlays.append(overlay)

        _install(home, tmp_path / "installed.json", overlays)

        agent_dir = home / ".pi" / "agent"
        variants = json.loads(
            (agent_dir / "agent-role-variants.json").read_text(encoding="utf-8")
        )
        assert variants["worker"]["sonnet"]["model"] == "acme/small"
        assert variants["reasoner"]["opus"]["model"] == "acme/second-large"
        assert variants["worker"]["haiku"] == {
            "model": "acme/fast",
            "efforts": {"low": "off"},
        }
        assert _frontmatter(agent_dir / "agents" / "Explore.md")["model"] == "acme/fast"


class TestHerdsmanAgents:
    def test_team_flow_has_no_agent_request_relay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        _install(home, tmp_path / "installed.json")
        agents = home / ".pi" / "agent" / "agents"
        rules = (home / ".pi" / "agent" / "AGENTS.md").read_text(encoding="utf-8")

        assert "continue_agent" in rules
        for text in (
            rules,
            (agents / "coordinator-sonnet-low.md").read_text(encoding="utf-8"),
            (agents / "worker.md").read_text(encoding="utf-8"),
            (agents / "surveyor.md").read_text(encoding="utf-8"),
        ):
            assert "AGENT REQUEST" not in text
            assert "killable" not in text

    def test_delegation_rule_names_no_unmapped_extra_models(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        _install(home, tmp_path / "installed.json")
        agents = home / ".pi" / "agent" / "agents"
        rules = (home / ".pi" / "agent" / "AGENTS.md").read_text(encoding="utf-8")

        assert not list(agents.glob("*-sol-*.md"))
        assert not re.search(r"\b(sol|terra|luna)\b", rules)

    def test_builtin_definitions_are_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        _install(home, tmp_path / "installed.json")

        agents = home / ".pi" / "agent" / "agents"
        for name in ("generalist", "implementer", "researcher", "scout"):
            assert (agents / f"{name}.md").read_text(encoding="utf-8") == (
                f"---\nname: {name}\nenabled: false\n---\n"
            )

    def test_herdsman_overlays_install_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        _install(home, tmp_path / "installed.json")

        installed = home / ".pi" / "agent" / "agents" / "orchestrator-lead.md"
        assert installed.read_text(encoding="utf-8") == (
            "---\nname: orchestrator-lead\n"
            "tools: [read, codemode, tower_do, "
            "tower_do_patch, tower_do_status, tower_do_talk, ask_user, compact_now, "
            "change_dir]\n---\n"
        )

    def test_agent_tools_pass_pi_names_but_not_mcp_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        agents = tmp_path / "overlay" / "shared" / "agents"
        agents.mkdir(parents=True)
        (agents / "searcher.md").write_text(
            "---\nname: searcher\ntools: lsp_symbols, mcp__acme__thing\n---\n\nbody\n",
            encoding="utf-8",
        )
        _install(home, tmp_path / "installed.json", [tmp_path / "overlay"])
        installed = home / ".pi" / "agent" / "agents" / "searcher.md"
        assert _frontmatter(installed)["tools"] == ["lsp_symbols"]

    def test_agents_install_in_herdsman_dialect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        _install(home, tmp_path / "installed.json")
        agents = home / ".pi" / "agent" / "agents"

        coordinator = _frontmatter(agents / "coordinator-sonnet-low.md")
        assert coordinator["tools"] == [
            "agent",
            "tower_do",
            "tower_do_patch",
            "tower_do_status",
            "tower_do_talk",
        ]
        assert coordinator["thinking"] == "low"
        assert coordinator["inheritGlobalContext"] is False
        assert coordinator["inheritProjectContext"] is True
        assert coordinator["systemPromptMode"] == "append"

        reasoner = _frontmatter(agents / "reasoner.md")
        assert reasoner["excludeTools"] == ["write", "edit"]
        worker = _frontmatter(agents / "worker.md")
        assert worker["excludeTools"][0] == "agent"
        checker = _frontmatter(agents / "eagle-vision-checker-haiku-low.md")
        explore = _frontmatter(agents / "Explore.md")
        for omitting in (checker, explore):
            assert omitting["inheritGlobalContext"] is False
            assert omitting["inheritProjectContext"] is False
        for inheriting in (coordinator, reasoner, worker):
            assert inheriting["inheritGlobalContext"] is False
            assert inheriting["inheritProjectContext"] is True
        for frontmatter in (coordinator, reasoner, worker, checker, explore):
            assert frontmatter["systemPromptMode"] == "append"
        for frontmatter in (coordinator, reasoner, worker, checker, explore):
            assert (
                not {
                    "effort",
                    "color",
                    "omitClaudeMd",
                    "allowed_subagents",
                    "disallowedTools",
                }
                & frontmatter.keys()
            )

    def test_leaves_load_listed_skills_and_trim_tools(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"
        packaged = home / ".pi" / "agent" / "npm" / "node_modules" / "@scope" / "pkg"
        (packaged / "skills" / "pi-processes").mkdir(parents=True)
        (packaged / "skills" / "pi-processes" / "SKILL.md").write_text(
            "---\nname: pi-processes\n---\n", encoding="utf-8"
        )
        _install(home, tmp_path / "installed.json")
        agent_dir = home / ".pi" / "agent"
        agents = agent_dir / "agents"

        def skill(name: str) -> str:
            return str(agent_dir / "skills" / name / "SKILL.md")

        assert _frontmatter(agents / "reasoner.md")["inheritSkills"] is True
        worker = _frontmatter(agents / "worker.md")
        assert worker["inheritSkills"] is True
        assert worker["skills"] == [
            skill("git-usage"),
            skill("tdd"),
            str(packaged / "skills" / "pi-processes" / "SKILL.md"),
        ]
        assert {"agent", "ask_user", "source_check"} <= set(worker["excludeTools"])
        assert "process" not in worker["excludeTools"]
        surveyor = _frontmatter(agents / "surveyor.md")
        assert surveyor["skills"] == [skill("git-usage")]
        assert {"write", "edit", "process", "ask_user"} <= set(surveyor["excludeTools"])
        assert "NotebookEdit" not in surveyor["excludeTools"]
        reviewer = _frontmatter(agents / "reviewer.md")
        assert reviewer["skills"] == [skill("git-usage")]
        assert reviewer["excludeTools"][:3] == ["agent", "write", "edit"]
        assert {"process"} <= set(reviewer["excludeTools"])

    def test_unresolvable_required_pi_skill_fails_install(self, tmp_path: Path) -> None:
        overlay = tmp_path / "o"
        (overlay / "shared" / "agents").mkdir(parents=True)
        (overlay / "shared" / "agents" / "odd.md").write_text(
            "---\nname: odd\npi_skills: nonexistent-skill\n---\n\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="nonexistent-skill"):
            _install(tmp_path / "home", tmp_path / "installed.json", [overlay])

    def test_reviewer_overrides_every_key_of_the_bundled_definition(
        self, pi_home: Path, tmp_path: Path
    ) -> None:
        reviewer = _frontmatter(pi_home / ".pi" / "agent" / "agents" / "reviewer.md")
        assert reviewer["agents"] == []
        assert reviewer["noSkills"] is False
        assert reviewer["tools"] == ["*"]

    def test_unmapped_frontmatter_key_fails_install(self, tmp_path: Path) -> None:
        overlay = tmp_path / "o"
        (overlay / "shared" / "agents").mkdir(parents=True)
        (overlay / "shared" / "agents" / "odd.md").write_text(
            "---\nname: odd\nmystery: 1\n---\n\nbody\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="mystery"):
            _install(tmp_path / "home", tmp_path / "installed.json", [overlay])

    @pytest.mark.parametrize("v", ["[x, y]", "[\"x\", 'y']"])
    def test_extensions_list_limits_extensions(self, tmp_path: Path, v: str) -> None:
        agents = tmp_path / "o/shared/agents"
        agents.mkdir(parents=True)
        (agents / "a.md").write_text(f"---\nname: a\nextensions: {v}\n---\n\nb\n")
        extensions = tmp_path / "h/.pi/agent/extensions"
        extensions.mkdir(parents=True)
        (extensions / "x.ts").touch()
        (extensions / "y").mkdir()
        _install(tmp_path / "h", tmp_path / "i.json", [tmp_path / "o"])
        fm = _frontmatter(tmp_path / "h/.pi/agent/agents/a.md")
        assert fm["noExtensions"] is True
        assert fm["extensions"][:2] == [str(extensions / "x.ts"), str(extensions / "y")]

    def test_missing_extension_fails_unless_optional(self, tmp_path: Path) -> None:
        agents = tmp_path / "o/shared/agents"
        agents.mkdir(parents=True)
        (agents / "a.md").write_text("---\nname: a\nextensions: gone?\n---\n\nb\n")
        _install(tmp_path / "h", tmp_path / "i.json", [tmp_path / "o"])
        assert "gone" not in (tmp_path / "h/.pi/agent/agents/a.md").read_text()
        (agents / "a.md").write_text("---\nname: a\nextensions: gone\n---\n\nb\n")
        with pytest.raises(ValueError, match="gone"):
            _install(tmp_path / "h", tmp_path / "i.json", [tmp_path / "o"])

    def test_base_extensions_join_every_list_once(self, tmp_path: Path) -> None:
        (tmp_path / "o/pi").mkdir(parents=True)
        (tmp_path / "o/pi/agent-extensions.json").write_text('["base", "builtin:a"]')
        agents = tmp_path / "o/shared/agents"
        agents.mkdir(parents=True)
        (agents / "a.md").write_text("---\nname: a\nextensions: builtin:a\n---\n\nb\n")
        extensions = tmp_path / "h/.pi/agent/extensions"
        extensions.mkdir(parents=True)
        (extensions / "base.ts").touch()
        _install(tmp_path / "h", tmp_path / "i.json", [tmp_path / "o"])
        fm = _frontmatter(tmp_path / "h/.pi/agent/agents/a.md")
        assert fm["extensions"].count("builtin:a") == 1
        assert str(extensions / "base.ts") in fm["extensions"]

    def test_provider_entries_of_configured_packages_join_every_list(
        self, tmp_path: Path
    ) -> None:
        agents = tmp_path / "o/shared/agents"
        agents.mkdir(parents=True)
        (agents / "a.md").write_text("---\nname: a\nextensions: []\n---\n\nb\n")
        agent_dir = tmp_path / "h/.pi/agent"
        provider = "pi.registerProvider(x)"
        manifest = '{"pi": {"extensions": ["./src/i.ts"]}}'
        for package, source in (
            ("npm/node_modules/prov", provider),
            ("npm/node_modules/plain", "x"),
            ("git/github.com/o/g", provider),
            ("git/github.com/o/h", provider),
            ("local", provider),
        ):
            (agent_dir / package / "src").mkdir(parents=True)
            (agent_dir / package / "package.json").write_text(manifest)
            (agent_dir / package / "src/i.ts").write_text(source)
        (agent_dir / "npm/node_modules/plain/other.ts").write_text(provider)
        (agent_dir / "npm/node_modules/bare/extensions").mkdir(parents=True)
        (agent_dir / "npm/node_modules/bare/extensions/e.ts").write_text(provider)
        (agent_dir / "extensions").mkdir()
        (agent_dir / "extensions/p.ts").write_text(provider)
        sources = [
            "npm:prov@1",
            "npm:plain",
            "npm:bare",
            "git:https://github.com/o/g",
            "git:github.com/o/h@feat/x",
            "./local",
        ]
        (agent_dir / "settings.json").write_text(json.dumps({"packages": sources}))
        _install(tmp_path / "h", tmp_path / "i.json", [tmp_path / "o"])
        fm = _frontmatter(agent_dir / "agents/a.md")
        assert fm["extensions"][-5:] == [
            str(agent_dir / "npm/node_modules/prov/src/i.ts"),
            str(agent_dir / "git/github.com/o/g/src/i.ts"),
            str(agent_dir / "git/github.com/o/h/src/i.ts"),
            str(agent_dir / "local/src/i.ts"),
            str(agent_dir / "extensions/p.ts"),
        ]

    def test_fresh_install_resolves_extensions_it_installs(
        self, tmp_path: Path
    ) -> None:
        agents = tmp_path / "o/shared/agents"
        agents.mkdir(parents=True)
        (agents / "a.md").write_text("---\nname: a\nextensions: net-guard\n---\n\nb\n")
        _install(tmp_path / "h", tmp_path / "i.json", [tmp_path / "o"])
        fm = _frontmatter(tmp_path / "h/.pi/agent/agents/a.md")
        assert fm["extensions"][0] == str(
            tmp_path / "h/.pi/agent/extensions/net-guard.ts"
        )

    @pytest.mark.parametrize(
        ("models", "made"), [('{"zeta": "p/z"}', True), ("{}", False)]
    )
    def test_additions_add_extra_variants_for_mapped_models(
        self, tmp_path: Path, models: str, made: bool
    ) -> None:
        agents = _install_with_additions(
            tmp_path,
            "generate_variants: sonnet-low",
            {"pi_extra_variants": ["zeta-low"]},
            models,
        )
        assert (agents / "a-zeta-low.md").exists() is made

    def test_additions_append_to_a_skills_list(self, tmp_path: Path) -> None:
        additions = {"pi_skills": ["tdd", "git-usage"], "generate_variants": []}
        agents = _install_with_additions(tmp_path, "pi_skills: git-usage", additions)
        _install(tmp_path / "h", tmp_path / "i.json", [tmp_path / "o"])
        assert (agents / "a.md").exists()
        skills = _frontmatter(agents / "a.md")["skills"]
        assert [Path(s).parent.name for s in skills] == ["git-usage", "tdd"]

    def test_additions_keep_extension_brackets_without_duplicates(
        self, tmp_path: Path
    ) -> None:
        agents = _install_with_additions(
            tmp_path,
            "extensions: [builtin:x]",
            {"extensions": ["builtin:x", "builtin:z"]},
        )
        extensions = _frontmatter(agents / "a.md")["extensions"]
        assert extensions[:2] == ["builtin:x", "builtin:z"]

    def test_additions_variants_stay_managed_when_the_size_guard_skips_the_agent(
        self, tmp_path: Path
    ) -> None:
        agents = _install_with_additions(
            tmp_path, "pi_skills: tdd", {"generate_variants": ["sonnet-low"]}
        )
        skipped = {"pi": {(tmp_path / "o/shared/agents/a.md").resolve()}}
        skip = patch("llm_prompts.size_guard.resolve_skip_set")
        with skip as resolve:
            resolve.return_value = (skipped, frozenset())
            _install(tmp_path / "h", tmp_path / "i.json", [tmp_path / "o"])
        assert (agents / "a-sonnet-low.md").exists()

    def test_additions_from_several_fragments_join_a_core_agent(
        self, tmp_path: Path
    ) -> None:
        for name, skill in ("o", "pickup"), ("p", "todos"):
            (tmp_path / name / "pi").mkdir(parents=True)
            (tmp_path / name / "pi/agent-additions.json").write_text(
                json.dumps({"worker": {"pi_skills": [skill]}})
            )
        _install(tmp_path / "h", tmp_path / "i.json", [tmp_path / "o", tmp_path / "p"])
        worker = tmp_path / "h/.pi/agent/agents/worker.md"
        skills = [Path(s).parent.name for s in _frontmatter(worker)["skills"]]
        assert skills == ["git-usage", "tdd", "pickup", "todos"]


def _install_with_additions(
    tmp_path: Path, line: str, additions: dict[str, list[str]], models: str = "{}"
) -> Path:
    """Install an overlay agent `a` with `line` plus additions; return the agents dir."""
    overlay = tmp_path / "o"
    (overlay / "shared/agents").mkdir(parents=True)
    (overlay / "pi").mkdir()
    (overlay / "pi/agent-models.json").write_text(models)
    (overlay / "pi/agent-additions.json").write_text(json.dumps({"a": additions}))
    (overlay / "shared/agents/a.md").write_text(f"---\nname: a\n{line}\n---\n\nb\n")
    _install(tmp_path / "h", tmp_path / "i.json", [overlay])
    return tmp_path / "h/.pi/agent/agents"


def _frontmatter(path: Path) -> dict[str, Any]:
    """Parse an installed agent's YAML frontmatter."""
    return dict(yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1]))


def _agent_overlay(root: Path) -> Path:
    """Build an overlay with one shared agent and one Claude-Code-only agent."""
    for subdir, name in (("shared", "shared-helper.md"), ("claude-code", "cc-only.md")):
        agents = root / subdir / "agents"
        agents.mkdir(parents=True)
        (agents / name).write_text(
            f"---\nname: {name}\n---\n\nbody\n", encoding="utf-8"
        )
    return root


class TestSharedAgents:
    def test_pi_installs_shared_agents_but_not_overlay_claude_code_agents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        home = tmp_path / "home"

        _install(home, tmp_path / "installed.json", [_agent_overlay(tmp_path / "o")])

        agents = home / ".pi" / "agent" / "agents"
        assert (agents / "shared-helper.md").is_file()
        assert not (agents / "cc-only.md").exists()

    def test_claude_code_installs_shared_and_own_agents(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        overlays = [_agent_overlay(tmp_path / "o")]

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.install._discover_overlay_paths", return_value=overlays),
        ):
            install_main(["claude-code"])

        agents = home / ".claude" / "agents"
        assert (agents / "shared-helper.md").is_file()
        assert (agents / "cc-only.md").is_file()


class TestPiMcpPermissions:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)

    @staticmethod
    def _claude_permissions(home: Path, **lists: list[str]) -> None:
        claude = home / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "settings.json").write_text(
            json.dumps({"permissions": lists}), encoding="utf-8"
        )

    @staticmethod
    def _pi_servers(home: Path, *names: str) -> None:
        mcp = home / ".pi" / "agent" / "mcp.json"
        mcp.parent.mkdir(parents=True, exist_ok=True)
        mcp.write_text(
            json.dumps({"mcpServers": {n: {"command": "x"} for n in names}}),
            encoding="utf-8",
        )

    @staticmethod
    def _config_path(home: Path) -> Path:
        return (
            home
            / ".pi"
            / "agent"
            / "extensions"
            / "pi-permission-system"
            / "config.json"
        )

    def _mcp_rules(self, home: Path) -> dict[str, str]:
        config = json.loads(self._config_path(home).read_text(encoding="utf-8"))
        return dict(config["permission"].get("mcp", {}))

    def test_claude_mcp_rules_become_server_and_tool_rules(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        self._pi_servers(home, "acme", "open")
        self._claude_permissions(
            home,
            allow=["mcp__acme__ReadThing", "mcp__open__*", "Bash(ls)"],
            ask=["mcp__acme__WriteThing"],
            deny=["mcp__acme__DropThing"],
        )

        _install(home, tmp_path / "installed.json")

        assert self._mcp_rules(home) == {
            "acme": "ask",
            "acme:ReadThing": "allow",
            "acme:WriteThing": "ask",
            "acme:DropThing": "deny",
            "open": "allow",
        }

    def test_server_wide_allow_needs_no_ask_default(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        self._pi_servers(home, "acme")
        self._claude_permissions(home, allow=["mcp__acme__*"])

        _install(home, tmp_path / "installed.json")

        assert self._mcp_rules(home) == {"acme": "allow"}

    def test_servers_unknown_to_pi_are_skipped(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        self._pi_servers(home, "acme")
        self._claude_permissions(
            home,
            allow=["mcp__plugin_x_other__Read", "mcp__acme__ReadThing"],
        )

        _install(home, tmp_path / "installed.json")

        assert set(self._mcp_rules(home)) == {"acme", "acme:ReadThing"}

    def test_stale_managed_rules_go_and_user_rules_stay(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        self._pi_servers(home, "acme")
        self._claude_permissions(home, allow=["mcp__acme__ReadThing"])
        _install(home, manifest)
        config_path = self._config_path(home)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["permission"]["mcp"]["mine:Tool"] = "deny"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        self._claude_permissions(home, allow=["mcp__acme__Other"])
        _install(home, manifest)

        assert self._mcp_rules(home) == {
            "mine:Tool": "deny",
            "acme": "ask",
            "acme:Other": "allow",
        }

    def test_unchanged_rules_do_not_rewrite_config(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        self._pi_servers(home, "acme")
        self._claude_permissions(home, allow=["mcp__acme__ReadThing"])
        _install(home, manifest)
        config_path = self._config_path(home)
        before = config_path.stat().st_mtime_ns

        _install(home, manifest)

        assert config_path.stat().st_mtime_ns == before

    def test_uninstall_removes_only_managed_rules(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        self._pi_servers(home, "acme")
        self._claude_permissions(home, allow=["mcp__acme__ReadThing"])
        _install(home, manifest)
        config_path = self._config_path(home)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["permission"]["mcp"]["mine:Tool"] = "deny"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.manifest.manifest_path", return_value=manifest),
        ):
            uninstall(["pi"])

        assert self._mcp_rules(home) == {"mine:Tool": "deny"}

    def test_no_claude_mcp_rules_adds_no_mcp_block(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        self._claude_permissions(home, allow=["Bash(ls)"])

        _install(home, tmp_path / "installed.json")

        assert self._mcp_rules(home) == {}

    def test_unparseable_claude_settings_keep_existing_rules(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        manifest = tmp_path / "installed.json"
        self._pi_servers(home, "acme")
        self._claude_permissions(home, allow=["mcp__acme__ReadThing"])
        _install(home, manifest)
        (home / ".claude" / "settings.json").write_text("{", encoding="utf-8")

        _install(home, manifest)

        assert self._mcp_rules(home) == {"acme": "ask", "acme:ReadThing": "allow"}


class TestRoles:
    @pytest.mark.parametrize(
        ("frontmatter", "expected"),
        [
            ("", {"core"}),
            ("roles: lead, worker\n", {"lead", "worker"}),
            ("roles: 'reasoner,reviewer'\n", {"reasoner", "reviewer"}),
        ],
    )
    def test_roles_parse_with_core_default(
        self, frontmatter: str, expected: set[str]
    ) -> None:
        content = f"---\ndescription: d\n{frontmatter}---\n\nbody\n"
        assert _parse_roles(content, "x.md") == frozenset(expected)

    @pytest.mark.parametrize(
        "value",
        ["", "wizard", "lead,,worker", "lead,", "core", "core, lead"],
    )
    def test_invalid_roles_are_rejected(self, value: str) -> None:
        content = f"---\nroles: {value}\n---\n\nbody\n"
        with pytest.raises(ValueError, match="x.md"):
            _parse_roles(content, "x.md")

    def test_legacy_pi_roles_key_is_not_read(self) -> None:
        content = "---\npi_roles: lead\n---\n\nbody\n"
        assert _parse_roles(content, "x.md") == frozenset({"core"})


def _rule_overlay(root: Path, **rules: tuple[str, str]) -> Path:
    """Build an overlay of shared rules, each given as ``name=(roles, text)``."""
    rules_dir = root / "shared" / "rules"
    rules_dir.mkdir(parents=True)
    for name, (roles, text) in rules.items():
        header = f"---\nroles: {roles}\n---\n\n" if roles else ""
        (rules_dir / f"{name}.md").write_text(
            f"{header}# {name}\n\n{text}\n", encoding="utf-8"
        )
    return root


class TestPiRoleRules:
    @pytest.fixture
    def herdsman_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        overlay = _rule_overlay(
            tmp_path / "overlay",
            zz_lead=("lead", "LEAD-MARKER"),
            zz_worker=("reasoner, worker", "WORKER-MARKER"),
            zz_core=("", "CORE-MARKER"),
        )
        home = tmp_path / "home"
        _install(home, tmp_path / "installed.json", [overlay])
        return home / ".pi" / "agent"

    def test_lead_agents_md_holds_core_and_lead_rules_only(
        self, herdsman_home: Path
    ) -> None:
        lead = (herdsman_home / "AGENTS.md").read_text(encoding="utf-8")
        assert "LEAD-MARKER" in lead
        assert "CORE-MARKER" in lead
        assert "WORKER-MARKER" not in lead

    def test_every_rule_is_written_as_a_shared_file(self, herdsman_home: Path) -> None:
        rules = herdsman_home / "rules"
        assert "WORKER-MARKER" in (rules / "zz_worker.md").read_text(encoding="utf-8")
        assert "LEAD-MARKER" in (rules / "zz_lead.md").read_text(encoding="utf-8")

    def test_definitions_reference_their_roles_rules_without_inlining_them(
        self, herdsman_home: Path
    ) -> None:
        worker = (herdsman_home / "agents" / "worker.md").read_text(encoding="utf-8")
        body = worker.split("---\n", 2)[2]
        lines = body.splitlines()
        assert "@../rules/zz_worker.md" in lines
        assert "@../rules/zz_core.md" in lines
        assert "@../rules/coding-python.md" in lines
        assert "@../rules/zz_lead.md" not in lines
        assert "@../rules/agent-teams.md" not in lines
        references = [line for line in lines if line.startswith("@../rules/")]
        assert references == sorted(references)
        assert "WORKER-MARKER" not in worker

    @pytest.mark.parametrize(
        "definition",
        [
            "coordinator-sonnet-low",
            "reasoner",
            "worker",
            "surveyor",
            "reviewer",
        ],
    )
    def test_rule_without_roles_reaches_every_role(
        self, herdsman_home: Path, definition: str
    ) -> None:
        text = (herdsman_home / "agents" / f"{definition}.md").read_text(
            encoding="utf-8"
        )
        assert "@../rules/zz_core.md" in text.split("---\n", 2)[2].splitlines()

    def test_global_context_is_not_inherited_but_project_context_is(
        self, herdsman_home: Path
    ) -> None:
        worker = _frontmatter(herdsman_home / "agents" / "worker.md")
        assert worker["inheritGlobalContext"] is False
        assert worker["inheritProjectContext"] is True


class TestPiRoleSizes:
    def test_measured_bytes_equal_the_installed_expansion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        overlay = _rule_overlay(
            tmp_path / "overlay",
            zz_lead=("lead", "LEAD-MARKER"),
            zz_worker=("worker", "WORKER-MARKER"),
        )
        home = tmp_path / "home"
        _install(home, tmp_path / "installed.json", [overlay])
        agent_dir = home / ".pi" / "agent"

        with patch(
            "llm_prompts.install.shutil.which",
            side_effect=lambda c: "/usr/bin/herdr" if c == "herdr" else _REAL_WHICH(c),
        ):
            result = check([prompts_dir("llm_prompts"), overlay], targets=("pi",))

        measured = {
            a.dest_name: a.value
            for a in result.artifacts
            if a.metric == PI_ROLE_PROMPT_BYTES
        }
        assert measured["lead"] == len((agent_dir / "AGENTS.md").read_bytes())
        for path in (agent_dir / "agents").glob("*.md"):
            if path.name not in measured:
                continue
            body = path.read_text(encoding="utf-8").split("---\n", 2)[2].strip("\n")
            expanded = "\n".join(
                (agent_dir / "rules" / line.removeprefix("@../rules/")).read_text(
                    encoding="utf-8"
                )
                if line.startswith("@../rules/")
                else line
                for line in body.split("\n")
            )
            assert measured[path.name] == len(expanded.encode()), path.name
        assert {"worker.md", "reasoner.md"} <= measured.keys()
        assert "Explore.md" in measured


def _agent_overlay_with_rules(root: Path) -> Path:
    """Build an overlay of agents covering explicit, isolated and custom-role sources."""
    agents = root / "shared" / "agents"
    agents.mkdir(parents=True)
    for name, extra in (
        ("explicit", "rules: zz_core\n"),
        ("isolated", "omitClaudeMd: true\n"),
        ("custom", ""),
    ):
        (agents / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: d\n{extra}---\n\nBody {name}.\n",
            encoding="utf-8",
        )
    return root


def _references(path: Path) -> list[str]:
    """List the rule references of an installed definition."""
    return [
        line.removeprefix("@../rules/")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("@../rules/")
    ]


class TestPiRoleSelection:
    @pytest.fixture
    def agent_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        overlay = _rule_overlay(
            tmp_path / "overlay",
            zz_core=("", "CORE-MARKER"),
            zz_lead=("lead", "LEAD-MARKER"),
        )
        _agent_overlay_with_rules(overlay)
        home = tmp_path / "home"
        _install(home, tmp_path / "installed.json", [overlay])
        return home / ".pi" / "agent"

    def test_roles_differ_by_their_selectors(self, agent_dir: Path) -> None:
        agents = agent_dir / "agents"
        coordinator = _references(agents / "coordinator-sonnet-low.md")
        worker = _references(agents / "worker.md")
        assert "delegation.md" in coordinator
        assert "delegation.md" not in worker
        assert "git.md" in worker
        assert "git.md" not in coordinator
        assert "agent-teams.md" not in coordinator + worker

    def test_explicit_rules_isolated_and_custom_sources(self, agent_dir: Path) -> None:
        agents = agent_dir / "agents"
        assert _references(agents / "explicit.md") == ["zz_core.md"]
        assert _frontmatter(agents / "explicit.md")["inheritProjectContext"] is False
        assert _references(agents / "isolated.md") == []
        assert _frontmatter(agents / "isolated.md")["inheritProjectContext"] is False
        assert _references(agents / "Explore.md") == []
        custom = _references(agents / "custom.md")
        assert custom == sorted(p.name for p in (agent_dir / "rules").glob("*.md"))
        assert _frontmatter(agents / "custom.md")["inheritProjectContext"] is True

    def test_installs_under_a_custom_agent_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_dir = tmp_path / "custom-agent"
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))
        home = tmp_path / "home"
        home.mkdir()

        _install(home, tmp_path / "installed.json")

        assert (agent_dir / "rules" / "coding.md").is_file()
        assert "coding.md" in _references(agent_dir / "agents" / "worker.md")
        assert not (home / ".pi").exists()


class TestPiRoleLifecycle:
    def _overlay(self, tmp_path: Path) -> Path:
        return _rule_overlay(
            tmp_path / "overlay",
            zz_core=("", "CORE-MARKER"),
            zz_worker=("worker", "WORKER-MARKER"),
        )

    def test_removed_rule_file_is_cleaned_up_after_reinstall(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        overlay, manifest = self._overlay(tmp_path), tmp_path / "installed.json"
        home = tmp_path / "home"
        _install(home, manifest, [overlay])
        rule_file = home / ".pi" / "agent" / "rules" / "zz_worker.md"
        assert rule_file.is_file()

        (overlay / "shared" / "rules" / "zz_worker.md").unlink()
        _install(home, manifest, [overlay])

        assert not rule_file.exists()
        assert "zz_worker.md" not in _references(
            home / ".pi" / "agent" / "agents" / "worker.md"
        )

    def test_uninstall_removes_rule_files_and_their_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        manifest, home = tmp_path / "installed.json", tmp_path / "home"
        _install(home, manifest)

        with (
            patch("llm_prompts.install.Path.home", return_value=home),
            patch("llm_prompts.manifest.manifest_path", return_value=manifest),
        ):
            uninstall(["pi"])

        assert not (home / ".pi" / "agent" / "rules").exists()

    def test_only_install_keeps_cached_text_and_selectors_of_other_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        overlay, manifest = self._overlay(tmp_path), tmp_path / "installed.json"
        home = tmp_path / "home"
        _install(home, manifest, [overlay])
        agent_dir = home / ".pi" / "agent"
        edited = overlay / "shared" / "rules" / "zz_core.md"
        edited.write_text("---\nroles: lead\n---\n\n# zz_core\n\nEDITED-MARKER\n")

        _install(home, manifest, [overlay], only=edited)

        lead = (agent_dir / "AGENTS.md").read_text(encoding="utf-8")
        assert "EDITED-MARKER" in lead
        assert "# Canary" in lead
        assert "WORKER-MARKER" not in lead
        recorded = json.loads(manifest.read_text(encoding="utf-8"))["agents"]["pi"]
        assert recorded["pi_rule_roles"]["zz_core.md"] == ["lead"]
        assert recorded["pi_rule_roles"]["zz_worker.md"] == ["worker"]
        assert str(agent_dir / "rules" / "zz_worker.md") in recorded["files"]

    def test_skipped_rule_with_no_cached_copy_keeps_the_previous_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        overlay, manifest = self._overlay(tmp_path), tmp_path / "installed.json"
        home = tmp_path / "home"
        _install(home, manifest, [overlay])
        agent_dir = home / ".pi" / "agent"
        sentinels = [
            agent_dir / "agents" / "worker.md",
            agent_dir / "rules" / "zz_core.md",
            agent_dir / "AGENTS.md",
        ]
        for path in sentinels:
            path.write_text("SENTINEL", encoding="utf-8")
        shutil.rmtree(manifest_module.rendered_rules_dir() / "pi")
        skipped = overlay / "shared" / "rules" / "zz_core.md"
        violation = Violation(RULE_BYTES, "pi", "zz_core.md", 9, 1, skipped)

        with patch(
            "llm_prompts.size_guard.check",
            return_value=CheckResult(False, [], [violation], ""),
        ):
            _install(home, manifest, [overlay])

        assert all(p.read_text(encoding="utf-8") == "SENTINEL" for p in sentinels)
        recorded = json.loads(manifest.read_text(encoding="utf-8"))["agents"]["pi"]
        assert all(str(p) in recorded["files"] for p in sentinels)
        assert "zz_core.md" in recorded["pi_rule_roles"]


class TestExpandedDefinition:
    def test_includes_each_rule_once_without_expanding_its_references(self) -> None:
        texts = {"a.md": "A\n@../rules/b.md\n", "b.md": "B\n"}
        content = "---\nname: x\n---\n@../rules/a.md\n@../rules/a.md\n\nBody\n"

        assert _expanded_definition(content, texts) == "A\n@../rules/b.md\n\n\nBody"

    @pytest.mark.parametrize(
        ("texts", "message"),
        [
            ({}, "unresolved"),
            ({"a.md": "A\0"}, "NUL"),
            ({"a.md": "A\ud800"}, "UTF-8"),
        ],
    )
    def test_unusable_dependency_is_rejected(
        self, texts: dict[str, str], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            _expanded_definition("---\nname: x\n---\n@../rules/a.md\n", texts)


_ROLES_LINE = re.compile(r"^roles: .*\n", re.MULTILINE)
_OTHER_FRONTENDS = [
    "cline",
    "copilot",
    "kiro",
    "claude-code",
    "codex",
    "antigravity",
]
_INSTALLED_PROMPTS = (
    ".cline_merged/rules",
    ".copilot/instructions",
    ".kiro/steering",
    ".claude/rules",
    ".claude/agents",
    ".codex/AGENTS.md",
    ".gemini/config/AGENTS.md",
)


def _tree_bytes(root: Path, relatives: tuple[str, ...]) -> dict[str, bytes]:
    """Read every file under the given paths of a fake home."""
    found: dict[str, bytes] = {}
    for relative in relatives:
        base = root / relative
        for path in [base] if base.is_file() else sorted(base.rglob("*")):
            if path.is_file():
                found[str(path.relative_to(root))] = path.read_bytes()
    return found


def _untagged_rules_overlay(root: Path) -> Path:
    """Build an overlay holding every core shared rule with its roles removed."""
    rules = root / "shared" / "rules"
    rules.mkdir(parents=True)
    for src in (prompts_dir("llm_prompts") / "shared" / "rules").glob("*.md"):
        (rules / src.name).write_text(
            strip_gating_keys(src.read_text(encoding="utf-8"), {"roles"}),
            encoding="utf-8",
        )
    return root


class TestRoleMetadataLeavesOtherOutputUnchanged:
    def test_other_frontends_are_byte_identical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
        untagged = _untagged_rules_overlay(tmp_path / "untagged")
        assert not _ROLES_LINE.search(
            "".join(p.read_text() for p in untagged.rglob("*.md"))
        )
        outputs = {}
        for label, overlays in (("tagged", []), ("untagged", [untagged])):
            home = tmp_path / label
            _install(
                home,
                tmp_path / f"{label}.json",
                overlays,
                targets=_OTHER_FRONTENDS,
            )
            outputs[label] = _tree_bytes(home, _INSTALLED_PROMPTS)

        assert outputs["tagged"].keys() == outputs["untagged"].keys()
        assert len(outputs["tagged"]) > 100
        assert outputs["tagged"] == outputs["untagged"]
        assert not any(b"\nroles:" in data for data in outputs["tagged"].values())

    def test_linked_agent_specific_rule_drops_roles(self, tmp_path: Path) -> None:
        rule = tmp_path / "rule.md"
        rule.write_text("---\nroles: lead\ndescription: d\n---\n\nBody\n")

        assert _linked_content(rule) == "---\ndescription: d\n---\n\nBody\n"


def _installed_package(home: Path, name: str, version: str | None) -> None:
    """Fake an npm package pi already installed into a fake home."""
    manifest = home / ".pi" / "agent" / "npm" / "node_modules" / name / "package.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"name": name, **({"version": version} if version else {})}),
        encoding="utf-8",
    )


class TestPiPackageInstall:
    def _run(
        self,
        tmp_path: Path,
        source: str,
        *,
        installed: tuple[str, str | None] | None = None,
        pi: str | None = "/usr/bin/pi",
        returncode: int = 0,
    ) -> tuple[list[list[str]], bool]:
        """Install one synthetic package, returning the pi commands run and the failure flag."""
        home = tmp_path / "home"
        home.mkdir()
        if installed:
            _installed_package(home, *installed)
        calls: list[list[str]] = []

        def run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode * (source in cmd))

        with patch("llm_prompts.install.subprocess.run", side_effect=run):
            failed = _install(
                home,
                tmp_path / "installed.json",
                [_overlay(tmp_path / "overlay", [source])],
                pi=pi,
            )
        return [c for c in calls if source in c], failed

    @pytest.mark.parametrize(
        ("source", "installed", "expected_runs"),
        [
            ("npm:acme-ext@1.0.0", None, 1),
            ("npm:acme-ext@1.0.0", ("acme-ext", "0.9.0"), 1),
            ("npm:acme-ext@1.0.0", ("acme-ext", "1.0.0"), 0),
            ("npm:@acme/ext@2.0.0", None, 1),
            ("npm:@acme/ext@2.0.0", ("@acme/ext", "2.0.0"), 0),
            ("npm:acme-ext", ("acme-ext", None), 0),
            ("npm:acme-ext", None, 1),
        ],
    )
    def test_installs_only_packages_not_already_at_pinned_version(
        self,
        tmp_path: Path,
        source: str,
        installed: tuple[str, str | None] | None,
        expected_runs: int,
    ) -> None:
        calls, _ = self._run(tmp_path, source, installed=installed)

        assert calls == [["/usr/bin/pi", "install", source]] * expected_runs

    def test_missing_pi_runs_nothing_and_does_not_fail(self, tmp_path: Path) -> None:
        calls, failed = self._run(tmp_path, "npm:acme-ext@1.0.0", pi=None)

        assert calls == []
        assert not failed

    def test_failed_install_is_reported_as_failure(self, tmp_path: Path) -> None:
        _, failed = self._run(tmp_path, "npm:acme-ext@1.0.0", returncode=1)

        assert failed


class TestPiPackageRemoval:
    def _install(
        self, tmp_path: Path, packages: list[str], *, broken: str = ""
    ) -> list[list[str]]:
        """Install the given overlay packages with a fake pi whose `broken` command fails, returning the pi commands run."""
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        calls: list[list[str]] = []

        def run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            name, version = _split_npm_source(cmd[2])
            package = home / ".pi" / "agent" / "npm" / "node_modules" / name
            if cmd[1] == broken and name == "acme-ext":
                pass
            elif cmd[1] == "remove":
                shutil.rmtree(package)
            else:
                package.mkdir(parents=True, exist_ok=True)
                (package / "package.json").write_text(json.dumps({"version": version}))
            return subprocess.CompletedProcess(
                cmd, int(cmd[1] == broken and name == "acme-ext")
            )

        with patch("llm_prompts.install.subprocess.run", side_effect=run):
            _install(
                home,
                tmp_path / "installed.json",
                [_overlay(tmp_path / "overlay", packages)],
                pi="/usr/bin/pi",
            )
        return calls

    def test_dropped_owned_package_is_removed_until_gone(self, tmp_path: Path) -> None:
        self._install(tmp_path, ["npm:acme-ext"])
        with patch(
            "llm_prompts.size_guard.resolve_skip_set",
            return_value=({}, frozenset({"pi"})),
        ):
            self._install(tmp_path, [])
        self._install(tmp_path, [], broken="remove")

        calls = self._install(tmp_path, [])

        assert ["/usr/bin/pi", "remove", "npm:acme-ext"] in calls

    @pytest.mark.parametrize(
        ("listed", "disk", "source", "broken"),
        [
            (True, False, "npm:acme-ext", ""),
            (True, False, "npm:acme-ext@1.0.0", ""),
            (False, True, "npm:acme-ext", ""),
            (False, True, "npm:acme-ext@1.0.0", ""),
            (False, False, "npm:acme-ext", "install"),
        ],
    )
    def test_dropped_unowned_package_is_only_unlisted(
        self, tmp_path: Path, listed: bool, disk: bool, source: str, broken: str
    ) -> None:
        settings = tmp_path / "home" / ".pi" / "agent" / "settings.json"
        settings.parent.mkdir(parents=True)
        if listed:
            settings.write_text(json.dumps({"packages": ["npm:acme-ext"]}))
        if disk:
            _installed_package(tmp_path / "home", "acme-ext", "0.9.0")
        self._install(tmp_path, [source], broken=broken)

        calls = self._install(tmp_path, [])

        assert not [c for c in calls if c[1] == "remove"]

    def test_uninstall_removes_only_owned_packages(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _installed_package(tmp_path / "home", "user-ext", None)
        self._install(tmp_path, ["npm:acme-ext", "npm:user-ext"])
        calls: list[list[str]] = []

        with (
            patch("llm_prompts.install.Path.home", return_value=tmp_path / "home"),
            patch("llm_prompts.install.shutil.which", return_value="/usr/bin/pi"),
            patch(
                "llm_prompts.manifest.manifest_path",
                return_value=tmp_path / "installed.json",
            ),
            patch(
                "llm_prompts.install.subprocess.run",
                side_effect=lambda cmd, **_: calls.append(cmd),
            ),
        ):
            uninstall(["pi"])

        removed = [c[2] for c in calls if c[1] == "remove"]
        assert "npm:acme-ext" in removed
        assert "npm:user-ext" not in removed
        assert "`pi remove npm:acme-ext`" in capsys.readouterr().err
