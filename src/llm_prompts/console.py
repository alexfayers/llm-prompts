"""Print levelled status messages to stderr."""

import os
import sys
from typing import Literal

from .colors import Color, paint

LogLevel = Literal["debug", "info", "warn", "error", "success"]

_COLORS: dict[LogLevel, Color] = {
    "debug": "grey",
    "info": "white",
    "warn": "yellow",
    "error": "red",
    "success": "green",
}
_SYMBOLS: dict[LogLevel, str] = {
    "debug": "[.]",
    "info": "[>]",
    "warn": "[!]",
    "error": "[x]",
    "success": "[+]",
}
_PLAIN_SYMBOLS: dict[LogLevel, str] = {
    "debug": "[.]",
    "info": "[*]",
    "warn": "[-]",
    "error": "[!]",
    "success": "[+]",
}


_verbose = False


def log(level: LogLevel, message: str) -> None:
    """Log a message with appropriate formatting.

    Args:
        level: Log level.
        message: Message to print.
    """
    if level == "debug" and not _verbose:
        return
    try:
        if sys.stderr.isatty():
            print(
                paint(f"{_SYMBOLS[level]} {message}", _COLORS[level]), file=sys.stderr
            )
        else:
            print(f"{_PLAIN_SYMBOLS[level]} {message}", file=sys.stderr)
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stderr.fileno())
