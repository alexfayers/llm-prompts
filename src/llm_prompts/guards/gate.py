"""The gate for every guard: pi with the pi-context runtime."""

from __future__ import annotations

import os

from cline_hooks.core.frontend import FRONTEND_ENV_KEY

from ..herdsman import pi_runtime


def guards_active() -> bool:
    """Report whether the guards run: pi frontend and the pi-context runtime."""
    return os.environ.get(FRONTEND_ENV_KEY) == "pi" and pi_runtime() == "pi-context"
