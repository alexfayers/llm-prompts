"""Tests for the batching module (pure batch-planning decisions)."""

from __future__ import annotations

import pytest

from llm_prompts.batching import (
    Batch,
    BatchPlan,
    Match,
    SelectionError,
    append_groups,
    batch_branch,
    batch_status,
    is_managed,
    match_commits,
    pending_plans,
    plan_batches,
    regression_warning,
    select_groups,
)
from llm_prompts.contribute import Commit, Group, Inventory, Pr


class TestBatchBranch:
    def test_joins_login_and_slug_under_contribute(self) -> None:
        assert batch_branch("alice", "fix-x") == "alice/contribute/fix-x"

    def test_managed_branch_is_managed(self) -> None:
        assert is_managed("alice/contribute/fix-x", "alice") is True

    def test_legacy_branch_is_not_managed(self) -> None:
        assert is_managed("alice/fix-x", "alice") is False


class TestMatchCommits:
    def test_owns_by_matching_patch_id(self) -> None:
        main_commit = Commit("m1", "fix: bug", (), patch_id="p1")
        branch_commit = Commit("b1", "fix: bug", (), patch_id="p1")
        match = match_commits((branch_commit,), (main_commit,))
        assert match.owned == {"b1": main_commit}
        assert match.amended == frozenset()
        assert match.unmatched == ()

    def test_owns_and_marks_amended_when_only_subject_matches_uniquely(self) -> None:
        main_commit = Commit("m1", "fix: bug", (), patch_id="p1")
        branch_commit = Commit("b1", "fix: bug", (), patch_id="p2")
        match = match_commits((branch_commit,), (main_commit,))
        assert match.owned == {"b1": main_commit}
        assert match.amended == frozenset({"b1"})

    def test_unmatched_when_subject_matches_multiple_main_commits(self) -> None:
        first = Commit("m1", "fix: bug", (), patch_id="p1")
        second = Commit("m2", "fix: bug", (), patch_id="p2")
        branch_commit = Commit("b1", "fix: bug", (), patch_id="p3")
        match = match_commits((branch_commit,), (first, second))
        assert match.owned == {}
        assert match.unmatched == (branch_commit,)


