"""Tests for syncing a diverged local main onto its upstream."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeSubprocess

from llm_prompts.main_sync import (
    PRE_SYNC_REF,
    SyncResult,
    _Bail,
    _Conflict,
    _merge_tree,
    sync_diverged,
)

REPO = Path("/clone")
GIT_MARKERS = (
    "rebase-merge",
    "rebase-apply",
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
)
SAVE_POINT = f"update-ref --create-reflog -m llm-prompts: pre-sync {PRE_SYNC_REF} HEAD"


def _in_progress(repo: Path, fake: FakeSubprocess, marker: str) -> None:
    """Make git report the paths of in-progress markers, and create one of them."""
    (repo / ".git" / marker).mkdir(parents=True)
    fake.on(
        "rev-parse",
        "--git-path",
        stdout="".join(f".git/{name}\n" for name in GIT_MARKERS),
    )


def _head_is_saved(fake: FakeSubprocess) -> None:
    """Route HEAD and the pre-sync ref to the same commit."""
    fake.on("rev-parse", "HEAD", stdout="c0\nc0\n")


class TestIdenticalTrees:
    def test_soft_reset_onto_upstream_without_rebase(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=0)

        assert sync_diverged(REPO) == SyncResult("reset")

        assert fake_subprocess.matching("reset", "--soft", "@{u}")
        assert fake_subprocess.matching("rebase") == []

    def test_pre_sync_ref_is_saved_before_the_soft_reset(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=0)

        sync_diverged(REPO)

        verbs = fake_subprocess.verbs
        assert verbs.index(SAVE_POINT) < verbs.index("reset --soft @{u}")

    def test_failed_soft_reset_is_reported_without_rebasing(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=0)
        fake_subprocess.on("reset", "--soft", returncode=1, stderr="fatal: lock\n")
        _head_is_saved(fake_subprocess)

        assert sync_diverged(REPO) == SyncResult(
            "failed", detail="fatal: lock; nothing changed"
        )

        assert fake_subprocess.matching("rebase") == []


class TestOperationInProgress:
    @pytest.mark.parametrize(
        ("marker", "operation"),
        [
            ("rebase-merge", "rebase"),
            ("rebase-apply", "rebase"),
            ("MERGE_HEAD", "merge"),
            ("CHERRY_PICK_HEAD", "cherry-pick"),
            ("REVERT_HEAD", "revert"),
        ],
    )
    def test_sync_touches_nothing(
        self,
        tmp_path: Path,
        fake_subprocess: FakeSubprocess,
        marker: str,
        operation: str,
    ) -> None:
        _in_progress(tmp_path, fake_subprocess, marker)
        fake_subprocess.on("rev-parse", "--verify", returncode=1)

        assert sync_diverged(tmp_path) == SyncResult(
            "failed", detail=f"a {operation} is in progress; finish or abort it first"
        )

        for mutation in ("update-ref", "reset", "rebase"):
            assert fake_subprocess.matching(mutation) == []

    def test_names_the_saved_ref_when_it_exists(
        self, tmp_path: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        _in_progress(tmp_path, fake_subprocess, "rebase-merge")

        assert sync_diverged(tmp_path) == SyncResult(
            "failed",
            detail="a rebase is in progress; finish or abort it first;"
            f" the state before the last sync is saved as {PRE_SYNC_REF}",
        )


class TestRebase:
    def test_clean_rebase_onto_upstream(self, fake_subprocess: FakeSubprocess) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=1)
        fake_subprocess.on("rebase", "--quiet", returncode=0)

        assert sync_diverged(REPO) == SyncResult("rebased")

        assert fake_subprocess.matching("rebase", "--abort") == []

    def test_pre_sync_ref_is_saved_before_the_rebase(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=1)

        sync_diverged(REPO)

        verbs = fake_subprocess.verbs
        assert verbs.index(SAVE_POINT) < verbs.index("rebase --quiet @{u}")

    @pytest.mark.parametrize("diff_exit", [0, 1])
    def test_failed_save_mutates_nothing(
        self, fake_subprocess: FakeSubprocess, diff_exit: int
    ) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=diff_exit)
        fake_subprocess.on("update-ref", returncode=1, stderr="fatal: cannot lock\n")

        assert sync_diverged(REPO) == SyncResult("failed", detail="fatal: cannot lock")

        assert fake_subprocess.matching("reset") == []
        assert fake_subprocess.matching("rebase") == []

    def test_failed_abort_reports_how_to_recover(
        self, tmp_path: Path, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=1)
        fake_subprocess.on(
            "rebase",
            "--quiet",
            returncode=1,
            side_effect=lambda argv, kwargs: _in_progress(
                tmp_path, fake_subprocess, "rebase-merge"
            ),
        )
        fake_subprocess.on("rebase", "--abort", returncode=1, stderr="fatal: lock\n")
        fake_subprocess.on("rev-parse", "HEAD", stdout="c1\nc0\n")

        assert sync_diverged(tmp_path) == SyncResult(
            "failed",
            detail=f"fatal: lock; recover with: cd {tmp_path} && git rebase --abort"
            f" && git reset --keep {PRE_SYNC_REF}",
        )

        assert fake_subprocess.matching("ls-remote") == []

    def test_timed_out_rebase_is_aborted_and_reported(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=1)
        fake_subprocess.on(
            "rebase",
            "--quiet",
            side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30),
        )
        fake_subprocess.on("rev-parse", "--abbrev-ref", returncode=1)
        _head_is_saved(fake_subprocess)

        assert sync_diverged(REPO) == SyncResult(
            "failed", detail="git rebase timed out; nothing changed"
        )

        assert fake_subprocess.matching("rebase", "--abort")
        assert fake_subprocess.matching("ls-remote") == []


LOCAL_LOG = (
    "l1\tp0\t100\tlocal work\nl2\tl1\t150\tpatch equal\nl3\tl2\t200\tpr commit\n"
)
LOCAL_AUTHOR = (
    "Jo Dev\x00jo@example.com\x002024-01-02T03:04:05+00:00\x00local work\n\nbody\n\n"
)


def _route_divergence(fake: FakeSubprocess) -> None:
    """Route a diverged repo: l1 is WIP, l2 is in PR head h1 by patch, l3 repeats PR commit p3."""
    fake.on("diff", "--quiet", returncode=1)
    fake.on("rebase", "--quiet", returncode=1, stderr="conflict")
    fake.on("rev-parse", "--abbrev-ref", stdout="origin/main\n")
    fake.on("merge-base", stdout="base\n")
    fake.on("log", "--reverse", stdout=LOCAL_LOG)
    fake.on("cherry", "HEAD", stdout="+ u1\n")
    fake.on("log", "--no-walk=unsorted", stdout="u1\tfeat: pr commit (#7)\n")
    fake.on("ls-remote", stdout="h1\trefs/pull/7/head\n")
    fake.on("cat-file", stdout="h1 missing\n")
    fake.on("rev-parse", "u1^{tree}", stdout="tree-u1\ntree-u1\n")
    fake.on("log", "--no-merges", stdout="p3\t200\tpr commit\n")
    fake.on("cherry", "@{u}", stdout="+ l1\n+ l2\n+ l3\n")
    fake.on("cherry", "h1", stdout="+ l1\n- l2\n+ l3\n")
    fake.on("rev-parse", "@{u}", stdout="tip0\n")
    fake.on("merge-tree", stdout="tree-l1\n")
    fake.on(
        "merge-tree",
        "--write-tree",
        "--name-only",
        "--merge-base=p3^",
        stdout="tree-l3\n",
    )
    fake.on("rev-parse", "l3^{tree}", stdout="tree-l3\n")
    fake.on("log", "-1", "--format=%an%x00%ae%x00%aI%x00%B", stdout=LOCAL_AUTHOR)
    fake.on("commit-tree", stdout=["tip1\n", "tip2\n"])
    _head_is_saved(fake)


def _commit_tree_calls(fake: FakeSubprocess) -> list[tuple[list[str], dict[str, Any]]]:
    return [call for call in fake.calls if "commit-tree" in call[0]]


class TestSquashSync:
    def test_commits_in_a_merged_pull_request_are_dropped_and_the_rest_replayed(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=1)

        (replay,) = _commit_tree_calls(fake_subprocess)
        assert replay[0][-5:] == ["tree-l1", "-p", "tip0", "-F", "-"]
        assert replay[1]["input"] == "local work\n\nbody\n"
        assert replay[1]["env"]["GIT_AUTHOR_NAME"] == "Jo Dev"
        assert replay[1]["env"]["GIT_AUTHOR_EMAIL"] == "jo@example.com"
        assert replay[1]["env"]["GIT_AUTHOR_DATE"] == "2024-01-02T03:04:05+00:00"
        assert fake_subprocess.commands[-1][-3:] == ["reset", "--keep", "tip1"]
        assert fake_subprocess.matching("cherry", "h1")
        assert fake_subprocess.matching(
            "merge-tree", "--write-tree", "--name-only", "--merge-base=p3^"
        )[0][-2:] == ["l3^", "p3"]

    def test_pull_request_commit_applying_differently_is_replayed(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "merge-tree",
            "--write-tree",
            "--name-only",
            "--merge-base=p3^",
            stdout="tree-other\n",
        )

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=2)

    def test_pull_request_commit_conflicting_with_local_is_replayed(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "merge-tree",
            "--write-tree",
            "--name-only",
            "--merge-base=p3^",
            returncode=1,
            stdout="tree-l3\nfile.txt\n",
        )

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=2)

    def test_head_with_a_different_tree_drops_nothing(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("rev-parse", "u1^{tree}", stdout="tree-u1\ntree-other\n")

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=3)

        assert fake_subprocess.matching("cherry", "h1") == []

    def test_upstream_subject_without_a_pull_request_number_drops_nothing(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("log", "--no-walk=unsorted", stdout="u1\tfeat: pr commit\n")

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=3)

        assert fake_subprocess.matching("ls-remote") == []

    def test_pull_request_without_a_head_drops_nothing(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("ls-remote", stdout="")
        fake_subprocess.on("cat-file", stdout="")

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=3)

    def test_fixup_group_equal_to_a_pull_request_commit_is_dropped(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_fixup_group(fake_subprocess)

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=1)

        group, replay = _commit_tree_calls(fake_subprocess)
        assert group[0][-5:] == ["tree-group", "-p", "l3^", "-F", "-"]
        assert group[1]["env"]["GIT_AUTHOR_DATE"] == "2024-01-02T03:04:05+00:00"
        assert fake_subprocess.matching("merge-tree", "--write-tree", "--name-only")[0][
            -3:
        ] == ["--merge-base=l4^", "l3", "l4"]
        assert replay[0][-5:] == ["tree-l1", "-p", "tip0", "-F", "-"]

    def test_fixup_group_differing_from_the_pull_request_commit_is_replayed(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_fixup_group(fake_subprocess)
        fake_subprocess.on("rev-parse", "g1^{tree}", stdout="tree-other\n")
        fake_subprocess.on("commit-tree", stdout=["g1\n", "tip1\n", "tip2\n"])

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=2)

        assert fake_subprocess.matching("merge-tree", "--write-tree", "--name-only")[
            -1
        ][-3:] == ["--merge-base=g1^", "tip1", "g1"]
        assert fake_subprocess.commands[-1][-3:] == ["reset", "--keep", "tip2"]

    def test_fixup_whose_target_is_dropped_by_patch_is_replayed(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_fixup_group(fake_subprocess)
        fake_subprocess.on("cherry", "h1", stdout="+ l1\n- l3\n+ l4\n")
        fake_subprocess.on(
            "merge-tree",
            "--write-tree",
            "--name-only",
            "--merge-base=l4^",
            stdout="tree-l4\n",
        )
        fake_subprocess.on("commit-tree", stdout=["tip1\n", "tip2\n"])

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=2)

        assert [call[0][-5] for call in _commit_tree_calls(fake_subprocess)] == [
            "tree-l1",
            "tree-l4",
        ]
        assert fake_subprocess.matching(
            "merge-tree", "--write-tree", "--name-only", "--merge-base=l4^"
        )[0][-2:] == ["tip1", "l4"]

    def test_fixup_conflicting_with_its_target_is_replayed_on_its_own(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_fixup_group(fake_subprocess)
        fake_subprocess.on(
            "merge-tree",
            "--write-tree",
            "--name-only",
            "--merge-base=l4^",
            returncode=[1, 0],
            stdout=["tree-group\nf.txt\n", "tree-l4\n"],
        )
        fake_subprocess.on("rev-parse", "l3^{tree}", stdout="tree-l3\n")

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=2)

        assert [call[0][-5] for call in _commit_tree_calls(fake_subprocess)] == [
            "tree-l1",
            "tree-l4",
        ]

    def test_failed_keep_reset_is_reported_without_a_soft_reset(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("reset", "--keep", returncode=1, stderr="error: overwrite\n")

        assert sync_diverged(REPO) == SyncResult(
            "failed", detail="error: overwrite; nothing changed"
        )

        assert fake_subprocess.matching("reset", "--soft") == []


def _route_fixup_group(fake: FakeSubprocess) -> None:
    """Route l3 "pr commit" plus its fixup l4 as one group g1, PR commit p3's equal."""
    _route_divergence(fake)
    fake.on(
        "log",
        "--reverse",
        stdout="l1\tp0\t100\tlocal work\nl3\tl1\t200\tpr commit\n"
        "l4\tl3\t300\tfixup! pr commit\n",
    )
    fake.on("cherry", "@{u}", stdout="+ l1\n+ l3\n+ l4\n")
    fake.on("cherry", "h1", stdout="+ l1\n+ l3\n+ l4\n")
    fake.on(
        "merge-tree",
        "--write-tree",
        "--name-only",
        "--merge-base=l4^",
        stdout="tree-group\n",
    )
    fake.on("commit-tree", stdout=["g1\n", "tip1\n"])
    fake.on("rev-parse", "g1^{tree}", stdout="tree-l3\n")


