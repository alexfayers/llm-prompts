"""Tests for the reusable GitHub workflows."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"


def _inline_python(workflow: str) -> ast.Module:
    """Parse the Python heredoc embedded in a workflow's run steps."""
    steps = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))["jobs"][
        "prompt-check"
    ]["steps"]
    script: str = next(s["run"] for s in steps if "<<'PY'" in s.get("run", ""))
    return ast.parse(script.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0])


def test_prompt_checks_imports_resolve() -> None:
    for node in ast.walk(_inline_python("prompt-checks.yml")):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = importlib.import_module(node.module)
            for alias in node.names:
                assert hasattr(module, alias.name), f"{node.module}.{alias.name}"


def test_reusable_jobs_that_check_out_grant_contents_read() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "workflow_call" not in workflow[True]:
            continue
        for name, job in workflow["jobs"].items():
            if any("actions/checkout" in s.get("uses", "") for s in job["steps"]):
                permissions = job.get("permissions", workflow.get("permissions", {}))
                assert permissions.get("contents") == "read", f"{path.name}:{name}"