class TestPlanBatches:
    def _group(self, slug: str) -> Group:
        commit = Commit(f"m-{slug}", f"feat: {slug}", ())
        return Group((commit,), slug, f"user/{slug}", ())

    def _batch(
        self,
        branch: str,
        slug: str,
        owned_groups: tuple[Group, ...],
        amended: frozenset[str] = frozenset(),
        unmatched: tuple[Commit, ...] = (),
    ) -> Batch:
        commits = tuple(
            Commit(f"b-{g.slug}", g.commits[0].subject, ()) for g in owned_groups
        )
        owned = {c.sha: g.commits[0] for c, g in zip(commits, owned_groups)}
        match = Match(owned=owned, amended=amended, unmatched=unmatched)
        return Batch(branch, slug, None, commits, match)

    def _inventory(
        self, batches: tuple[Batch, ...] = (), past_slugs: frozenset[str] = frozenset()
    ) -> Inventory:
        return Inventory(
            batches=batches,
            done=frozenset(),
            merged_prs={},
            unmanaged={},
            legacy_orphans=(),
            past_slugs=past_slugs,
        )

    def test_new_batch_from_first_groups_slug_when_none_exist(self) -> None:
        groups = (self._group("a"), self._group("b"), self._group("c"))
        plans = plan_batches(groups, self._inventory(), "alice")

        assert len(plans) == 1
        assert plans[0].mode == "new"
        assert plans[0].slug == "a"
        assert plans[0].branch == batch_branch("alice", "a")
        assert plans[0].groups == groups

    def test_appends_to_newest_batch_until_cap_then_starts_new_batch(self) -> None:
        owned = tuple(self._group(f"o{n}") for n in range(4))
        batch = self._batch("alice/contribute/old", "old", owned)
        pending = (self._group("p1"), self._group("p2"))
        groups = owned + pending

        plans = plan_batches(groups, self._inventory((batch,)), "alice")

        assert len(plans) == 2
        assert plans[0].branch == "alice/contribute/old"
        assert plans[0].mode == "append"
        assert plans[0].groups == owned + (pending[0],)
        assert plans[1].mode == "new"
        assert plans[1].groups == (pending[1],)

    def test_starts_new_batch_when_newest_batch_is_full(self) -> None:
        owned = tuple(self._group(f"o{n}") for n in range(5))
        batch = self._batch("alice/contribute/old", "old", owned)
        pending = (self._group("p1"), self._group("p2"))
        groups = owned + pending

        plans = plan_batches(groups, self._inventory((batch,)), "alice")

        assert len(plans) == 1
        assert plans[0].mode == "new"
        assert plans[0].groups == pending

    def test_pending_groups_keep_main_order_when_split_across_new_batches(self) -> None:
        groups = tuple(self._group(f"g{n}") for n in range(7))

        plans = plan_batches(groups, self._inventory(), "alice")

        assert len(plans) == 2
        assert plans[0].groups + plans[1].groups == groups

    def test_amended_owned_commit_forces_rebuild_mode(self) -> None:
        owned = (self._group("a"), self._group("b"))
        batch = self._batch(
            "alice/contribute/old", "old", owned, amended=frozenset({"b-b"})
        )
        pending = (self._group("p1"),)
        groups = owned + pending

        plans = plan_batches(groups, self._inventory((batch,)), "alice")

        assert len(plans) == 1
        assert plans[0].branch == "alice/contribute/old"
        assert plans[0].mode == "rebuild"
        assert plans[0].groups == groups

    def test_owned_group_missing_one_of_its_commits_forces_rebuild_mode(self) -> None:
        first = Commit("m-a1", "feat: a1", ())
        second = Commit("m-a2", "feat: a2", ())
        group = Group((first, second), "a", "user/a", ())
        batch_commit = Commit("b-a1", "feat: a1", ())
        match = Match(owned={"b-a1": first}, amended=frozenset(), unmatched=())
        batch = Batch("alice/contribute/old", "old", None, (batch_commit,), match)

        plans = plan_batches((group,), self._inventory((batch,)), "alice")

        assert len(plans) == 1
        assert plans[0].branch == "alice/contribute/old"
        assert plans[0].mode == "rebuild"
        assert plans[0].groups == (group,)

    def test_batch_already_over_cap_does_not_append_via_negative_room(self) -> None:
        owned = tuple(self._group(f"o{n}") for n in range(6))
        batch = self._batch("alice/contribute/old", "old", owned)
        pending = (self._group("p1"), self._group("p2"))
        groups = owned + pending

        plans = plan_batches(groups, self._inventory((batch,)), "alice")

        assert len(plans) == 1
        assert plans[0].mode == "new"
        assert plans[0].groups == pending

    def test_current_batch_appends_new_groups_in_append_mode(self) -> None:
        owned = (self._group("a"), self._group("b"))
        batch = self._batch("alice/contribute/old", "old", owned)
        pending = (self._group("p1"),)
        groups = owned + pending

        plans = plan_batches(groups, self._inventory((batch,)), "alice")

        assert len(plans) == 1
        assert plans[0].mode == "append"
        assert plans[0].groups == groups

    def test_current_batch_with_no_pending_groups_returns_no_plan(self) -> None:
        owned = (self._group("a"), self._group("b"))
        batch = self._batch("alice/contribute/old", "old", owned)

        plans = plan_batches(owned, self._inventory((batch,)), "alice")

        assert plans == []

    def test_new_batch_slug_colliding_with_past_pr_gets_suffix(self) -> None:
        pending = (self._group("dup"),)
        inv = self._inventory(past_slugs=frozenset({"dup"}))

        plans = plan_batches(pending, inv, "alice")

        assert len(plans) == 1
        assert plans[0].mode == "new"
        assert plans[0].slug == "dup-2"
        assert plans[0].branch == batch_branch("alice", "dup-2")

    def test_pending_plans_drops_the_plan_of_a_regressed_batch(self) -> None:
        owned = (self._group("a"),)
        lost = Commit("b-lost", "feat: lost", ())
        batch = self._batch("alice/contribute/old", "old", owned, unmatched=(lost,))
        groups = owned + (self._group("p1"),)

        assert pending_plans(groups, self._inventory((batch,)), "alice") == []

    def test_pending_plans_excludes_problem_done_and_unmanaged_groups(self) -> None:
        problem = self._group("problem")._replace(problems=("mixed-scope",))
        done = self._group("done")
        unmanaged = self._group("unmanaged")
        clean = self._group("clean")
        inv = self._inventory()._replace(
            done=frozenset({"m-done"}),
            unmanaged={"m-unmanaged": Pr(9, "OPEN", "https://example.test/pull/9")},
        )

        plans = pending_plans((problem, done, unmanaged, clean), inv, "alice")

        assert len(plans) == 1
        assert plans[0].groups == (clean,)

    def test_pending_plans_plans_only_selected_groups(self) -> None:
        skipped, picked = self._group("skipped"), self._group("picked")

        plans = pending_plans(
            (skipped, picked), self._inventory(), "alice", frozenset({"m-picked"})
        )

        assert len(plans) == 1
        assert plans[0].groups == (picked,)

    def test_selection_appends_only_selected_groups_to_newest_batch(self) -> None:
        owned = (self._group("a"),)
        batch = self._batch("alice/contribute/old", "old", owned)
        skipped, picked = self._group("skipped"), self._group("picked")

        plans = plan_batches(
            owned + (skipped, picked),
            self._inventory((batch,)),
            "alice",
            frozenset({"m-picked"}),
        )

        assert len(plans) == 1
        assert plans[0].mode == "append"
        assert plans[0].groups == owned + (picked,)

    def test_selection_starts_new_batch_when_newest_batch_is_full(self) -> None:
        owned = tuple(self._group(f"o{n}") for n in range(5))
        batch = self._batch("alice/contribute/old", "old", owned)
        skipped, picked = self._group("skipped"), self._group("picked")

        plans = plan_batches(
            owned + (skipped, picked),
            self._inventory((batch,)),
            "alice",
            frozenset({"m-picked"}),
        )

        assert len(plans) == 1
        assert plans[0].mode == "new"
        assert plans[0].groups == (picked,)

    @pytest.mark.parametrize(
        ("amended", "selected", "expected_mode"),
        [
            (frozenset({"b-b"}), "m-p1", "new"),
            (frozenset({"b-b"}), "m-a", "rebuild"),
            (frozenset(), "m-a", None),
        ],
    )
    def test_selection_plans_existing_batch_only_when_it_owns_a_selected_commit(
        self, amended: frozenset[str], selected: str, expected_mode: str | None
    ) -> None:
        owned = (self._group("a"), self._group("b"))
        batch = self._batch("alice/contribute/old", "old", owned, amended=amended)
        pending = (self._group("p1"),)

        plans = plan_batches(
            owned + pending,
            self._inventory((batch,)),
            "alice",
            frozenset({selected}),
        )

        assert [plan.mode for plan in plans] == (
            [expected_mode] if expected_mode else []
        )
        if expected_mode == "rebuild":
            assert plans[0].groups == owned
        if expected_mode == "new":
            assert plans[0].groups == pending

    def test_selection_counts_unselected_owned_groups_toward_room(self) -> None:
        owned = tuple(self._group(f"o{n}") for n in range(4))
        batch = self._batch("alice/contribute/old", "old", owned)
        picked = (self._group("p1"), self._group("p2"))

        plans = plan_batches(
            owned + picked,
            self._inventory((batch,)),
            "alice",
            frozenset({"m-p1", "m-p2"}),
        )

        assert [plan.mode for plan in plans] == ["append", "new"]
        assert plans[0].groups == owned + (picked[0],)
        assert plans[1].groups == (picked[1],)