def _assert_untouched_bail(fake: FakeSubprocess, reason: str) -> None:
    assert sync_diverged(REPO) == SyncResult(
        "failed", detail=f"squash sync stopped: {reason}; nothing changed"
    )
    assert fake.matching("reset") == []


class TestSquashSyncBails:
    def test_replay_conflict_names_the_commit_and_paths(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "merge-tree", returncode=1, stdout="tree\na.txt\nb.txt\n\nAuto-merging\n"
        )

        _assert_untouched_bail(
            fake_subprocess,
            "local commit l1 (local work) conflicts with upstream in a.txt, b.txt",
        )
        assert _commit_tree_calls(fake_subprocess) == []

    def test_bail_after_head_moved_reports_how_to_recover(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("log", "--reverse", stdout="l1\tp0 p1\t100\tmerge\n")
        fake_subprocess.on("rev-parse", "HEAD", stdout="c1\nc0\n")

        assert sync_diverged(REPO) == SyncResult(
            "failed",
            detail="squash sync stopped: local merge commit l1; recover with:"
            f" cd {REPO} && git reset --keep {PRE_SYNC_REF}",
        )

    def test_pull_request_commits_sharing_an_identity(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "log", "--no-merges", stdout="p2\t200\tpr commit\np3\t200\tpr commit\n"
        )

        _assert_untouched_bail(
            fake_subprocess,
            "two pull request commits share author time and subject: pr commit",
        )

    def test_timed_out_git_call(self, fake_subprocess: FakeSubprocess) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "ls-remote", side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30)
        )

        _assert_untouched_bail(fake_subprocess, "git ls-remote timed out")

    def test_local_merge_commit(self, fake_subprocess: FakeSubprocess) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("log", "--reverse", stdout="l1\tp0 p1\t100\tmerge\n")

        _assert_untouched_bail(fake_subprocess, "local merge commit l1")


