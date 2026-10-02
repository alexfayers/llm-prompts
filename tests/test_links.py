"""Tests for the persisted cross-repo link model."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_prompts.batching import SelectionError
from llm_prompts.contribute import Commit
from llm_prompts.links import (
    Annotation,
    Link,
    LinkCycleError,
    Note,
    Status,
    add_links,
    annotate,
    derive_links,
    describe,
    holds,
    load_links,
    order_targets,
    prune,
    resolve_commits,
    save_links,
)

ALPHA = ("alpha", "add alpha thing", "2026-01-01")
BETA = ("beta", "add beta thing", "2026-01-02")
GAMMA = ("gamma", "add gamma thing", "2026-01-03")


def _link(dependent: tuple[str, str, str], dependency: tuple[str, str, str]) -> Link:
    return Link(*dependent, *dependency)


def _commit(sha: str) -> Commit:
    return Commit(sha, f"subject {sha}", ())


class TestSaveLoad:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "links.json"
        links = (_link(BETA, ALPHA), _link(GAMMA, BETA))

        save_links(path, links)

        assert load_links(path) == links

    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert load_links(tmp_path / "links.json") == ()

    def test_corrupt_file_is_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "links.json"
        path.write_text("{not json", encoding="utf-8")

        assert load_links(path) == ()


class TestAddLinks:
    def test_union_preserves_order_without_duplicates(self) -> None:
        existing = (_link(BETA, ALPHA),)

        result = add_links(existing, (_link(GAMMA, BETA), _link(BETA, ALPHA)))

        assert result == (_link(BETA, ALPHA), _link(GAMMA, BETA))

    def test_cycle_is_rejected(self) -> None:
        existing = (_link(BETA, ALPHA), _link(GAMMA, BETA))

        with pytest.raises(LinkCycleError):
            add_links(existing, (_link(ALPHA, GAMMA),))


class TestPrune:
    def test_keeps_link_whose_dependent_is_pending(self) -> None:
        links = (_link(BETA, ALPHA),)

        result = prune(
            links,
            {"beta": {(BETA[1], BETA[2])}},
            {"alpha", "beta"},
        )

        assert result == links

    def test_drops_link_whose_dependent_is_no_longer_pending(self) -> None:
        result = prune((_link(BETA, ALPHA),), {"beta": set()}, {"alpha", "beta"})

        assert result == ()

    def test_drops_link_with_unconfigured_tool(self) -> None:
        pending = {"beta": {(BETA[1], BETA[2])}}

        assert prune((_link(BETA, ALPHA),), pending, {"beta"}) == ()
        assert prune((_link(BETA, ALPHA),), pending, {"alpha"}) == ()

    def test_keeps_link_whose_dependency_has_merged(self) -> None:
        links = (_link(BETA, ALPHA),)

        result = prune(
            links, {"beta": {(BETA[1], BETA[2])}, "alpha": set()}, {"alpha", "beta"}
        )

        assert result == links


class TestDeriveLinks:
    def test_later_repo_depends_on_earlier_repo(self) -> None:
        assert derive_links([ALPHA, BETA]) == (_link(BETA, ALPHA),)

    def test_same_repo_commits_get_no_link(self) -> None:
        other = ("alpha", "another alpha thing", "2026-01-04")

        assert derive_links([ALPHA, other]) == ()

    def test_three_repos_chain_every_later_on_every_earlier(self) -> None:
        assert derive_links([ALPHA, BETA, GAMMA]) == (
            _link(BETA, ALPHA),
            _link(GAMMA, ALPHA),
            _link(GAMMA, BETA),
        )

    def test_repo_order_follows_first_appearance(self) -> None:
        other = ("alpha", "another alpha thing", "2026-01-04")

        assert derive_links([ALPHA, BETA, other]) == (
            _link(BETA, ALPHA),
            _link(BETA, other),
        )


class TestAnnotate:
    def test_reports_dependency_status(self) -> None:
        status = {"alpha": {(ALPHA[1], ALPHA[2]): Status("needs PR", "u", "b")}}

        result = annotate((_link(BETA, ALPHA),), status)

        assert result == {
            BETA: (Annotation("alpha", ALPHA[1], "needs PR", "u", False),),
        }

    def test_absent_dependency_is_satisfied(self) -> None:
        result = annotate((_link(BETA, ALPHA),), {"alpha": {}})

        assert result == {BETA: (Annotation("alpha", ALPHA[1], "merged", None, True),)}

    def test_groups_dependencies_by_dependent(self) -> None:
        links = (_link(GAMMA, ALPHA), _link(GAMMA, BETA))

        result = annotate(links, {})

        assert [a.dependency_tool for a in result[GAMMA]] == ["alpha", "beta"]


class TestHolds:
    @pytest.mark.parametrize("stage", ["local only", "needs sync"])
    def test_unsynced_dependency_holds_dependent(self, stage: str) -> None:
        status = {"alpha": {(ALPHA[1], ALPHA[2]): Status(stage, None, None)}}

        assert holds((_link(BETA, ALPHA),), status) == frozenset({BETA})

    def test_dependency_with_pr_does_not_hold(self) -> None:
        status = {"alpha": {(ALPHA[1], ALPHA[2]): Status("needs PR", None, "b")}}

        assert holds((_link(BETA, ALPHA),), status) == frozenset()

    def test_satisfied_dependency_does_not_hold(self) -> None:
        assert holds((_link(BETA, ALPHA),), {"alpha": {}}) == frozenset()


class TestOrderTargets:
    def test_dependency_tool_comes_first(self) -> None:
        assert order_targets(["beta", "alpha"], (_link(BETA, ALPHA),)) == [
            "alpha",
            "beta",
        ]

    def test_unlinked_names_keep_given_order(self) -> None:
        assert order_targets(["gamma", "beta", "alpha"], ()) == [
            "gamma",
            "beta",
            "alpha",
        ]

    def test_links_to_unlisted_tools_are_ignored(self) -> None:
        assert order_targets(["beta", "gamma"], (_link(BETA, ALPHA),)) == [
            "beta",
            "gamma",
        ]

    def test_cycle_is_rejected(self) -> None:
        links = (_link(BETA, ALPHA), _link(ALPHA, BETA))

        with pytest.raises(LinkCycleError):
            order_targets(["alpha", "beta"], links)


class TestResolveCommits:
    def test_unique_prefix_resolves_to_its_tool(self) -> None:
        commits = {"alpha": [_commit("aaa111")], "beta": [_commit("bbb222")]}

        assert resolve_commits(["bbb", "aaa1"], commits) == {
            "beta": ["bbb"],
            "alpha": ["aaa1"],
        }

    def test_prefix_ambiguous_across_tools_is_an_error(self) -> None:
        commits = {"alpha": [_commit("abc111")], "beta": [_commit("abc222")]}

        with pytest.raises(SelectionError) as error:
            resolve_commits(["abc"], commits)

        assert error.value.lines == ["abc: ambiguous across alpha, beta"]

    def test_unknown_prefix_is_an_error(self) -> None:
        with pytest.raises(SelectionError) as error:
            resolve_commits(["zzz"], {"alpha": [_commit("aaa111")]})

        assert error.value.lines == ["zzz: not a local commit ahead of the base branch"]

    def test_prefix_ambiguous_within_one_tool_is_an_error(self) -> None:
        commits = {"alpha": [_commit("abc111"), _commit("abc222")]}

        with pytest.raises(SelectionError) as error:
            resolve_commits(["abc"], commits)

        assert error.value.lines[0].startswith("abc: ambiguous (abc111 ")

    def test_repeated_values_resolve_once_in_first_appearance_order(self) -> None:
        commits = {"alpha": [_commit("aaa111"), _commit("aaa222")]}

        assert resolve_commits(["aaa2", "aaa1", "aaa2"], commits) == {
            "alpha": ["aaa2", "aaa1"]
        }


class TestDescribe:
    def test_dependency_with_a_pr_shows_its_url(self) -> None:
        assert describe(
            [Annotation("alpha", "s", "waiting for review", "u", False)]
        ) == (Note("depends on u", False),)

    @pytest.mark.parametrize("stage", ["local only", "needs sync"])
    def test_unpushed_dependency_without_a_pr_says_so(self, stage: str) -> None:
        assert describe([Annotation("alpha", "s", stage, None, False)]) == (
            Note("depends on alpha: unpushed", True),
        )

    def test_pushed_dependency_without_a_pr_says_no_pr_yet(self) -> None:
        assert describe([Annotation("alpha", "s", "needs PR", None, False)]) == (
            Note("depends on alpha: no PR yet", True),
        )

    def test_satisfied_dependency_shows_nothing(self) -> None:
        assert describe([Annotation("alpha", "s", "merged", None, True)]) == ()

    def test_each_dependency_gets_its_own_note(self) -> None:
        annotations = [
            Annotation("alpha", "s", "approved", "u", False),
            Annotation("gamma", "s", "local only", None, False),
            Annotation("delta", "s", "merged", None, True),
        ]

        assert describe(annotations) == (
            Note("depends on u", False),
            Note("depends on gamma: unpushed", True),
        )


class TestDescribePrBody:
    _url = "https://github.com/o/r/pull/5"

    def _dependency(self, url: str | None = _url) -> Annotation:
        return Annotation("alpha", "s", "waiting for review", url, False)

    def test_url_present_in_the_body_is_not_flagged(self) -> None:
        assert describe([self._dependency()], f"Depends on {self._url}") == (
            Note(f"depends on {self._url}", False),
        )

    def test_url_missing_from_the_body_is_flagged(self) -> None:
        assert describe([self._dependency()], "no link") == (
            Note(f"depends on {self._url} - missing from PR", True),
        )

    def test_empty_body_is_flagged(self) -> None:
        assert describe([self._dependency()], "")[0].urgent

    def test_no_pr_body_is_never_flagged(self) -> None:
        assert describe([self._dependency()], None) == (
            Note(f"depends on {self._url}", False),
        )

    def test_dependency_without_a_url_is_never_flagged(self) -> None:
        annotation = Annotation("alpha", "s", "local only", None, False)

        assert describe([annotation], "") == (Note("depends on alpha: unpushed", True),)

    def test_only_the_missing_dependency_is_flagged(self) -> None:
        other = Annotation("gamma", "s", "approved", "https://x/pull/9", False)

        assert describe([self._dependency(), other], self._url) == (
            Note(f"depends on {self._url}", False),
            Note("depends on https://x/pull/9 - missing from PR", True),
        )


class TestResolveCommitsRewritten:
    def test_rewritten_value_names_the_current_commit(self) -> None:
        commits = {"alpha": [_commit("new1234567")]}
        rewritten = {"old": ("alpha", _commit("new1234567"))}

        with pytest.raises(SelectionError) as error:
            resolve_commits(["old"], commits, rewritten)

        assert error.value.lines == [
            "old: rewritten - alpha main now has new1234 subject new1234567"
        ]

    def test_value_absent_from_rewritten_keeps_the_plain_message(self) -> None:
        with pytest.raises(SelectionError) as error:
            resolve_commits(["old"], {"alpha": [_commit("aaa111")]}, {})

        assert error.value.lines == ["old: not a local commit ahead of the base branch"]

    def test_code_only_commit_resolves_like_any_other(self) -> None:
        commit = Commit("cod111", "fix: code change", ("src/app.py",))

        assert resolve_commits(["cod1"], {"alpha": [commit]}) == {"alpha": ["cod1"]}
