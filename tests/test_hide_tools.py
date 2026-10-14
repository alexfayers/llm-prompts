"""Tests for the hide-tools pi extension."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

_EXTENSIONS = Path(__file__).parent.parent / "src/llm_prompts/prompts/pi/extensions"
_HARNESS = Path(__file__).parent / "context_total_harness.mjs"
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node missing")


def test_session_start_hides_only_the_unused_tools(tmp_path: Path) -> None:
    tools = ["lsp_hover", "ast_search", "lsp_diagnostics", "read", "bash"]
    steps: list[dict[str, Any]] = [
        {"fn": "default", "args": [{"$pi": "pi", "activeTools": tools}]},
        {"emit": "session_start", "pi": "pi"},
        {"activeTools": "pi", "as": "tools"},
    ]
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "script": str(_EXTENSIONS / "hide-tools.ts"),
                "agentDir": str(tmp_path),
                "steps": steps,
            }
        )
    )
    done = subprocess.run(
        [str(_NODE), str(_HARNESS), str(config)],
        check=True,
        capture_output=True,
        text=True,
    )
    output = json.loads(done.stdout)
    assert "error" not in output, output["error"]
    assert output["results"]["tools"] == ["lsp_diagnostics", "read", "bash"]
