"""Rule and skill text under the pi-context runtime."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from llm_prompts.install import _requirements_met
from llm_prompts.render_template import parse_frontmatter

PROMPTS = Path(__file__).parent.parent / "src/llm_prompts/prompts"


@pytest.fixture
def set_runtime(isolated_config_dir: Path) -> Callable[[str], None]:
    """Return a function that writes the `[pi] runtime` setting."""

    def write(runtime: str) -> None:
        (isolated_config_dir / "config.toml").write_text(
            f'[pi]\nruntime = "{runtime}"\n', encoding="utf-8"
        )

    return write


class TestAgentTeamsRule:
    @pytest.mark.parametrize(
        ("runtime", "installed"), [("herdsman", True), ("pi-context", False)]
    )
    def test_only_herdsman_installs_the_rule_for_pi(
        self, set_runtime: Callable[[str], None], runtime: str, installed: bool
    ) -> None:
        set_runtime(runtime)
        _, declared = parse_frontmatter(
            (PROMPTS / "shared/rules/agent-teams.md").read_text(encoding="utf-8")
        )

        assert _requirements_met(declared, "pi") is installed
