"""ANSI terminal colors."""

from typing import Literal

Color = Literal["grey", "white", "yellow", "red", "green", "cyan"]

_CODES: dict[Color, str] = {
    "grey": "\033[0;90m",
    "white": "\033[0;37m",
    "yellow": "\033[0;33m",
    "red": "\033[0;31m",
    "green": "\033[0;32m",
    "cyan": "\033[0;36m",
}
_RESET = "\033[0;0m"


def paint(text: str, color: Color) -> str:
    """Wrap ``text`` in the ANSI escape codes for ``color``."""
    return f"{_CODES[color]}{text}{_RESET}"
