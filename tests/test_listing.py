"""Tests for the listing module (pure stage classification and rendering)."""

from __future__ import annotations

import pytest

from llm_prompts.colors import paint
from llm_prompts.contribute import Commit, Group, OpenPr, Pr
from llm_prompts.links import Note
from llm_prompts.listing import Entry, render, review_state


def _open_pr(*, draft: bool = False, decision: str = "") -> OpenPr:
    return OpenPr(
        Pr(5, "OPEN", "https://example.test/pull/5", draft), "b", decision, ()
    )


class TestReviewState:
    @pytest.mark.parametrize(
        ("pr", "expected"),
        [
            (_open_pr(draft=True, decision="APPROVED"), "draft"),
            (_open_pr(decision="CHANGES_REQUESTED"), "changes requested"),
            (_open_pr(decision="APPROVED"), "approved"),
            (_open_pr(decision="REVIEW_REQUIRED"), "needs review"),
            (_open_pr(), "needs review"),
            (_open_pr(decision="SOMETHING_NEW"), "needs review"),
            (None, "needs review"),
        ],
    )
    def test_maps_draft_and_review_decision_to_a_state(
        self, pr: OpenPr | None, expected: str
    ) -> None:
        assert review_state(pr) == expected


class TestRender:
    _foo = Commit("abcdef123", "feat: add foo", ())
    _bar = Commit("fedcba987", "docs: note bar", ())

    def _entries(self) -> list[Entry]:
        return [
            Entry(
                "local only",
                ("[new]",),
                "tester/contribute/add-foo",
                ((self._foo, ""),),
            ),
            Entry("needs PR", ("[manual PR]",), "", ((self._bar, "code"),)),
        ]

    def test_lays_out_stage_headings_entries_and_commit_lines(self) -> None:
        assert render(self._entries(), [], False) == [
            "  local only:",
            "    [new] tester/contribute/add-foo",
            "      abcdef1 feat: add foo",
            "  needs PR:",
            "    [manual PR]",
            "      fedcba9 docs: note bar [code]",
        ]

    def test_notes_go_on_their_own_line_under_the_commit(self) -> None:
        lines = render(
            self._entries(), [], False, {"abcdef123": (Note("depends on url", False),)}
        )

        assert lines[2:4] == [
            "      abcdef1 feat: add foo",
            "        -> depends on url",
        ]

    def test_notes_follow_the_commit_suffix(self) -> None:
        lines = render(
            self._entries(), [], False, {"fedcba987": (Note("depends on url", False),)}
        )

        assert lines[-2:] == [
            "      fedcba9 docs: note bar [code]",
            "        -> depends on url",
        ]

    def test_notes_for_other_commits_change_nothing(self) -> None:
        assert render(
            self._entries(), [], False, {"other": (Note("x", False),)}
        ) == render(self._entries(), [], False)

    def test_paints_notes_yellow_or_red_when_urgent_with_color_on(self) -> None:
        notes = {"abcdef123": (Note("a", False), Note("b", True))}

        out = "\n".join(render(self._entries(), [], True, notes))

        assert f"        {paint('-> a', 'yellow')}" in out
        assert f"        {paint('-> b', 'red')}" in out

    def test_notes_carry_no_escape_codes_when_color_is_off(self) -> None:
        notes = {"abcdef123": (Note("b", True),)}

        assert "\033" not in "\n".join(render(self._entries(), [], False, notes))

    def test_prints_nothing_pending_when_there_is_nothing_to_show(self) -> None:
        assert render([], [], False) == ["  no pending changes"]

    def test_lists_problem_commits_after_the_stages(self) -> None:
        group = Group((self._foo,), "add-foo", "tester/add-foo", ("non-conventional",))

        lines = render([], [group], False)

        assert lines == [
            "  problems:",
            "    abcdef1 feat: add foo [non-conventional]",
        ]

    def test_paints_headings_and_the_manual_pr_tag_when_color_is_on(self) -> None:
        out = "\n".join(render(self._entries(), [], True))

        assert paint("local only:", "cyan") in out
        assert paint("needs PR:", "yellow") in out
        assert paint("[manual PR]", "yellow") in out

    def test_emits_no_escape_codes_when_color_is_off(self) -> None:
        assert "\033" not in "\n".join(render(self._entries(), [], False))
