"""Tests for the credential-expiry pi extension."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "extensions"
    / "credential-expiry.ts"
)
_HARNESS = Path(__file__).parent / "context_total_harness.mjs"
_DOMAIN = "example.test"


def _can_strip_types() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run(
        [node, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not _can_strip_types(), reason="node with type stripping missing"
)


def _run(tmp_path: Path, steps: list[dict[str, Any]]) -> dict[str, Any]:
    config = tmp_path / "config.json"
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir(exist_ok=True)
    config.write_text(
        json.dumps({"script": str(_SCRIPT), "agentDir": str(agent_dir), "steps": steps})
    )
    done = subprocess.run(
        ["node", str(_HARNESS), str(config)],
        check=True,
        capture_output=True,
        text=True,
    )
    output: dict[str, Any] = json.loads(done.stdout)
    assert "error" not in output, output["error"]
    results: dict[str, Any] = output["results"]
    return results


def _cookie(*rows: tuple[str, int], http_only: bool = False) -> str:
    lines = ["# Netscape HTTP Cookie File", "# generated for tests", ""]
    for domain, expiry in rows:
        prefix = "#HttpOnly_" if http_only else ""
        lines.append(f"{prefix}{domain}\tTRUE\t/\tTRUE\t{expiry}\tsession\tvalue")
    return "\n".join(lines) + "\n"


class TestParseExpiry:
    """Tests for picking the expiry out of a Netscape cookie file."""

    def test_soonest_expiry_of_the_matching_domain_ignoring_comments_and_other_hosts(
        self, tmp_path: Path
    ) -> None:
        text = (
            _cookie(("other.test", 100), (f".{_DOMAIN}", 5000), (_DOMAIN, 3000))
            + _cookie((f"api.{_DOMAIN}", 9000), http_only=True)
            + _cookie((_DOMAIN, 0))
            + "short\tline\n"
        )
        steps: list[dict[str, Any]] = [
            {"fn": "parseExpiry", "args": [text, _DOMAIN], "as": "matched"},
            {"fn": "parseExpiry", "args": [text, ""], "as": "any"},
            {"fn": "parseExpiry", "args": [text, "absent.test"], "as": "none"},
        ]
        results = _run(tmp_path, steps)
        assert results["matched"] == 3000
        assert results["any"] == 100
        assert "none" not in results


_YELLOW = "\x1b[33m"
_RED = "\x1b[31m"
_RESET = "\x1b[0m"
_NOW = 1_000_000
_HOUR = 3600
_MINUTE = 60


class TestFormatRemaining:
    """Tests for the footer text of the time left."""

    def test_hours_and_minutes_then_warning_colour_then_red_when_expired_or_unknown(
        self, tmp_path: Path
    ) -> None:
        def fmt(expiry: int | None, name: str) -> dict[str, Any]:
            args: list[Any] = [expiry, _NOW, _HOUR]
            return {"fn": "formatRemaining", "args": args, "as": name}

        steps = [
            fmt(_NOW + 7 * _HOUR + 12 * _MINUTE, "plenty"),
            fmt(_NOW + 2 * _HOUR + 5 * _MINUTE, "padded"),
            fmt(_NOW + _HOUR, "boundary"),
            fmt(_NOW + 42 * _MINUTE + 59, "warn"),
            fmt(_NOW + 59, "seconds"),
            fmt(_NOW, "expired"),
            fmt(None, "unknown"),
        ]
        results = _run(tmp_path, steps)
        assert results == {
            "plenty": "mw 7h12m",
            "padded": "mw 2h05m",
            "boundary": "mw 1h00m",
            "warn": f"{_YELLOW}mw 42m{_RESET}",
            "seconds": f"{_YELLOW}mw <1m{_RESET}",
            "expired": f"{_RED}mw expired{_RESET}",
            "unknown": f"{_RED}mw expired{_RESET}",
        }


class TestConfig:
    """Tests for the settings file."""

    def test_defaults_clamped_interval_and_enabled_rewrite_keeping_other_keys(
        self, tmp_path: Path
    ) -> None:
        file = tmp_path / "credential-expiry.json"
        read = {"fn": "readConfig", "args": [str(file)]}
        custom = {
            "enabled": False,
            "warnSeconds": 120,
            "cookiePath": "~/jar",
            "domain": _DOMAIN,
            "intervalSeconds": 1,
            "x": 1,
        }
        steps: list[dict[str, Any]] = [
            {**read, "as": "missing"},
            {"truncate": str(file), "text": json.dumps(custom)},
            {**read, "as": "custom"},
            {"fn": "writeEnabledSetting", "args": [str(file), True]},
            {**read, "as": "enabled"},
        ]
        results = _run(tmp_path, steps)
        assert results["missing"] == {
            "enabled": False,
            "warnSeconds": 3600,
            "cookiePath": "",
            "domain": "",
            "intervalSeconds": 60,
        }
        assert results["custom"]["intervalSeconds"] == 10
        assert results["custom"]["warnSeconds"] == 120
        assert results["custom"]["cookiePath"] == "~/jar"
        assert results["enabled"]["enabled"] is True
        assert json.loads(file.read_text()) == {**custom, "enabled": True}


class TestReadExpiry:
    """Tests for reading the cookie file only when it has changed."""

    def test_rereads_only_on_new_mtime_expands_home_and_treats_a_missing_file_as_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        jar = tmp_path / "jar"
        read = {
            "fn": "readExpiry",
            "args": [{"$ref": "cache"}, "~/jar", _DOMAIN],
        }
        steps: list[dict[str, Any]] = [
            {"fn": "createCredentialCache", "as": "cache"},
            {**read, "as": "missing"},
            {"truncate": str(jar), "text": _cookie((_DOMAIN, 1000))},
            {"utime": str(jar), "seconds": 500},
            {**read, "as": "first"},
            {"truncate": str(jar), "text": _cookie((_DOMAIN, 2000))},
            {"utime": str(jar), "seconds": 500},
            {**read, "as": "cached"},
            {"utime": str(jar), "seconds": 600},
            {**read, "as": "changed"},
        ]
        results = _run(tmp_path, steps)
        assert "missing" not in results
        assert [results[k] for k in ("first", "cached", "changed")] == [
            1000,
            1000,
            2000,
        ]


_VARIABLE = "llm-prompts/credential-expiry:left"


class TestPublish:
    """Tests for handing the text to zentui or to a status line."""

    def _publish(
        self, tmp_path: Path, active: list[str]
    ) -> tuple[list[Any], list[Any]]:
        steps: list[dict[str, Any]] = [
            {
                "fn": "publish",
                "args": [{"$pi": "pi", "active": active}, {"$ui": "ui"}, "mw 7h12m"],
            },
            {"fn": "clear", "args": [{"$pi": "pi"}, {"$ui": "ui"}]},
            {"emitted": "pi", "as": "emitted"},
            {"ui": "ui", "as": "status"},
        ]
        results = _run(tmp_path, steps)
        return results["emitted"], results["status"]

    def test_active_variable_is_published_and_the_status_line_cleared(
        self, tmp_path: Path
    ) -> None:
        emitted, status = self._publish(tmp_path, [_VARIABLE])
        published = [p for event, p in emitted if event == "zentui:variable"]
        assert published == [
            {"key": _VARIABLE, "text": "mw 7h12m"},
            {"key": _VARIABLE},
        ]
        assert status == [["credential-expiry", None], ["credential-expiry", None]]

    def test_inactive_variable_falls_back_to_the_status_line(
        self, tmp_path: Path
    ) -> None:
        emitted, status = self._publish(tmp_path, [])
        published = [
            p for event, p in emitted if event == "zentui:variable" and "text" in p
        ]
        assert published == []
        assert status == [
            ["credential-expiry", "mw 7h12m"],
            ["credential-expiry", None],
        ]


_ENABLED = {"enabled": True, "domain": _DOMAIN}


class TestExtension:
    """Tests for the extension wiring: session events and the slash command."""

    def _configure(
        self, tmp_path: Path, config: dict[str, Any], expires_in: int
    ) -> None:
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir(exist_ok=True)
        jar = tmp_path / "jar"
        jar.write_text(_cookie((_DOMAIN, int(time.time()) + expires_in)))
        (agent_dir / "credential-expiry.json").write_text(
            json.dumps({**config, "cookiePath": str(jar)})
        )

    def _start(self) -> list[dict[str, Any]]:
        pi = {"$pi": "pi"}
        ctx = {"ui": {"$ui": "ui"}}
        return [
            {"fn": "default", "args": [pi]},
            {"emit": "session_start", "pi": "pi", "ctx": ctx},
        ]

    def test_enabled_config_shows_the_time_left_on_session_start_and_clears_on_shutdown(
        self, tmp_path: Path
    ) -> None:
        self._configure(tmp_path, _ENABLED, 7 * _HOUR + 12 * _MINUTE + 30)
        steps: list[dict[str, Any]] = [
            *self._start(),
            {"emit": "session_shutdown", "pi": "pi", "ctx": {"ui": {"$ui": "ui"}}},
            {"ui": "ui", "as": "status"},
        ]
        status = _run(tmp_path, steps)["status"]
        assert status == [
            ["credential-expiry", "mw 7h12m"],
            ["credential-expiry", None],
        ]

    def test_disabled_config_shows_nothing(self, tmp_path: Path) -> None:
        self._configure(tmp_path, {**_ENABLED, "enabled": False}, 5 * _HOUR)
        status = _run(tmp_path, [*self._start(), {"ui": "ui", "as": "status"}])[
            "status"
        ]
        assert status == []

    def test_command_toggles_the_setting_and_the_footer_and_reports_misuse(
        self, tmp_path: Path
    ) -> None:
        self._configure(tmp_path, {"enabled": False, "domain": _DOMAIN}, 5 * _HOUR + 30)
        ctx = {"ui": {"$ui": "ui"}}
        command = {"command": "credential-expiry", "pi": "pi", "ctx": ctx}
        steps: list[dict[str, Any]] = [
            *self._start(),
            {**command, "args": "on"},
            {**command, "args": "bogus"},
            {**command, "args": ""},
            {**command, "args": "off"},
            {"ui": "ui", "as": "status"},
            {"notices": "ui", "as": "notices"},
        ]
        results = _run(tmp_path, steps)
        assert results["status"] == [
            ["credential-expiry", "mw 5h00m"],
            ["credential-expiry", None],
        ]
        assert [level for _, level in results["notices"]] == [
            "info",
            "warning",
            "info",
            "info",
        ]
        saved = json.loads((tmp_path / "agent" / "credential-expiry.json").read_text())
        assert saved["enabled"] is False


_SEED = _SCRIPT.parents[1] / "seed"


class TestSeeds:
    """Tests for the seeded settings that let the footer show the text."""

    def test_zentui_footer_places_the_variable_and_the_seeded_config_is_inert(
        self,
    ) -> None:
        starship = json.loads((_SEED / "zentui.json").read_text())["components"][
            "footer"
        ]["styles"]["starship"]
        names = [n for n, key in starship["variables"].items() if key == _VARIABLE]
        assert len(names) == 1
        assert f"${names[0]}" in starship["format"]
        seeded = json.loads((_SEED / "credential-expiry.json").read_text())
        assert seeded["enabled"] is False
        assert seeded["cookiePath"] == ""