class TestMergeTree:
    def test_clean_merge_returns_the_tree(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("merge-tree", stdout="tree-x\n")

        assert _merge_tree(REPO, "base", "ours", "theirs") == "tree-x"

        assert fake_subprocess.commands[-1][-6:] == [
            "merge-tree",
            "--write-tree",
            "--name-only",
            "--merge-base=base",
            "ours",
            "theirs",
        ]

    def test_conflict_carries_the_conflicted_paths(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on(
            "merge-tree",
            returncode=1,
            stdout="tree-x\na.txt\nb.txt\n\nAuto-merging a.txt\n",
        )

        with pytest.raises(_Conflict) as conflict:
            _merge_tree(REPO, "base", "ours", "theirs")

        assert conflict.value.paths == ["a.txt", "b.txt"]

    def test_any_other_failure_bails_with_stderr(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("merge-tree", returncode=2, stderr="fatal: bad object\n")

        with pytest.raises(_Bail, match="fatal: bad object") as bail:
            _merge_tree(REPO, "base", "ours", "theirs")

        assert not isinstance(bail.value, _Conflict)


class TestPullRequestHeads:
    def test_only_the_named_pull_request_is_listed(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)

        sync_diverged(REPO)

        assert fake_subprocess.matching("ls-remote")[0][-3:] == [
            "ls-remote",
            "origin",
            "refs/pull/7/head",
        ]

    def test_only_heads_missing_locally_are_fetched(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "log",
            "--no-walk=unsorted",
            stdout="u1\tfeat: a (#7)\nu2\tfeat: b (#8)\n",
        )
        fake_subprocess.on(
            "ls-remote", stdout="h1\trefs/pull/7/head\nh2\trefs/pull/8/head\n"
        )
        fake_subprocess.on("cat-file", stdout="h1 commit 200\nh2 missing\n")
        fake_subprocess.on(
            "rev-parse", "u1^{tree}", stdout="tree-u1\ntree-u1\ntree-u2\ntree-h2\n"
        )

        sync_diverged(REPO)

        assert fake_subprocess.matching("fetch")[0][-4:] == [
            "fetch",
            "--quiet",
            "origin",
            "refs/pull/8/head",
        ]

    def test_no_head_is_fetched_when_all_are_present(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("cat-file", stdout="h1 commit 200\n")

        sync_diverged(REPO)

        assert fake_subprocess.matching("fetch") == []


class TestGitOnly:
    def test_no_command_uses_gh(self, fake_subprocess: FakeSubprocess) -> None:
        _route_divergence(fake_subprocess)

        sync_diverged(REPO)

        assert {argv[0] for argv in fake_subprocess.commands} == {"git"}
