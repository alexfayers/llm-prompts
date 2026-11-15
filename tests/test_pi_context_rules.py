"""Rule and skill text under the pi-context runtime."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from llm_prompts.install import _requirements_met
from llm_prompts.render_template import (
    load_vars,
    parse_frontmatter,
    substitute_variables,
)

PROMPTS = Path(__file__).parent.parent / "src/llm_prompts/prompts"


@pytest.fixture
def set_runtime(isolated_config_dir: Path) -> Callable[[str], None]:
    """Return a function that writes the `[pi] runtime` setting."""

    def write(runtime: str) -> None:
        (isolated_config_dir / "config.toml").write_text(
            f'[pi]\nruntime = "{runtime}"\n', encoding="utf-8"
        )

    return write


def render_for_pi(source: str) -> str:
    """Render a prompt source for pi under the configured runtime."""
    variables = {**load_vars(PROMPTS / "pi/vars.json"), "AGENT": "pi"}
    body, _ = parse_frontmatter((PROMPTS / source).read_text(encoding="utf-8"))
    return substitute_variables(body, variables)


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


class TestDelegationRule:
    HERDSMAN_ONLY = ("coordinator", "subagent_type", "pi -p", "``")

    def test_pi_context_names_only_fork_roles(
        self, set_runtime: Callable[[str], None]
    ) -> None:
        set_runtime("pi-context")

        rendered = render_for_pi("shared/rules/delegation.md")

        assert "A `reader` (default) only reads." in rendered
        assert not [text for text in self.HERDSMAN_ONLY if text in rendered]
        assert "starts with an empty session" in rendered

    def test_herdsman_keeps_the_agent_tiers(
        self, set_runtime: Callable[[str], None]
    ) -> None:
        set_runtime("herdsman")

        rendered = render_for_pi("shared/rules/delegation.md")

        assert "`coordinator` (breakdown, spawns all of these" in rendered


class TestHerdrRule:
    @pytest.mark.parametrize(
        ("runtime", "kept"), [("herdsman", True), ("pi-context", False)]
    )
    def test_herdsman_sections_follow_the_runtime(
        self, set_runtime: Callable[[str], None], runtime: str, kept: bool
    ) -> None:
        set_runtime(runtime)

        rendered = render_for_pi("shared/rules/herdr.md")

        assert ("pi-herdsman" in rendered) is kept
        assert ("## Feature worktrees" in rendered) is kept


class TestPlanningRule:
    @pytest.mark.parametrize(
        ("runtime", "wording"),
        [("herdsman", "to subagents"), ("pi-context", "to `fork` readers")],
    )
    def test_bulk_work_goes_to_the_runtimes_delegates(
        self, set_runtime: Callable[[str], None], runtime: str, wording: str
    ) -> None:
        set_runtime(runtime)

        assert wording in render_for_pi("shared/rules/planning.md")


class TestAntiYapRule:
    @pytest.mark.parametrize(
        ("runtime", "wording"),
        [
            ("herdsman", "a file holding the full report"),
            ("pi-context", "The `fork` tool shows main only that line"),
        ],
    )
    def test_outcome_line_follows_how_the_runtime_returns_the_reply(
        self, set_runtime: Callable[[str], None], runtime: str, wording: str
    ) -> None:
        set_runtime(runtime)

        assert wording in render_for_pi("shared/rules/anti-yap.md")
