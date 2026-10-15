"""The home directory every installed path is derived from."""

from __future__ import annotations

from pathlib import Path


class Home:
    """The install root, or the user's home directory when none is set."""

    def __init__(self) -> None:
        """Start without an install root."""
        self.root: Path | None = None

    def user_home(self) -> Path:
        """Return the install root, defaulting to the user's home directory."""
        return self.root or Path.home()

    def is_rooted(self) -> bool:
        """Return whether an install root replaces the user's home directory."""
        return self.root is not None

    def config_dir(self) -> Path:
        """Return the llm-prompts config directory under the install root."""
        return self.user_home() / ".config" / "llm-prompts"


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


def set_root(root: Path) -> None:
    """Use ``root`` as the home directory.

    Args:
        root: Directory to install under.
    """
    _HOME.root = root
