"""The settings command: show and check the config file."""

from __future__ import annotations

import importlib
import sys
from typing import Any, NamedTuple

from .benchmark.command import DEFAULT_JOBS, at_least_one
from .exit_reason import ExitReason
from .guards.review_limit import DEFAULT_LIMIT
from .setup import config_errors, config_path, read_config, redact_credentials


class Setting(NamedTuple):
    """One scalar config key and the value used when the file leaves it out."""

    table: str
    key: str
    default: bool | int


SETTINGS = (
    Setting("update", "auto", True),
    Setting("telemetry", "enabled", True),
    Setting("reviews", "max_in_flight", DEFAULT_LIMIT),
    Setting("benchmark", "jobs", DEFAULT_JOBS),
)
_MISSING_EXTRA = (
    "The settings editor needs the llm-prompts[tui] extra, which adds textual. "
    "Run `llm-prompts settings --check` to print the config instead."
)


def _toml_value(value: Any) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def _entries(title: str, entries: Any) -> list[str]:
    if not isinstance(entries, list) or not entries:
        return [f"{title}: none"]
    return [f"{title}:"] + [
        redact_credentials(
            f"  {entry.get('name')}  {entry.get('source')}"
            if isinstance(entry, dict)
            else f"  {entry!r}"
        )
        for entry in entries
    ]


def report(config: dict[str, Any]) -> list[str]:
    """Return the lines that show a parsed config's tools, plugins and settings."""
    lines = [
        f"Config: {config_path()}",
        "",
        *_entries("Tools", config.get("tools")),
        *_entries("Plugins", config.get("plugins")),
        "",
    ]
    for setting in SETTINGS:
        table = config.get(setting.table)
        table = table if isinstance(table, dict) else {}
        name = f"{setting.table}.{setting.key}"
        if setting.key in table:
            lines.append(f"{name} = {_toml_value(table[setting.key])}")
        else:
            lines.append(f"{name} = {_toml_value(setting.default)} (default)")
        if setting.key == "max_in_flight" and isinstance(table.get("repos"), dict):
            lines.extend(
                f"reviews.repos.{scope} = {_toml_value(limit)}"
                for scope, limit in table["repos"].items()
            )
    return lines


def _benchmark_errors(config: dict[str, Any]) -> list[str]:
    if "benchmark" not in config:
        return []
    benchmark = config["benchmark"]
    if not isinstance(benchmark, dict):
        return ["[benchmark] must be a table"]
    if "jobs" not in benchmark:
        return []
    try:
        at_least_one("benchmark.jobs", benchmark["jobs"])
    except ValueError as error:
        return [str(error)]
    return []


def config_problems(config: dict[str, Any]) -> list[str]:
    """Return every problem in a parsed config that the settings command reports."""
    return config_errors(config) + _benchmark_errors(config)


def _has_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def run(*, check: bool) -> None:
    """Open the settings editor in a terminal, or print the config and its errors.

    Args:
        check: Print the config even in a terminal.

    Raises:
        ExitReason: ``config_invalid`` when the config has errors or is not
            valid TOML, or ``other`` when the editor's extra is not installed.
    """
    if not check and _has_terminal():
        try:
            importlib.import_module("textual")
        except ImportError:
            raise ExitReason("other", _MISSING_EXTRA) from None
        from .config_edit import load_doc
        from .settings_app import SettingsApp

        SettingsApp(load_doc()).run()
        return
    config = read_config()
    print("\n".join(report(config)))
    errors = config_problems(config)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise ExitReason("config_invalid")
