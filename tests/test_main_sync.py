"""Tests for syncing a diverged local main onto its upstream."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from conftest import FakeSubprocess

from llm_prompts.main_sync import LocalCommit, SyncResult, split_local, sync_diverged

REPO = Path("/clone")


class TestIdenticalTrees:
    def test_soft_reset_onto_upstream_without_rebase(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=0)

        assert sync_diverged(REPO) == SyncResult("reset")

        assert fake_subprocess.matching("reset", "--soft", "@{u}")
        assert fake_subprocess.matching("rebase") == []

    def test_failed_soft_reset_is_reported_without_rebasing(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=0)
        fake_subprocess.on("reset", "--soft", returncode=1, stderr="fatal: lock\n")

        assert sync_diverged(REPO) == SyncResult("failed", detail="fatal: lock")

        assert fake_subprocess.matching("rebase") == []


class TestRebase:
    def test_clean_rebase_onto_upstream(self, fake_subprocess: FakeSubprocess) -> None:
        fake_subprocess.on("diff", "--quiet", returncode=1)
        fake_subprocess.on("rebase", "--quiet", returncode=0)

        assert sync_diverged(REPO) == SyncResult("rebased")

        assert fake_subprocess.matching("rebase", "--abort") == []

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

        assert sync_diverged(REPO) == SyncResult(
            "failed", detail="git rebase timed out"
        )

        assert fake_subprocess.matching("rebase", "--abort")
        assert fake_subprocess.matching("ls-remote") == []


LOCAL_LOG = "l1\tp0\t100\tlocal work\nl2\tl1\t200\tpr commit\n"
LOCAL_AUTHOR = (
    "Jo Dev\x00jo@example.com\x002024-01-02T03:04:05+00:00\x00local work\n\nbody\n\n"
)
REVISED_MESSAGE = "pr commit\n\nrevised body\n\n"


def _route_divergence(fake: FakeSubprocess) -> None:
    """Route a diverged repo: l1 is unrelated, l2 revises PR head h1, u1 is its squash."""
    fake.on("diff", "--quiet", returncode=1)
    fake.on("rebase", "--quiet", returncode=1, stderr="conflict")
    fake.on("rev-parse", "--abbrev-ref", stdout="origin/main\n")
    fake.on("merge-base", stdout="base\n")
    fake.on("log", "--reverse", stdout=LOCAL_LOG)
    fake.on("cherry", "HEAD", stdout="+ u1\n")
    fake.on("ls-remote", stdout="h1\trefs/pull/7/head\n")
    fake.on("cat-file", stdout="h1 missing\n")
    fake.on("rev-parse", "u1^{tree}", stdout="tree-u1\ntree-u1\n")
    fake.on("log", "--no-merges", stdout="p2\t200\tpr commit\n")
    fake.on("cherry", "@{u}", stdout="")
    fake.on("cherry", "h1", stdout="+ l1\n+ l2\n")
    fake.on("rev-parse", "@{u}", stdout="tip0\n")
    fake.on("merge-tree", stdout="tree-l1\n")
    fake.on("log", "-1", "--format=%an%x00%ae%x00%aI%x00%B", stdout=LOCAL_AUTHOR)
    fake.on("log", "-1", "--format=%B", stdout=REVISED_MESSAGE)
    fake.on("commit-tree", stdout=["tip1\n", "tip2\n"])
    fake.on("rev-parse", "tip1^{tree}", stdout="tree-tip1\n")
    fake.on("merge-tree", "--write-tree", "--merge-base=base", stdout="tree-merged\n")
    fake.on("log", "--walk-reflogs", stdout="l2\t200\tpr commit\nl0\t200\tpr commit\n")
    fake.on("show", stdout="diff\n")
    fake.on("patch-id", stdout="pidP p2\npidL l2\npidP l0\n")
    fake.on("merge-tree", "--write-tree", "--merge-base=l0^", stdout="tree-base\n")
    fake.on(
        "merge-tree", "--write-tree", "--merge-base=tree-base", stdout="tree-fold\n"
    )


def _commit_tree_calls(fake: FakeSubprocess) -> list[tuple[list[str], dict[str, Any]]]:
    return [call for call in fake.calls if "commit-tree" in call[0]]


class TestSquashSync:
    def test_unrelated_commit_replayed_and_revised_commit_folded(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)

        assert sync_diverged(REPO) == SyncResult(
            "squash-synced", replayed=1, folded=("pr commit",)
        )

        replay, fold = _commit_tree_calls(fake_subprocess)
        assert replay[0][-5:] == ["tree-l1", "-p", "tip0", "-F", "-"]
        assert replay[1]["input"] == "local work\n\nbody\n"
        assert replay[1]["env"]["GIT_AUTHOR_NAME"] == "Jo Dev"
        assert replay[1]["env"]["GIT_AUTHOR_EMAIL"] == "jo@example.com"
        assert replay[1]["env"]["GIT_AUTHOR_DATE"] == "2024-01-02T03:04:05+00:00"
        assert fold[0][-5:] == ["tree-fold", "-p", "tip1", "-F", "-"]
        assert fold[1]["input"] == "pr commit\n\nrevised body\n"
        assert fold[1]["env"] is None
        assert fake_subprocess.commands[-1][-3:] == ["reset", "--keep", "tip2"]
        assert not any(
            "HEAD^{tree}" in call[0] for call in _commit_tree_calls(fake_subprocess)
        )
        base_merge, fold_merge = fake_subprocess.matching(
            "merge-tree", "--write-tree", "--merge-base=l0^"
        ) + fake_subprocess.matching(
            "merge-tree", "--write-tree", "--merge-base=tree-base"
        )
        assert base_merge[-3:] == ["--merge-base=l0^", "l2^", "l0"]
        assert fold_merge[-3:] == ["--merge-base=tree-base", "tree-tip1", "l2"]

    def test_folded_messages_joined_by_single_blank_line(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "log",
            "--reverse",
            stdout="l1\tp0\t100\tlocal work\nl2\tl1\t200\tpr commit\nl3\tl2\t300\tpr fix\n",
        )
        fake_subprocess.on("cherry", "h1", stdout="+ l1\n+ l2\n+ l3\n")
        fake_subprocess.on(
            "log", "--no-merges", stdout="p2\t200\tpr commit\np3\t300\tpr fix\n"
        )
        fake_subprocess.on(
            "log",
            "--walk-reflogs",
            stdout="l3\t300\tpr fix\nl2\t200\tpr commit\nl0\t200\tpr commit\nl9\t300\tpr fix\n",
        )
        fake_subprocess.on(
            "patch-id",
            stdout="pidP p2\npidL l2\npidP l0\npidQ p3\npidM l3\npidQ l9\n",
        )
        fake_subprocess.on(
            "merge-tree", "--write-tree", "--merge-base=l9^", stdout="tree-base2\n"
        )
        fake_subprocess.on(
            "log", "-1", "--format=%B", stdout=[REVISED_MESSAGE, "pr fix\n\n"]
        )

        sync_diverged(REPO)

        _, fold = _commit_tree_calls(fake_subprocess)
        assert fold[1]["input"] == "pr commit\n\nrevised body\n\npr fix\n"

    def test_fold_matching_the_tip_makes_no_folded_commit(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "merge-tree", "--write-tree", "--merge-base=tree-base", stdout="tree-tip1\n"
        )

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=1)

        assert len(_commit_tree_calls(fake_subprocess)) == 1
        assert fake_subprocess.commands[-1][-3:] == ["reset", "--keep", "tip1"]

    def test_pull_request_with_no_local_commits_is_skipped(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("log", "--no-merges", stdout="p9\t999\tunknown commit\n")
        fake_subprocess.on("rev-parse", "tip2^{tree}", stdout="tree-tip2\n")
        fake_subprocess.on(
            "merge-tree", "--write-tree", "--merge-base=base", stdout="tree-tip2\n"
        )

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=2)

        assert fake_subprocess.matching("cherry", "h1") == []
        assert fake_subprocess.commands[-1][-3:] == ["reset", "--keep", "tip2"]

    def test_local_changes_already_on_tip_skip_the_fold(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "merge-tree", "--write-tree", "--merge-base=base", stdout="tree-tip1\n"
        )

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=1)

        assert fake_subprocess.matching("patch-id") == []
        assert fake_subprocess.commands[-1][-3:] == ["reset", "--keep", "tip1"]

    def test_conflicting_merge_of_local_onto_tip_still_folds(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "merge-tree", "--write-tree", "--merge-base=base", returncode=1
        )

        assert sync_diverged(REPO) == SyncResult(
            "squash-synced", replayed=1, folded=("pr commit",)
        )

    def test_failed_keep_reset_is_reported_without_a_soft_reset(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("reset", "--keep", returncode=1, stderr="error: overwrite\n")

        assert sync_diverged(REPO) == SyncResult("failed", detail="error: overwrite")

        assert fake_subprocess.matching("reset", "--soft") == []

    def test_matching_trees_make_no_folded_commit(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("log", "--reverse", stdout="l1\tp0\t100\tlocal work\n")
        fake_subprocess.on("cherry", "HEAD", stdout="")
        fake_subprocess.on("rev-parse", "tip1^{tree}", stdout="same\n")
        fake_subprocess.on(
            "merge-tree", "--write-tree", "--merge-base=base", stdout="same\n"
        )

        assert sync_diverged(REPO) == SyncResult("squash-synced", replayed=1)

        assert fake_subprocess.matching("ls-remote") == []
        assert len(_commit_tree_calls(fake_subprocess)) == 1
        assert fake_subprocess.commands[-1][-3:] == ["reset", "--keep", "tip1"]


UNMATCHED_UPSTREAM = (
    "upstream commit u1 matches no merged pull request of local commits"
)


def _assert_untouched_bail(fake: FakeSubprocess, reason: str) -> None:
    assert sync_diverged(REPO) == SyncResult(
        "failed", detail=f"squash sync stopped: {reason}"
    )
    assert fake.matching("reset") == []


class TestSquashSyncBails:
    def test_upstream_commit_without_tree_matching_head(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("rev-parse", "u1^{tree}", stdout="tree-u1\ntree-other\n")

        _assert_untouched_bail(fake_subprocess, UNMATCHED_UPSTREAM)

    def test_pull_request_partly_matching_local_commits(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "log", "--no-merges", stdout="p2\t200\tpr commit\np9\t999\tunknown commit\n"
        )

        _assert_untouched_bail(fake_subprocess, UNMATCHED_UPSTREAM)

    def test_upstream_commit_matching_a_pull_request_with_no_commits(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("log", "--no-merges", stdout="")

        _assert_untouched_bail(fake_subprocess, UNMATCHED_UPSTREAM)

    def test_replay_conflict(self, fake_subprocess: FakeSubprocess) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("merge-tree", returncode=1)

        _assert_untouched_bail(
            fake_subprocess,
            "git merge-tree --write-tree --merge-base=l1^ tip0 l1 exited 1",
        )
        assert _commit_tree_calls(fake_subprocess) == []

    def test_differing_trees_without_revised_commits(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("log", "--no-merges", stdout="p1\t100\tlocal work\n")
        fake_subprocess.on("cherry", "h1", stdout="- l1\n")
        fake_subprocess.on("log", "--reverse", stdout="l1\tp0\t100\tlocal work\n")
        fake_subprocess.on("rev-parse", "tip0^{tree}", stdout="upstream\n")

        _assert_untouched_bail(
            fake_subprocess,
            "local changes missing upstream match no merged pull request",
        )

    def test_no_pull_request_heads_listed(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("ls-remote", stdout="")

        _assert_untouched_bail(fake_subprocess, "origin lists no pull request heads")

    def test_no_reflog_version_matches_the_pull_request_commit(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on("patch-id", stdout="pidP p2\npidL l2\npidX l0\n")

        _assert_untouched_bail(
            fake_subprocess,
            "no earlier local version of l2 matches its merged pull request",
        )

    def test_fold_merge_conflict(self, fake_subprocess: FakeSubprocess) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "merge-tree", "--write-tree", "--merge-base=tree-base", returncode=1
        )

        _assert_untouched_bail(
            fake_subprocess,
            "git merge-tree --write-tree --merge-base=tree-base tree-tip1 l2 exited 1",
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


class TestPullRequestHeads:
    def test_only_heads_missing_locally_are_fetched(
        self, fake_subprocess: FakeSubprocess
    ) -> None:
        _route_divergence(fake_subprocess)
        fake_subprocess.on(
            "ls-remote", stdout="h1\trefs/pull/7/head\nh2\trefs/pull/8/head\n"
        )
        fake_subprocess.on("cat-file", stdout="h1 commit 200\nh2 missing\n")
        fake_subprocess.on(
            "rev-parse", "u1^{tree}", stdout="tree-u1\ntree-u1\ntree-h2\n"
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


class TestSplitLocal:
    def test_covered_skipped_and_rest_partitioned_in_local_order(self) -> None:
        commits = [
            LocalCommit("a1", "100", "first"),
            LocalCommit("b2", "200", "second"),
            LocalCommit("c3", "300", "third"),
            LocalCommit("d4", "400", "fourth"),
        ]

        unrelated, revised = split_local(
            commits, {"b2"}, {("100", "first"), ("400", "fourth")}
        )

        assert unrelated == [commits[2]]
        assert revised == [commits[0], commits[3]]
