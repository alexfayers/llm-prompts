"""The home directory every installed path is derived from."""

from __future__ import annotations

import sys
from pathlib import Path

from platformdirs import user_data_dir

from . import tool_paths
from .path_migration import migrate, unready_kinds

TOOL = "llm-prompts"
_KIND_OF_OLD_CONFIG_FILE = {
    "contribute-worktrees.json": "data",
    "receipts.json": "data",
    "primary-blocks.json": "state",
    "telemetry.json": "state",
}
_OLD_DATA_FILES = (
    "auto-update.lock",
    "auto-update-failed.json",
    "auto-update.log",
    ".llm-prompts-pyproject-stamp",
    ".llm-prompts-checkout-stamp",
)


def _old_config_kind(name: str) -> str:
    bare = name.lstrip(".")
    return next(
        (
            kind
            for file, kind in _KIND_OF_OLD_CONFIG_FILE.items()
            if bare == file or bare.startswith(f"{file}.")
        ),
        "config",
    )


def _legacy_path(old_home: Path, kind: str, name: str) -> Path:
    """Return where ``name`` of the ``kind`` folder lived before the shared root."""
    if kind == "cache":
        return old_home / ".cache" / TOOL / name
    if kind == "state" and old_home == Path.home():
        if name == "benchmark":
            return old_home / ".local" / "state" / TOOL / name
        if name in _OLD_DATA_FILES:
            return Path(user_data_dir(TOOL)) / name
    return old_home / ".config" / TOOL / name


class Home:
    """The install root, or the user's home directory when none is set."""

    def __init__(self) -> None:
        """Start without an install root."""
        self.root: Path | None = None
        self._migrated: set[Path] = set()
        self._on_old_paths: set[tuple[Path, str]] = set()

    def user_home(self) -> Path:
        """Return the install root, defaulting to the user's home directory."""
        return self.root or Path.home()

    def is_rooted(self) -> bool:
        """Return whether an install root replaces the user's home directory."""
        return self.root is not None

    def tool_dir(self, kind: str, name: str = "") -> Path:
        """Return ``name`` in the llm-prompts ``kind`` folder, under the install root when one is set."""
        if self.root is None:
            return self.live_dir(kind, name)
        return self._location(
            self.root / ".local" / "share" / TOOL, self.root, kind, name
        )

    def live_dir(self, kind: str, name: str = "") -> Path:
        """Return ``name`` in the user's llm-prompts ``kind`` folder, ignoring any install root."""
        return self._location(tool_paths.root(), Path.home(), kind, name)

    def config_dir(self) -> Path:
        """Return the llm-prompts config directory under the install root."""
        return self.tool_dir("config")

    def _location(self, base: Path, old_home: Path, kind: str, name: str) -> Path:
        """Return ``name`` in the ``kind`` folder, or its old place while the old files are not copied."""
        if base not in self._migrated:
            self._migrated.add(base)
            self._migrate(base, old_home)
        if (base, kind) in self._on_old_paths:
            return _legacy_path(old_home, kind, name)
        return tool_paths.tool_dir(TOOL, kind, base) / name

    def _migrate(self, base: Path, old_home: Path) -> None:
        from .setup import _running_as_installed_tool

        tool_root = base / TOOL
        copies: list[tuple[Path, Path]] = []
        try:
            copies = self._old_paths(base, old_home)
            if not unready_kinds(tool_root, copies) or not _running_as_installed_tool():
                return
            failures = migrate(tool_root, copies)
        except OSError as error:
            failures = dict.fromkeys(
                unready_kinds(tool_root, copies) or tool_paths.KINDS,
                f"{tool_root}: {error.strerror or error}",
            )
        self._on_old_paths |= {(base, kind) for kind in failures}
        if failures:
            print(
                f"llm-prompts could not copy its old files to {tool_root}. "
                "It keeps using the old folders until the copy works:",
                *failures.values(),
                sep="\n  ",
                file=sys.stderr,
            )

    def _old_paths(self, base: Path, old_home: Path) -> list[tuple[Path, Path]]:
        def new(kind: str, name: str) -> Path:
            return tool_paths.tool_dir(TOOL, kind, base) / name

        old_config = old_home / ".config" / TOOL
        copies = [
            (old, new(_old_config_kind(old.name), old.name))
            for old in (sorted(old_config.iterdir()) if old_config.is_dir() else [])
        ]
        if old_home == Path.home():
            old_data = Path(user_data_dir(TOOL))
            copies += [
                (old_data / name, new("state", name)) for name in _OLD_DATA_FILES
            ]
            old_cache = old_home / ".cache" / TOOL
            copies += [
                (old_cache / "watch", new("cache", "watch")),
                (
                    old_cache / "benchmark" / "variants",
                    new("cache", "benchmark/variants"),
                ),
                (
                    old_home / ".local" / "state" / TOOL / "benchmark",
                    new("state", "benchmark"),
                ),
            ]
        return copies


_HOME = Home()


def user_home() -> Path:
    """Return the install root, defaulting to the user's home directory."""
    return _HOME.user_home()


def is_rooted() -> bool:
    """Return whether an install root replaces the user's home directory."""
    return _HOME.is_rooted()


def config_dir() -> Path:
    """Return the llm-prompts config directory under the install root."""
    return _HOME.config_dir()


def data_dir(name: str = "") -> Path:
    """Return ``name`` in the llm-prompts data directory under the install root."""
    return _HOME.tool_dir("data", name)


def state_dir(name: str = "") -> Path:
    """Return ``name`` in the llm-prompts state directory under the install root."""
    return _HOME.tool_dir("state", name)


def live_dir(kind: str, name: str = "") -> Path:
    """Return ``name`` in the user's llm-prompts ``kind`` folder, ignoring any install root."""
    return _HOME.live_dir(kind, name)


def set_root(root: Path) -> None:
    """Use ``root`` as the home directory.

    Args:
        root: Directory to install under.
    """
    _HOME.root = root
