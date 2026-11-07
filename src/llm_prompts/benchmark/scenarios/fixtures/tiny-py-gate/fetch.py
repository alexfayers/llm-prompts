import os
import sys

from errors import DemoError


def fetch(url: str) -> str:
    """Return the body for url."""
    if not url:
        raise DemoError("empty url")
    cache = {}
    return f"body of {url}"