class TestSelectGroups:
    def _inventory(self, *commits: Commit) -> Inventory:
        return Inventory(
            batches=(),
            done=frozenset(),
            merged_prs={},
            unmanaged={},
            legacy_orphans=(),
            commits=commits,
        )

    def test_short_prefix_resolves_and_selects_the_whole_pair(self) -> None:
        first = Commit("abc123", "feat: a", ())
        second = Commit("def456", "feat: a compressed", ())
        other = Commit("999999", "feat: b", ())
        pair = Group((first, second), "a", "user/a", ())
        single = Group((other,), "b", "user/b", ())

        selected = select_groups(
            ["abc"], (pair, single), self._inventory(first, second, other)
        )

        assert selected == frozenset({"abc123", "def456"})

    def test_uppercase_prefix_matches_case_insensitively(self) -> None:
        commit = Commit("abc123", "feat: a", ())
        group = Group((commit,), "a", "user/a", ())

        selected = select_groups(["ABC"], (group,), self._inventory(commit))

        assert selected == frozenset({"abc123"})

    @pytest.mark.parametrize("value", ["", "  "])
    def test_blank_value_is_rejected(self, value: str) -> None:
        commit = Commit("abc123", "feat: a", ())
        group = Group((commit,), "a", "user/a", ())

        with pytest.raises(SelectionError, match="empty commit value"):
            select_groups([value], (group,), self._inventory(commit))

    def test_ambiguous_prefix_raises(self) -> None:
        first = Commit("abc123", "feat: a", ())
        second = Commit("abc456", "feat: b", ())
        groups = (
            Group((first,), "a", "user/a", ()),
            Group((second,), "b", "user/b", ()),
        )

        with pytest.raises(SelectionError) as error:
            select_groups(["abc"], groups, self._inventory(first, second))

        assert error.value.lines == ["abc: ambiguous (abc123 feat: a, abc456 feat: b)"]

    def test_unknown_sha_and_commit_outside_any_group_raise(self) -> None:
        code_only = Commit("abc123", "fix: code", ())

        with pytest.raises(SelectionError) as unknown:
            select_groups(["fff"], (), self._inventory(code_only))
        with pytest.raises(SelectionError) as outside:
            select_groups(["abc"], (), self._inventory(code_only))

        assert unknown.value.lines == [
            "fff: not a local commit ahead of the base branch"
        ]
        assert outside.value.lines == ["abc: touches no prompt sources"]

    def test_reports_every_bad_value_including_group_problems(self) -> None:
        bad = Commit("abc123", "feat: a", ())
        group = Group((bad,), "a", "user/a", ("mixed-scope", "no-tests"))

        with pytest.raises(SelectionError) as error:
            select_groups(["abc", "fff", "abc"], (group,), self._inventory(bad))

        assert error.value.lines == [
            "abc: mixed-scope, no-tests",
            "fff: not a local commit ahead of the base branch",
        ]

    def test_merged_unmanaged_and_current_commits_are_selectable(self) -> None:
        commits = tuple(Commit(f"{n}00000", f"feat: {n}", ()) for n in "123")
        groups = tuple(Group((c,), c.subject, f"user/{c.sha}", ()) for c in commits)
        inv = self._inventory(*commits)._replace(
            done=frozenset({"100000"}),
            unmanaged={"200000": Pr(9, "OPEN", "https://example.test/pull/9")},
        )

        selected = select_groups(["1", "2", "3"], groups, inv)

        assert selected == frozenset(c.sha for c in commits)


