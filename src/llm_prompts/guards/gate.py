"""The gate for every guard: the pi frontend."""

from __future__ import annotations

import os

from cline_hooks.core.frontend import FRONTEND_ENV_KEY


def guards_active() -> bool:
    """Report whether the guards run: the pi frontend."""
    return os.environ.get(FRONTEND_ENV_KEY) == "pi"