class TestAppendGroups:
    def test_excludes_groups_the_batch_already_owns(self) -> None:
        owned_commit = Commit("m-a", "feat: a", ())
        new_commit = Commit("m-b", "feat: b", ())
        owned_group = Group((owned_commit,), "a", "user/a", ())
        new_group = Group((new_commit,), "b", "user/b", ())
        batch_commit = Commit("b-a", "feat: a", ())
        match = Match(owned={"b-a": owned_commit}, amended=frozenset(), unmatched=())
        batch = Batch("alice/contribute/old", "old", None, (batch_commit,), match)
        plan = BatchPlan(
            branch="alice/contribute/old",
            slug="old",
            pr=None,
            groups=(owned_group, new_group),
            mode="append",
        )

        assert append_groups(plan, batch) == (new_group,)


class TestBatchStatus:
    def _batch(self, branch_commit: Commit, main_commits: tuple[Commit, ...]) -> Batch:
        match = match_commits((branch_commit,), main_commits)
        return Batch("tester/contribute/fix", "fix", None, (branch_commit,), match)

    def test_current_when_every_commit_owned_and_none_amended(self) -> None:
        main_commit = Commit("m1", "fix: bug", (), patch_id="p1")
        branch_commit = Commit("b1", "fix: bug", (), patch_id="p1")
        batch = self._batch(branch_commit, (main_commit,))
        assert batch_status(batch) == "current"

    def test_stale_when_an_owned_commit_is_amended(self) -> None:
        main_commit = Commit("m1", "fix: bug", (), patch_id="p1")
        branch_commit = Commit("b1", "fix: bug", (), patch_id="p2")
        batch = self._batch(branch_commit, (main_commit,))
        assert batch_status(batch) == "stale"

    def test_regressed_when_a_commit_matches_nothing_on_main(self) -> None:
        first = Commit("m1", "fix: bug", (), patch_id="p1")
        second = Commit("m2", "fix: bug", (), patch_id="p2")
        branch_commit = Commit("b1", "fix: bug", (), patch_id="p3")
        batch = self._batch(branch_commit, (first, second))
        assert batch_status(batch) == "regressed"

    def test_no_batch_regressed_returns_none(self) -> None:
        main_commit = Commit("m1", "fix: bug", (), patch_id="p1")
        branch_commit = Commit("b1", "fix: bug", (), patch_id="p1")
        batch = self._batch(branch_commit, (main_commit,))
        assert regression_warning((batch,)) is None

    def test_names_only_the_regressed_batchs_unmatched_commits(self) -> None:
        current_main = Commit("m1", "fix: bug", (), patch_id="p1")
        current_branch = Commit("b1", "fix: bug", (), patch_id="p1")
        current_match = match_commits((current_branch,), (current_main,))
        current_batch = Batch(
            "tester/contribute/fix", "fix", None, (current_branch,), current_match
        )

        other_main = Commit("m2", "feat: add x", (), patch_id="p2")
        regressed_commit = Commit("b2", "feat: add y", (), patch_id="p3")
        regressed_match = match_commits((regressed_commit,), (other_main,))
        regressed_batch = Batch(
            "tester/contribute/add-x",
            "add-x",
            None,
            (regressed_commit,),
            regressed_match,
        )

        warning = regression_warning((current_batch, regressed_batch))

        assert warning is not None
        assert "tester/contribute/add-x" in warning
        assert "tester/contribute/fix" not in warning
        assert "b2" in warning
        assert "b1" not in warning

    def test_command_cherry_picks_only_the_regressed_commits(self) -> None:
        owned_main = Commit("m1", "fix: bug", (), patch_id="p1")
        owned_branch = Commit("b1", "fix: bug", (), patch_id="p1")
        unmatched = Commit("b2", "feat: add y", (), patch_id="p3")
        match = match_commits((owned_branch, unmatched), (owned_main,))
        batch = Batch(
            "tester/contribute/mixed", "mixed", None, (owned_branch, unmatched), match
        )

        warning = regression_warning((batch,))

        assert warning is not None
        assert "git cherry-pick b2" in warning
        assert "b1" not in warning
