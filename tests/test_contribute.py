"""Tests for the contribute module (derived PR branch management)."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import pytest
from conftest import ContributeRemote, FakeSubprocess

from llm_prompts import contribute, links
from llm_prompts.batching import (
    Batch,
    BatchPlan,
    Match,
    batch_branch,
    pending_plans,
)
from llm_prompts.contribute import (
    ApplyResult,
    Commit,
    Group,
    Pr,
    all_prs,
    apply_batch,
    base_ref,
    branch_name,
    fetch_base,
    find_blocking_commits,
    group_commits,
    inventory,
    is_conventional,
    log_commits,
    open_prs,
    push_remote,
    remote_branches,
    run_list,
    run_sync,
    scope_commits,
    slug_for,
    stale_main_warning,
)
from llm_prompts.size_guard import CheckResult

PROMPTS_PREFIX = "src/llm_prompts/prompts/"

_IN_SCOPE = f"{PROMPTS_PREFIX}shared/skills/foo/SKILL.md"
_OUT_SCOPE = "docs/notes.md"


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry network calls without waiting between attempts."""
    monkeypatch.setattr(contribute, "_RETRY_DELAY_SECONDS", 0)


def _passing_check() -> CheckResult:
    return CheckResult(passed=True, artifacts=[], violations=[], report="")


def _stub_cherry_pick(fake_subprocess: FakeSubprocess) -> None:
    fake_subprocess.on("branch", "--list", stdout="")
    fake_subprocess.on("worktree", "add")
    fake_subprocess.on("switch", "-c")
    fake_subprocess.on("cherry-pick")
    fake_subprocess.on("worktree", "remove")


def _plan(
    branch: str, group: Group, mode: Literal["append", "rebuild", "new"]
) -> BatchPlan:
    return BatchPlan(branch=branch, slug="foo", pr=None, groups=(group,), mode=mode)


class TestSlugFor:
    @pytest.mark.parametrize(
        ("subject", "expected"),
        [
            ("docs: foo bar", "foo-bar"),
            ("fix(cli): something", "something"),
            ("feat!: big change", "big-change"),
            ("feat: foo!!  bar--baz???", "foo-bar-baz"),
        ],
    )
    def test_known_subjects(self, subject: str, expected: str) -> None:
        assert slug_for(subject) == expected

    def test_truncates_at_a_hyphen_boundary(self) -> None:
        words = [f"word{i:02d}" for i in range(1, 20)]
        subject = "feat: " + " ".join(words)
        slug = slug_for(subject)
        full_slug = "-".join(words)

        assert len(slug) <= 50
        assert not slug.endswith("-")
        assert full_slug.startswith(slug)
        assert full_slug[len(slug) : len(slug) + 1] in ("-", "")


class TestBranchName:
    def test_joins_login_and_slug(self) -> None:
        assert branch_name("octocat", "add-foo-skill") == "octocat/add-foo-skill"


class TestIsConventional:
    @pytest.mark.parametrize(
        ("subject", "expected"),
        [
            ("docs: x", True),
            ("fix(cli): x", True),
            ("feat!: x", True),
            ("no colon here", False),
            ("justwords", False),
        ],
    )
    def test_known_subjects(self, subject: str, expected: bool) -> None:
        assert is_conventional(subject) is expected


class TestGroupCommits:
    def test_compression_commit_pairs_with_the_next_commit(self) -> None:
        compress = Commit("s1", "chore: compress abc", (_IN_SCOPE,))
        content = Commit("s2", "feat: add foo skill", (_IN_SCOPE,))
        groups = group_commits([compress, content], "tester", PROMPTS_PREFIX)

        assert len(groups) == 1
        assert groups[0].commits == (compress, content)
        assert groups[0].problems == ()
        assert groups[0].slug == slug_for(content.subject)
        assert groups[0].branch == branch_name("tester", groups[0].slug)

    def test_lone_content_commit_forms_its_own_group(self) -> None:
        content = Commit("s1", "feat: add bar skill", (_IN_SCOPE,))
        groups = group_commits([content], "tester", PROMPTS_PREFIX)

        assert len(groups) == 1
        assert groups[0].commits == (content,)
        assert groups[0].problems == ()

    def test_unpaired_compression_at_the_tip_is_flagged(self) -> None:
        content = Commit("s1", "feat: add baz skill", (_IN_SCOPE,))
        compress = Commit("s2", "chore: compress baz", (_IN_SCOPE,))
        groups = group_commits([content, compress], "tester", PROMPTS_PREFIX)

        assert len(groups) == 2
        assert groups[0].commits == (content,)
        assert groups[0].problems == ()
        assert groups[1].commits == (compress,)
        assert "unpaired-compression" in groups[1].problems

    def test_double_compression_is_flagged(self) -> None:
        first = Commit("s1", "chore: compress x", (_IN_SCOPE,))
        second = Commit("s2", "chore: compress y", (_IN_SCOPE,))
        groups = group_commits([first, second], "tester", PROMPTS_PREFIX)

        assert len(groups) == 1
        assert groups[0].commits == (first, second)
        assert "double-compression" in groups[0].problems

    def test_non_conventional_subject_is_flagged(self) -> None:
        content = Commit("s1", "randomly worded commit", (_IN_SCOPE,))
        groups = group_commits([content], "tester", PROMPTS_PREFIX)

        assert "non-conventional-subject" in groups[0].problems

    def test_colliding_slugs_flag_both_groups(self) -> None:
        first = Commit("s1", "feat: fix bug", (_IN_SCOPE,))
        second = Commit("s2", "docs: fix bug", (_IN_SCOPE,))
        groups = group_commits([first, second], "tester", PROMPTS_PREFIX)

        assert len(groups) == 2
        assert groups[0].branch == groups[1].branch
        assert "slug-collision" in groups[0].problems
        assert "slug-collision" in groups[1].problems

    def test_mixed_scope_commit_never_pairs_and_is_flagged(self) -> None:
        compress = Commit("s1", "chore: compress x", (_IN_SCOPE,))
        mixed = Commit("s2", "feat: mixed change", (_IN_SCOPE, _OUT_SCOPE))
        groups = group_commits([compress, mixed], "tester", PROMPTS_PREFIX)

        assert len(groups) == 2
        assert groups[0].commits == (compress,)
        assert "unpaired-compression" in groups[0].problems
        assert groups[1].commits == (mixed,)
        assert "mixed-scope" in groups[1].problems


class TestScopeCommits:
    def test_excludes_out_of_scope_and_includes_mixed_scope(self) -> None:
        commits = [
            Commit("aaa111", "feat: add foo skill", (_IN_SCOPE,)),
            Commit("bbb222", "docs: unrelated notes", (_OUT_SCOPE,)),
            Commit("ccc333", "fix(rules): mixed change", (_IN_SCOPE, _OUT_SCOPE)),
        ]

        assert scope_commits(commits, PROMPTS_PREFIX) == [commits[0], commits[2]]


class TestLogCommits:
    def _log(self, fake_subprocess: FakeSubprocess) -> None:
        fake_subprocess.on(
            "log",
            "--format=%H%x09%aI%x09%s",
            stdout=fake_subprocess.sha_dated_subjects(
                ("aaa111", "feat: add foo skill", "2024-01-01T00:00:00+00:00"),
                ("bbb222", "chore: empty", "2024-01-02T00:00:00+00:00"),
                ("ccc333", "fix: two paths", "2024-01-03T00:00:00+00:00"),
            ),
        )

    def test_reads_every_commits_paths_in_one_show(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        self._log(fake_subprocess)
        fake_subprocess.on(
            "show",
            "--pretty=format:%x00%H",
            "--name-only",
            stdout=f"\x00aaa111\n{_IN_SCOPE}\n\n\x00bbb222\n\x00ccc333\n{_IN_SCOPE}\n{_OUT_SCOPE}\n",
        )

        commits = log_commits(tmp_path, "origin/main")

        assert [c.sha for c in commits] == ["aaa111", "bbb222", "ccc333"]
        assert [c.paths for c in commits] == [
            (_IN_SCOPE,),
            (),
            (_IN_SCOPE, _OUT_SCOPE),
        ]
        assert len(fake_subprocess.matching("show")) == 1
        assert fake_subprocess.matching("show")[0][-3:] == [
            "aaa111",
            "bbb222",
            "ccc333",
        ]

    def test_commit_missing_from_show_output_has_no_paths(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        self._log(fake_subprocess)
        fake_subprocess.on(
            "show",
            "--pretty=format:%x00%H",
            "--name-only",
            stdout=f"\x00aaa111\n{_IN_SCOPE}\n",
        )

        commits = log_commits(tmp_path, "origin/main")

        assert [c.paths for c in commits] == [(_IN_SCOPE,), (), ()]

    def test_no_commits_makes_no_show_call(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%aI%x09%s", stdout="")

        assert log_commits(tmp_path, "origin/main") == []
        assert fake_subprocess.matching("show") == []


class TestPatchIds:
    def test_no_shas_makes_no_call(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        from llm_prompts.contribute import _patch_ids

        assert _patch_ids(tmp_path, []) == {}
        assert fake_subprocess.commands == []

    def test_maps_each_sha_with_one_show_and_one_patch_id_call(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        from llm_prompts.contribute import _patch_ids

        contribute_remote.main(("m1", "feat: one"), ("m2", "feat: two"))
        fake = contribute_remote.fake

        ids = _patch_ids(tmp_path, ["m1", "m2"])

        assert ids == {
            "m1": ContributeRemote.patch_id("m1"),
            "m2": ContributeRemote.patch_id("m2"),
        }
        assert len(fake.matching("show", "-U0")) == 1
        assert len(fake.matching("patch-id", "--stable")) == 1


class TestPatchIdIgnoresSurroundingContext:
    """Exercises real git, since a fake diff can't show context sensitivity."""

    def _git(self, tmp_path: Path, *args: str) -> str:
        return subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def test_patch_id_matches_the_same_change_applied_with_different_context(
        self, tmp_path: Path
    ) -> None:
        file_path = tmp_path / "file.txt"
        file_path.write_text("".join(f"line{n}\n" for n in range(1, 10)))
        self._git(tmp_path, "init", "-q")
        self._git(tmp_path, "add", "file.txt")
        self._git(tmp_path, "commit", "-q", "-m", "chore: base")
        base_sha = self._git(tmp_path, "rev-parse", "HEAD")

        lines = file_path.read_text().splitlines()
        lines[1] = "line2-changed"
        file_path.write_text("\n".join(lines) + "\n")
        self._git(tmp_path, "commit", "-q", "-am", "chore: change context")

        lines = file_path.read_text().splitlines()
        lines[4] = "line5-changed"
        file_path.write_text("\n".join(lines) + "\n")
        self._git(tmp_path, "commit", "-q", "-am", "feat: change target")
        main_sha = self._git(tmp_path, "rev-parse", "HEAD")

        self._git(tmp_path, "checkout", "-q", base_sha)
        self._git(tmp_path, "cherry-pick", main_sha)
        branch_sha = self._git(tmp_path, "rev-parse", "HEAD")

        from llm_prompts.contribute import _patch_ids

        patch_ids = _patch_ids(tmp_path, [main_sha, branch_sha])

        assert patch_ids[main_sha] != ""
        assert patch_ids[main_sha] == patch_ids[branch_sha]


class TestRemoteBranches:
    def test_parses_branch_names_from_ls_remote(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "ls-remote",
            "--heads",
            "origin",
            stdout=(
                "aaa111\trefs/heads/tester/add-foo-skill\n"
                "bbb222\trefs/heads/tester/fix-bar\n"
            ),
        )
        result = remote_branches(tmp_path, "tester")
        assert result == {"tester/add-foo-skill", "tester/fix-bar"}

    def test_retries_a_transient_connection_failure(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "ls-remote",
            stdout=["", "aaa111\trefs/heads/tester/fix-bar\n"],
            returncode=[128, 0],
            stderr=["fatal: unable to access: Couldn't connect to server\n", ""],
        )

        assert remote_branches(tmp_path, "tester") == {"tester/fix-bar"}


class TestOpenPrs:
    def test_keeps_both_prs_sharing_a_branch_name(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "gh",
            "pr",
            "list",
            stdout=json.dumps(
                [
                    {
                        "number": 12,
                        "state": "OPEN",
                        "url": "https://github.com/o/r/pull/12",
                        "headRefName": "tester/add-foo-skill",
                    },
                    {
                        "number": 9,
                        "state": "MERGED",
                        "url": "https://github.com/o/r/pull/9",
                        "headRefName": "tester/add-foo-skill",
                    },
                ]
            ),
        )
        result = all_prs(tmp_path)
        assert result == [
            ("tester/add-foo-skill", Pr(12, "OPEN", "https://github.com/o/r/pull/12")),
            ("tester/add-foo-skill", Pr(9, "MERGED", "https://github.com/o/r/pull/9")),
        ]

    def test_requests_a_high_limit_so_old_prs_are_not_truncated(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("gh", "pr", "list", stdout="[]")

        all_prs(tmp_path)

        call = fake_subprocess.matching("gh", "pr", "list")[0]
        assert "--limit" in call
        limit = int(call[call.index("--limit") + 1])
        assert limit >= 100

    def test_retries_a_transient_gh_failure(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "gh",
            "pr",
            "list",
            stdout=["", "[]"],
            returncode=[1, 0],
            stderr=["HTTP 502: Bad Gateway\n", ""],
        )

        assert all_prs(tmp_path) == []


class TestManualShas:
    def test_code_only_and_mixed_scope_commits_are_manual(self) -> None:
        rule = Commit("r1", "feat: add foo", (_IN_SCOPE,))
        code = Commit("c1", "fix: code", (_OUT_SCOPE,))
        mixed = Commit("m1", "feat: both", (_IN_SCOPE, _OUT_SCOPE))

        result = contribute._manual_shas([rule, code, mixed], PROMPTS_PREFIX)

        assert result == frozenset({"c1", "m1"})


class TestCollectReportProbe:
    KEY = ("fix: code", "2024-01-01T00:00:00+00:00")

    def _remote(self, contribute_remote: ContributeRemote) -> None:
        contribute_remote.main(("c1", "fix: code"), paths={"c1": (_OUT_SCOPE,)})

    def test_code_only_commit_with_a_remote_ref_is_pushed_without_a_pr(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        self._remote(contribute_remote)
        contribute_remote.fake.on(
            "branch", "-r", "--contains", "c1", stdout="origin/feature\n"
        )

        report = contribute.collect_report(
            tmp_path, contribute_remote.login, PROMPTS_PREFIX, frozenset({self.KEY})
        )

        assert report.statuses[self.KEY] == links.Status("needs PR", None, None)

    def test_code_only_commit_with_no_remote_ref_is_local_only(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        self._remote(contribute_remote)
        contribute_remote.fake.on("branch", "-r", "--contains", "c1", stdout="\n")

        report = contribute.collect_report(
            tmp_path, contribute_remote.login, PROMPTS_PREFIX, frozenset({self.KEY})
        )

        assert report.statuses[self.KEY] == links.Status("local only", None, None)

    def test_default_probe_makes_no_remote_ref_call(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        self._remote(contribute_remote)

        contribute.collect_report(tmp_path, contribute_remote.login, PROMPTS_PREFIX)

        assert contribute_remote.fake.matching("branch") == []


class TestOpenPrBody:
    def test_null_body_maps_to_empty_and_a_real_body_is_kept(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.unmanaged_pr("someone/a", 1, [("c1", "feat: a")])
        contribute_remote.unmanaged_pr("someone/b", 2, [("c2", "feat: b")])
        contribute_remote.body(2, "Depends on https://x/pull/9")
        contribute_remote.fake.on(
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--author",
            "@me",
            "--json",
            "number,state,url,headRefName,isDraft,reviewDecision,body",
            stdout=json.dumps(
                [
                    {
                        "number": number,
                        "state": "OPEN",
                        "url": f"https://x/pull/{number}",
                        "headRefName": f"someone/{number}",
                        "isDraft": False,
                        "reviewDecision": "",
                        "body": body,
                    }
                    for number, body in ((1, None), (2, "Depends on https://x/pull/9"))
                ]
            ),
        )

        prs, _ = open_prs(tmp_path)

        assert [pr.body for pr in prs] == ["", "Depends on https://x/pull/9"]


class TestPrsByBranch:
    def test_open_pr_wins_over_an_older_merged_pr_reusing_the_branch(self) -> None:
        from llm_prompts.contribute import _prs_by_branch

        open_pr = Pr(12, "OPEN", "https://github.com/o/r/pull/12")
        merged_pr = Pr(9, "MERGED", "https://github.com/o/r/pull/9")

        result = _prs_by_branch(
            [("tester/add-foo", open_pr), ("tester/add-foo", merged_pr)]
        )

        assert result == {"tester/add-foo": open_pr}

    def test_merged_pr_wins_over_a_closed_pr_when_no_pr_is_open(self) -> None:
        from llm_prompts.contribute import _prs_by_branch

        merged_pr = Pr(9, "MERGED", "https://github.com/o/r/pull/9")
        closed_pr = Pr(12, "CLOSED", "https://github.com/o/r/pull/12")

        result = _prs_by_branch(
            [("tester/add-foo", merged_pr), ("tester/add-foo", closed_pr)]
        )

        assert result == {"tester/add-foo": merged_pr}

    def test_highest_number_wins_among_only_closed_prs(self) -> None:
        from llm_prompts.contribute import _prs_by_branch

        older_closed = Pr(9, "CLOSED", "https://github.com/o/r/pull/9")
        newer_closed = Pr(12, "CLOSED", "https://github.com/o/r/pull/12")

        result = _prs_by_branch(
            [("tester/add-foo", older_closed), ("tester/add-foo", newer_closed)]
        )

        assert result == {"tester/add-foo": newer_closed}


class TestContributeRemote:
    def test_merged_pr_reports_state_and_commits(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        branch = contribute_remote.merged("fix-x", 12, [("m1", "fix: bug")])

        prs = dict(all_prs(tmp_path))
        assert prs[branch].state == "MERGED"

        listed = json.loads(
            subprocess.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--state",
                    "merged",
                    "--author",
                    "@me",
                    "--json",
                    "number,headRefName,title",
                ],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        assert listed == [{"number": 12, "headRefName": branch, "title": "fix: bug"}]

        viewed = json.loads(
            subprocess.run(
                ["gh", "pr", "view", "12", "--json", "commits"],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        assert viewed["commits"] == [
            {
                "oid": "m1",
                "messageHeadline": "fix: bug",
                "messageBody": "",
                "authoredDate": "2024-01-01T00:00:00+00:00",
            }
        ]


class TestInventory:
    def test_managed_branch_with_open_pr_returns_batch_carrying_pr(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        pr = Pr(5, "OPEN", "https://github.com/o/r/pull/5")
        contribute_remote.managed("add-foo", [("m1", "feat: add foo")], pr=pr)

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert [batch.pr for batch in inv.batches] == [pr]

    def test_managed_branch_with_no_pr_returns_batch_with_no_pr(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.managed("add-foo", [("m1", "feat: add foo")])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert [batch.pr for batch in inv.batches] == [None]

    def test_two_managed_batches_are_ordered_oldest_first(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        newer_pr = Pr(9, "OPEN", "https://github.com/o/r/pull/9")
        older_pr = Pr(3, "OPEN", "https://github.com/o/r/pull/3")
        contribute_remote.managed("b-batch", [("m2", "feat: b")], pr=newer_pr)
        contribute_remote.managed("a-batch", [("m1", "feat: a")], pr=older_pr)

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert [batch.slug for batch in inv.batches] == ["a-batch", "b-batch"]

    def test_merged_pr_records_its_number_and_branch_against_the_main_commit(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        branch = contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.merged_prs == {"m1": (7, branch)}

    def test_merged_pr_unique_subject_match_marks_main_commit_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1"})
        assert inv.past_slugs == frozenset({"add-foo"})

    def test_merged_pr_truncated_headline_still_matches_main_commit_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        subject = "feat: add a very long allowlist entry for the frobnicator service"
        contribute_remote.main(("m1", subject))
        contribute_remote.merged("add-foo", 7, [("c1", subject)])
        contribute_remote.truncate_headline(
            7, "c1", subject[:40] + "\u2026", "\u2026" + subject[40:]
        )

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1"})
        assert inv.past_slugs == frozenset({"add-foo"})

    def test_merged_legacy_pr_unique_subject_match_marks_main_commit_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged_legacy("tester/add-foo", 7, [("c1", "feat: add foo")])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1"})
        assert inv.past_slugs == frozenset()

    def test_legacy_branch_merged_pr_with_later_open_pr_still_marks_commit_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged_legacy("tester/add-foo", 7, [("c1", "feat: add foo")])
        contribute_remote.legacy(
            "tester/add-foo", pr=Pr(9, "OPEN", "https://github.com/o/r/pull/9")
        )

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1"})

    def test_branch_with_two_merged_prs_marks_commits_from_both_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"), ("m2", "feat: add bar"))
        contribute_remote.merged_legacy("tester/add-foo", 7, [("c1", "feat: add foo")])
        contribute_remote.merged_legacy("tester/add-foo", 8, [("c2", "feat: add bar")])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1", "m2"})

    def test_merged_pr_commits_come_from_per_pr_view(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1"})
        views = contribute_remote.fake.matching("gh", "pr", "view")
        assert len(views) == 1
        assert "7" in views[0]

    def test_two_merged_prs_each_viewed_and_both_marked_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"), ("m2", "feat: add bar"))
        contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])
        contribute_remote.merged("add-bar", 8, [("c2", "feat: add bar")])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1", "m2"})
        assert len(contribute_remote.fake.matching("gh", "pr", "view")) == 2

    def test_failed_pr_view_is_skipped_and_other_prs_still_marked_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"), ("m2", "feat: add bar"))
        contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])
        contribute_remote.merged("add-bar", 8, [("c2", "feat: add bar")])
        contribute_remote.fail_pr_view(7)

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m2"})

    def test_failed_pr_view_records_the_pr_number_as_skipped(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"), ("m2", "feat: add bar"))
        contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])
        contribute_remote.merged("add-bar", 8, [("c2", "feat: add bar")])
        contribute_remote.fail_pr_view(7)

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.skipped_prs == frozenset({7})

    def test_merged_pr_matching_no_pending_subject_is_not_viewed(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])
        contribute_remote.merged("unrelated", 9, [("c9", "chore: unrelated")])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1"})
        views = contribute_remote.fake.matching("gh", "pr", "view")
        assert [argv for argv in views if "9" in argv] == []
        assert len(views) == 1

    def test_merged_pr_discovered_by_list_call_marks_matching_commit_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        date = "2024-03-15T12:00:00+00:00"
        contribute_remote.main(
            ("m1", "feat: add foo"), ("m2", "feat: add bar"), dates={"m1": date}
        )
        contribute_remote.merged(
            "add-foo",
            7,
            [("c1", "feat: add foo"), ("c2", "feat: add bar")],
            dates={"c1": date, "c2": "2024-06-01T00:00:00+00:00"},
        )

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1"})

    def test_merged_pr_headref_without_login_prefix_still_marks_commit_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged_legacy(
            "add-foo-no-prefix", 7, [("c1", "feat: add foo")]
        )

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1"})

    def test_subject_match_with_different_authored_date_is_not_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged_legacy(
            "tester/add-foo",
            7,
            [("c1", "feat: add foo")],
            dates={"c1": "2024-06-01T00:00:00+00:00"},
        )

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset()

    def test_subject_match_with_same_authored_date_is_done(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        date = "2024-03-15T12:00:00+00:00"
        contribute_remote.main(("m1", "feat: add foo"), dates={"m1": date})
        contribute_remote.merged_legacy(
            "tester/add-foo", 7, [("c1", "feat: add foo")], dates={"c1": date}
        )

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset({"m1"})

    def test_closed_pr_contributes_nothing_to_done_or_batches(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.closed("add-foo", 8, [("c1", "feat: add foo")])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset()
        assert inv.batches == ()
        assert inv.past_slugs == frozenset({"add-foo"})

    def test_unmanaged_open_pr_maps_pending_commit_to_pr(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        pr = Pr(82, "OPEN", "https://github.com/o/r/pull/82")
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.unmanaged_pr("someone/add-foo", 82, [("m1", "feat: add foo")])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.unmanaged == {"m1": pr}

    def test_no_pr_batch_with_no_commits_ahead_of_base_sorts_last(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: one"))
        with_commits = contribute_remote.managed("has-commits", [("m1", "feat: one")])
        contribute_remote.fake.on_match(
            lambda argv: "--format=%aI" in argv and argv[-1] == "m1",
            stdout="2024-01-01T00:00:00+00:00\n",
        )
        empty_branch = contribute_remote.managed("empty-batch", [])

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert [batch.branch for batch in inv.batches] == [with_commits, empty_branch]

    def test_legacy_branch_with_only_closed_pr_leaves_commit_pending(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.legacy(
            "someone/add-foo", pr=Pr(8, "CLOSED", "https://github.com/o/r/pull/8")
        )

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.done == frozenset()
        assert inv.unmanaged == {}
        assert inv.batches == ()
        assert inv.legacy_orphans == ()


class TestBaseRef:
    def test_prefers_upstream_when_present(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("remote", stdout="origin\nupstream\n")
        assert base_ref(tmp_path) == "upstream/main"

    def test_falls_back_to_origin_without_upstream(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("remote", stdout="origin\n")
        assert base_ref(tmp_path) == "origin/main"


class TestFetchBase:
    def test_retries_a_transient_connection_failure(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "fetch",
            returncode=[128, 0],
            stderr=["fatal: unable to access: Couldn't connect to server\n", ""],
        )

        fetch_base(tmp_path, "origin")

        assert len(fake_subprocess.matching("fetch")) == 2

    def test_does_not_retry_a_non_transient_failure(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "fetch",
            returncode=1,
            stderr="fatal: couldn't find remote ref main\n",
        )

        with pytest.raises(subprocess.CalledProcessError):
            fetch_base(tmp_path, "origin")

        assert len(fake_subprocess.matching("fetch")) == 1


class TestStaleMainWarning:
    def test_empty_cherry_output_returns_none(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("cherry", "origin/main", "main", stdout="")
        assert stale_main_warning(tmp_path, "origin/main", "origin") is None

    def test_plus_only_output_returns_none(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("cherry", "origin/main", "main", stdout="+abc123 new\n")
        assert stale_main_warning(tmp_path, "origin/main", "origin") is None

    def test_minus_line_warns_with_the_fix_command(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("cherry", "origin/main", "main", stdout="-abc123 old\n")
        warning = stale_main_warning(tmp_path, "origin/main", "origin")
        assert warning is not None
        assert "git fetch origin main && git rebase origin/main" in warning

    def test_mixed_minus_and_plus_lines_still_warns(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "cherry", "origin/main", "main", stdout="-abc123 old\n+def456 new\n"
        )
        assert stale_main_warning(tmp_path, "origin/main", "origin") is not None

    def test_names_the_given_base_and_remote_not_origin(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("cherry", "upstream/main", "main", stdout="-abc123 old\n")
        warning = stale_main_warning(tmp_path, "upstream/main", "upstream")
        assert warning is not None
        assert "upstream/main" in warning
        assert "upstream main" in warning
        assert "origin" not in warning


class TestPushRemote:
    def test_admin_permission_uses_origin_without_forking(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        result = push_remote(tmp_path)
        assert result == "origin"
        assert fake_subprocess.matching("gh", "repo", "fork") == []

    def test_read_permission_forks_before_using_origin(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "READ"})
        )
        fake_subprocess.on("gh", "repo", "fork", "--remote")
        result = push_remote(tmp_path)
        assert result == "origin"
        assert fake_subprocess.matching("gh", "repo", "fork") != []


class TestRunSyncDryRun:
    def test_dry_run_never_pushes_or_deletes_branches(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("aaa111", "feat: add foo skill"))
        contribute_remote.legacy("tester/orphan-branch")
        contribute_remote.fake.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")

        run_sync(tmp_path, contribute_remote.login, PROMPTS_PREFIX, False, None, None)

        assert contribute_remote.fake.matching("push") == []
        assert contribute_remote.fake.matching("cherry-pick") == []

    def test_append_plan_lists_only_the_new_groups_shas(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        existing = [("b1", "feat: add foo"), ("b2", "feat: add bar")]
        contribute_remote.main(*existing, ("m3", "feat: add baz"))
        contribute_remote.managed("add-foo", existing)

        run_sync(tmp_path, contribute_remote.login, PROMPTS_PREFIX, False, None, None)

        out = capsys.readouterr().out
        cherry_pick_line = next(
            line for line in out.splitlines() if line.startswith("git cherry-pick")
        )
        assert cherry_pick_line == "git cherry-pick m3"

    def test_commits_limits_the_preview_to_the_selected_batch_and_skips_orphans(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"), ("m2", "feat: add bar"))
        contribute_remote.legacy("tester/orphan-branch")
        contribute_remote.fake.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")

        run_sync(
            tmp_path,
            contribute_remote.login,
            PROMPTS_PREFIX,
            False,
            None,
            None,
            ("m2",),
        )

        out = capsys.readouterr().out
        assert "git cherry-pick m2" in out
        assert "m1" not in out
        assert "would delete" not in out

    def test_unknown_commit_lists_the_problem_and_plans_nothing(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))

        result = run_sync(
            tmp_path,
            contribute_remote.login,
            PROMPTS_PREFIX,
            True,
            None,
            None,
            ("zzz",),
        )

        assert result == 1
        assert "zzz: not a local commit" in capsys.readouterr().out
        assert contribute_remote.fake.matching("push") == []

    def test_skipped_pr_view_refuses_dry_run_before_any_mutation(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])
        contribute_remote.fail_pr_view(7)

        result = run_sync(
            tmp_path, contribute_remote.login, PROMPTS_PREFIX, False, None, None
        )

        assert "warning" in capsys.readouterr().out
        assert result != 0
        assert contribute_remote.fake.matching("push") == []
        assert contribute_remote.fake.matching("gh", "pr", "create") == []
        assert contribute_remote.fake.matching("gh", "pr", "edit") == []


class TestRunSyncGroupsBeforeDroppingDoneCommits:
    def test_a_compression_pairs_content_commit_is_not_replanned_when_its_pair_is_done(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(
            ("c1", "chore: compress notes"), ("c2", "feat: add foo skill")
        )
        contribute_remote.merged("old-slug", 5, [("c1", "chore: compress notes")])

        run_sync(tmp_path, contribute_remote.login, PROMPTS_PREFIX, False, None, None)

        out = capsys.readouterr().out
        assert "c2" not in out


class TestOrphanScopeFilter:
    def test_legacy_branch_with_in_scope_changes_and_no_pr_is_orphan(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        branch = contribute_remote.legacy("tester/old-fix")
        contribute_remote.fake.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.legacy_orphans == (branch,)

    def test_legacy_branch_with_a_pr_is_not_orphan(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        pr = Pr(31, "OPEN", "https://github.com/o/r/pull/31")
        contribute_remote.legacy("tester/old-fix", pr=pr)

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.legacy_orphans == ()

    def test_legacy_branch_with_a_commit_not_on_main_is_not_orphan(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        branch = contribute_remote.legacy("tester/old-fix")
        contribute_remote.fake.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")
        contribute_remote.fake.on(
            "show", "-U0", "b1", stdout="commit b1\nfake diff b1\n"
        )
        contribute_remote.fake.on_match(
            lambda argv: (
                "--format=%H%x09%s" in argv and argv[-1].endswith(f"..origin/{branch}")
            ),
            stdout=contribute_remote.fake.sha_subjects(("b1", "feat: unmerged change")),
        )

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.legacy_orphans == ()

    def test_legacy_branch_with_commits_already_on_main_is_still_orphan(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        branch = contribute_remote.legacy("tester/old-fix")
        contribute_remote.fake.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")
        contribute_remote.fake.on_match(
            lambda argv: (
                "--format=%H%x09%s" in argv and argv[-1].endswith(f"..origin/{branch}")
            ),
            stdout=contribute_remote.fake.sha_subjects(("m1", "feat: add foo")),
        )

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert inv.legacy_orphans == (branch,)


class TestInventoryFetchesBeforeReadingBranches:
    def test_fetches_the_logins_refs_before_listing_branches(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.managed("add-foo", [("m1", "feat: add foo")])

        inventory(tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX)

        fetch_calls = contribute_remote.fake.matching("fetch")
        assert fetch_calls != []
        expected_refspec = (
            f"+refs/heads/{contribute_remote.login}/*:"
            f"refs/remotes/origin/{contribute_remote.login}/*"
        )
        assert expected_refspec in fetch_calls[0]

        ls_remote_calls = contribute_remote.fake.matching("ls-remote")
        assert ls_remote_calls != []
        commands = contribute_remote.fake.commands
        assert commands.index(fetch_calls[0]) < commands.index(ls_remote_calls[0])


class TestInventoryFetchSurvivesForcePush:
    """Exercises real git: rebuilds force-push their batch branch, so a stale
    local tracking ref is a non-fast-forward update that a `+`-less fetch
    refspec would reject.
    """

    def _git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def test_fetch_survives_a_force_pushed_managed_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin.git"
        repo = tmp_path / "repo"
        self._git(tmp_path, "init", "--bare", "-q", str(origin))
        self._git(tmp_path, "init", "-q", "-b", "main", str(repo))
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test")
        self._git(repo, "config", "commit.gpgsign", "false")
        (repo / "base.txt").write_text("base\n")
        self._git(repo, "add", "base.txt")
        self._git(repo, "commit", "-q", "-m", "chore: base")
        self._git(repo, "remote", "add", "origin", str(origin))
        self._git(repo, "push", "-q", "origin", "main")
        base_sha = self._git(repo, "rev-parse", "main")

        branch = batch_branch("tester", "foo")

        (repo / "old.txt").write_text("old\n")
        self._git(repo, "add", "old.txt")
        self._git(repo, "commit", "-q", "-m", "feat: old batch")
        old_sha = self._git(repo, "rev-parse", "HEAD")
        self._git(repo, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        self._git(repo, "update-ref", f"refs/remotes/origin/{branch}", old_sha)
        self._git(repo, "reset", "-q", "--hard", base_sha)

        (repo / "new.txt").write_text("new\n")
        self._git(repo, "add", "new.txt")
        self._git(repo, "commit", "-q", "-m", "feat: rebuilt batch")
        new_sha = self._git(repo, "rev-parse", "HEAD")
        self._git(repo, "push", "-q", "--force", "origin", f"HEAD:refs/heads/{branch}")
        self._git(repo, "reset", "-q", "--hard", base_sha)

        real_run = subprocess.run

        def fake_run(
            argv: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            if argv[0] == "gh":
                return subprocess.CompletedProcess(argv, 0, "[]", "")
            return real_run(argv, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_run)

        inventory(repo, "tester", "main", PROMPTS_PREFIX)

        updated_sha = self._git(repo, "rev-parse", f"refs/remotes/origin/{branch}")
        assert updated_sha == new_sha
        assert updated_sha != old_sha


class TestInventoryBatchOrdering:
    def test_no_pr_batches_are_ordered_by_first_commit_author_date(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(
            ("m1", "feat: one"), ("m1b", "feat: one-b"), ("m2", "feat: two")
        )
        older_branch = contribute_remote.managed(
            "zzz-slug", [("m1", "feat: one"), ("m1b", "feat: one-b")]
        )
        newer_branch = contribute_remote.managed("aaa-slug", [("m2", "feat: two")])
        contribute_remote.fake.on_match(
            lambda argv: "--format=%aI" in argv and argv[-1] == "m1",
            stdout="2021-06-01T23:00:00+09:00\n",
        )
        contribute_remote.fake.on_match(
            lambda argv: "--format=%aI" in argv and argv[-1] == "m2",
            stdout="2021-06-01T10:00:00-05:00\n",
        )
        # Simulates a rebuild's reset tip committer date; ordering ignores it.
        contribute_remote.fake.on_match(
            lambda argv: "--format=%cI" in argv and argv[-1] == "m1b",
            stdout="2024-01-01T00:00:00+00:00\n",
        )

        inv = inventory(
            tmp_path, contribute_remote.login, "origin/main", PROMPTS_PREFIX
        )

        assert [batch.branch for batch in inv.batches] == [older_branch, newer_branch]


class TestRunListStaleMainWarning:
    def test_warns_when_a_commit_is_squash_merged(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main()
        contribute_remote.fake.on("remote", stdout="origin\n")
        contribute_remote.fake.on(
            "cherry", "origin/main", "main", stdout="-abc123 old\n"
        )

        result = run_list(tmp_path, contribute_remote.login, PROMPTS_PREFIX)

        out = capsys.readouterr().out
        assert "git fetch origin main && git rebase origin/main" in out
        assert any(line.startswith("  warning:") for line in out.splitlines())
        assert result == 0


class TestRunListOut:
    def test_writes_to_the_given_stream_and_not_stdout(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        buf = io.StringIO()

        result = run_list(tmp_path, contribute_remote.login, PROMPTS_PREFIX, buf)

        assert "  local only:" in buf.getvalue()
        assert capsys.readouterr().out == ""
        assert result == 0


class TestRunList:
    def _list(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> tuple[int, str]:
        result = run_list(tmp_path, contribute_remote.login, PROMPTS_PREFIX)
        return result, capsys.readouterr().out

    def test_lists_every_pending_commit_regardless_of_a_sync_selection(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(
            ("m1", "feat: add foo"), ("m2", "feat: add bar"), ("m3", "feat: add baz")
        )

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert result == 0
        assert all(f"feat: add {name}" in out for name in ("foo", "bar", "baz"))

    def test_current_batch_with_open_pr_waits_for_review(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        pr = Pr(5, "OPEN", "https://github.com/o/r/pull/5")
        contribute_remote.main(("m1", "feat: add foo"))
        branch = contribute_remote.managed("add-foo", [("m1", "feat: add foo")], pr=pr)

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "  waiting for review:" in out
        assert f"    [#5 - needs review] {branch}" in out
        assert result == 0

    def test_pending_commit_in_unmanaged_pr_shown_under_its_pr(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.unmanaged_pr("someone/add-foo", 82, [("m1", "feat: add foo")])

        _, out = self._list(contribute_remote, tmp_path, capsys)

        assert "    [#82 - needs review] someone/add-foo" in out

    def test_mixed_scope_commit_in_unmanaged_pr_is_manual_not_a_problem(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(
            ("m1", "feat: mixed change"), paths={"m1": (_IN_SCOPE, _OUT_SCOPE)}
        )
        contribute_remote.unmanaged_pr(
            "someone/mixed", 82, [("m1", "feat: mixed change")]
        )

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "    [manual PR] [#82 - needs review] someone/mixed" in out
        assert "      m1 feat: mixed change [rule + code]" in out
        assert "problems:" not in out
        assert result == 0

    def test_pending_commit_with_no_batch_or_pr_is_local_only_new(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "  local only:" in out
        assert f"    [new] {batch_branch(contribute_remote.login, 'add-foo')}" in out
        assert result == 0

    def test_merged_pr_commit_shown_as_merged_not_local_only(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        branch = contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "  merged:" in out
        assert f"    [#7] {branch}" in out
        assert "local only:" not in out
        assert result == 0

    def test_regressed_batch_needs_sync_and_returns_exit_code_one(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.managed("add-foo", [("b1", "feat: add foo")])

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "  needs sync:" in out
        assert "[regressed]" in out
        assert result == 1

    def test_amended_batch_needs_sync_as_stale_and_returns_exit_code_one(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m2", "feat: add foo"))
        branch = contribute_remote.managed("add-foo", [("b1", "feat: add foo")])

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "  needs sync:" in out
        assert f"    [stale] {branch}" in out
        assert result == 1

    def test_pushed_batch_without_a_pr_needs_a_pr(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        branch = contribute_remote.managed("add-foo", [("m1", "feat: add foo")])

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert out == f"  needs PR:\n    {branch}\n      m1 feat: add foo\n"
        assert result == 0

    @pytest.mark.parametrize(
        ("draft", "decision", "heading", "label"),
        [
            (True, "", "draft", "#5"),
            (False, "CHANGES_REQUESTED", "changes requested", "#5"),
            (False, "APPROVED", "approved", "#5"),
            (False, "REVIEW_REQUIRED", "waiting for review", "#5 - needs review"),
        ],
    )
    def test_open_pr_stage_follows_its_review_state(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        draft: bool,
        decision: str,
        heading: str,
        label: str,
    ) -> None:
        pr = Pr(5, "OPEN", "https://github.com/o/r/pull/5")
        contribute_remote.main(("m1", "feat: add foo"))
        branch = contribute_remote.managed("add-foo", [("m1", "feat: add foo")], pr=pr)
        contribute_remote.review(5, draft=draft, decision=decision)

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert f"  {heading}:" in out
        assert f"    [{label}] {branch}" in out
        assert result == 0

    def test_unmanaged_pr_with_two_commits_has_one_header(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        commits = [("m1", "feat: add foo"), ("m2", "feat: add bar")]
        contribute_remote.main(*commits)
        contribute_remote.unmanaged_pr("someone/add-foo", 82, commits)

        _, out = self._list(contribute_remote, tmp_path, capsys)

        assert out == (
            "  waiting for review:\n"
            "    [#82 - needs review] someone/add-foo\n"
            "      m1 feat: add foo\n"
            "      m2 feat: add bar\n"
        )

    def test_unmanaged_pr_commit_missing_from_main_is_flagged(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        commits = [("m1", "feat: add foo")]
        contribute_remote.main(*commits)
        contribute_remote.unmanaged_pr("someone/add-foo", 82, commits)
        contribute_remote.pr_extra_commits(82, [("p2", "fix: tidy foo")])

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert out == (
            "  waiting for review:\n"
            "    [#82 - needs review] someone/add-foo\n"
            "      m1 feat: add foo\n"
            "      p2 fix: tidy foo [not on main]\n"
            "  warning: these open PRs hold commits local main does not have - "
            "cherry-pick them onto main:\n"
            "    someone/add-foo: git cherry-pick p2\n"
        )
        assert result == 1

    def test_rebased_unmanaged_pr_commit_counts_as_on_main(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"), ("m2", "feat: add bar"))
        contribute_remote.unmanaged_pr(
            "someone/add-foo", 82, [("p1", "feat: add foo"), ("p2", "feat: add bar")]
        )

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "not on main" not in out
        assert result == 0

    def test_pr_commit_with_same_subject_but_new_date_is_flagged(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        commits = [("m1", "feat: add foo")]
        contribute_remote.main(*commits)
        contribute_remote.unmanaged_pr("someone/add-foo", 82, commits)
        contribute_remote.pr_extra_commits(
            82, [("p2", "feat: add foo")], dates={"p2": "2024-02-01T00:00:00+00:00"}
        )

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "      p2 feat: add foo [not on main]" in out.splitlines()
        assert result == 1

    def test_pr_sharing_no_commit_with_main_stays_unlisted(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.unmanaged_pr("someone/other", 83, [("p1", "fix: other")])

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "someone/other" not in out
        assert "p1" not in out
        assert result == 0

    def test_regressed_managed_batch_is_not_also_flagged_as_not_on_main(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("b1", "feat: add foo"))
        branch = contribute_remote.managed(
            "add-foo",
            [("b1", "feat: add foo"), ("b2", "feat: add lost")],
            pr=Pr(5, "OPEN", "u"),
        )

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert f"    [regressed] [#5 - needs review] {branch}" in out.splitlines()
        assert "not on main" not in out
        assert result == 1

    def test_seven_pending_commits_preview_as_two_new_batches(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        commits = [(f"m{i}", f"feat: add thing{i}") for i in range(1, 8)]
        contribute_remote.main(*commits)
        first = batch_branch(contribute_remote.login, slug_for(commits[0][1]))
        second = batch_branch(contribute_remote.login, slug_for(commits[5][1]))

        result, out = self._list(contribute_remote, tmp_path, capsys)

        lines = [f"      {sha} {subject}" for sha, subject in commits]
        assert out.splitlines() == [
            "  local only:",
            f"    [new] {first}",
            *lines[:5],
            f"    [new] {second}",
            *lines[5:],
        ]
        assert result == 0

    def test_new_commit_beside_a_current_batch_shows_what_sync_adds(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        existing = [("b1", "feat: add foo"), ("b2", "feat: add bar")]
        contribute_remote.main(*existing, ("m3", "feat: add baz"))
        branch = contribute_remote.managed("add-foo", existing)

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert out == (
            "  local only:\n"
            f"    [adds 1] {branch}\n"
            "      b1 feat: add foo\n"
            "      b2 feat: add bar\n"
            "      m3 feat: add baz\n"
        )
        assert result == 0

    def test_code_only_commit_in_a_pr_is_a_manual_pr_under_that_pr(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "docs: note"), paths={"m1": (_OUT_SCOPE,)})
        contribute_remote.unmanaged_pr("someone/notes", 82, [("p1", "docs: note")])

        _, out = self._list(contribute_remote, tmp_path, capsys)

        assert out == (
            "  waiting for review:\n"
            "    [manual PR] [#82 - needs review] someone/notes\n"
            "      m1 docs: note [code]\n"
        )

    def test_code_only_commit_without_a_pr_needs_a_manual_pr(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "docs: note"), paths={"m1": (_OUT_SCOPE,)})

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert out == "  needs PR:\n    [manual PR]\n      m1 docs: note [code]\n"
        assert result == 0

    def test_code_only_commit_with_a_different_authored_date_is_not_matched(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "docs: note"), paths={"m1": (_OUT_SCOPE,)})
        contribute_remote.unmanaged_pr(
            "someone/notes",
            82,
            [("p1", "docs: note")],
            dates={"p1": "2024-02-02T00:00:00+00:00"},
        )

        _, out = self._list(contribute_remote, tmp_path, capsys)

        assert "  needs PR:" in out
        assert "[#82" not in out

    def test_two_code_only_commits_in_one_pr_share_a_header(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(
            ("m1", "docs: note one"),
            ("m2", "docs: note two"),
            paths={"m1": (_OUT_SCOPE,), "m2": (_OUT_SCOPE,)},
        )
        contribute_remote.unmanaged_pr(
            "someone/notes", 82, [("p1", "docs: note one"), ("p2", "docs: note two")]
        )

        _, out = self._list(contribute_remote, tmp_path, capsys)

        assert out.count("[#82 - needs review]") == 1
        assert "      m1 docs: note one [code]" in out
        assert "      m2 docs: note two [code]" in out

    def test_mixed_scope_commit_without_a_pr_needs_a_manual_pr(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(
            ("m1", "feat: mixed change"), paths={"m1": (_IN_SCOPE, _OUT_SCOPE)}
        )

        _, out = self._list(contribute_remote, tmp_path, capsys)

        assert out == (
            "  needs PR:\n    [manual PR]\n      m1 feat: mixed change [rule + code]\n"
        )

    def test_nothing_pending_says_so(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main()

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert out == "  no pending changes\n"
        assert result == 0

    def test_stages_lay_out_in_order_with_manual_commits_after_local_only(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(
            ("m1", "feat: add foo"),
            ("m2", "docs: note thing"),
            ("m3", "feat: mixed change"),
            paths={"m2": (_OUT_SCOPE,), "m3": (_IN_SCOPE, _OUT_SCOPE)},
        )

        _, out = self._list(contribute_remote, tmp_path, capsys)

        assert out == (
            "  local only:\n"
            "    [new] tester/contribute/add-foo\n"
            "      m1 feat: add foo\n"
            "  needs PR:\n"
            "    [manual PR]\n"
            "      m2 docs: note thing [code]\n"
            "      m3 feat: mixed change [rule + code]\n"
        )

    def test_non_conventional_commit_listed_as_a_problem_and_fails(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "add foo"))

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "  problems:" in out
        assert "    m1 add foo [non-conventional-subject]" in out
        assert result == 1

    def test_piped_output_has_no_color_codes(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))

        _, out = self._list(contribute_remote, tmp_path, capsys)

        assert "  local only:" in out
        assert "\033" not in out

    def test_queries_open_prs_once(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))

        self._list(contribute_remote, tmp_path, capsys)

        open_lists = contribute_remote.fake.matching(
            "gh", "pr", "list", "--state", "open"
        )
        assert len(open_lists) == 1

    def test_skipped_pr_view_warns_naming_the_pr_and_keeps_exit_code(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])
        contribute_remote.fail_pr_view(7)

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert "warning" in out
        assert "#7" in out
        assert result == 0

    def test_open_pr_commits_come_from_pr_view_and_a_failed_view_warns(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.unmanaged_pr("someone/add-foo", 82, [("m1", "feat: add foo")])
        contribute_remote.fail_pr_view(82)

        result, out = self._list(contribute_remote, tmp_path, capsys)

        assert contribute_remote.fake.matching("gh", "pr", "view", "82")
        assert "warning" in out
        assert "#82" in out
        assert result == 0


class TestRunSyncDoesNotQueryOpenPrs:
    def test_dry_run_never_lists_open_prs(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))

        run_sync(tmp_path, contribute_remote.login, PROMPTS_PREFIX, False, None, None)

        assert (
            contribute_remote.fake.matching("gh", "pr", "list", "--state", "open") == []
        )


class TestRunSyncStaleMainWarning:
    def test_regressed_batch_is_neither_rebuilt_nor_pushed(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.managed("foo", [("b1", "feat: foo")])
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )

        with (
            patch("llm_prompts.contribute.apply_batch") as mock_apply_batch,
            patch("llm_prompts.contribute.run_list", return_value=0),
        ):
            result = run_sync(
                tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
            )

        mock_apply_batch.assert_not_called()
        assert contribute_remote.fake.matching("push", "--force-with-lease") == []
        assert result == 1


class TestRunSyncApplyConflict:
    def test_conflict_pushes_nothing_for_that_batch_and_fails(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("aaa111", "feat: add foo skill"))
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )

        with (
            patch(
                "llm_prompts.contribute.apply_batch",
                return_value=ApplyResult(
                    outcome="conflict",
                    mode="new",
                    paths=("foo.md",),
                    message="error: could not apply aaa111...",
                ),
            ),
            patch("llm_prompts.contribute.run_list", return_value=0),
        ):
            result = run_sync(
                tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
            )

        out = capsys.readouterr().out
        assert "conflict" in out
        assert result == 1
        assert contribute_remote.fake.matching("push") == []


class TestRunSyncApplyCommitsConflict:
    def test_conflict_names_earlier_unselected_commits_touching_the_same_paths(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        shared = f"{PROMPTS_PREFIX}shared/rules/foo.md"
        contribute_remote.main(
            ("m1", "feat: add foo"),
            ("m2", "feat: tweak foo"),
            paths={"m1": [shared], "m2": [shared]},
        )
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )

        with (
            patch(
                "llm_prompts.contribute.apply_batch",
                return_value=ApplyResult(
                    outcome="conflict", mode="new", paths=(shared,), message="error"
                ),
            ),
            patch("llm_prompts.contribute.run_list", return_value=0),
        ):
            result = run_sync(
                tmp_path,
                contribute_remote.login,
                PROMPTS_PREFIX,
                True,
                None,
                None,
                ("m2",),
            )

        out = capsys.readouterr().out
        assert "blocked by earlier unselected commits: m1 feat: add foo" in out
        assert result == 1


class TestRunSyncApplySkippedPrView:
    def test_skipped_pr_view_refuses_before_any_push_or_pr_call(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged("add-foo", 7, [("c1", "feat: add foo")])
        contribute_remote.fail_pr_view(7)
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )

        with patch("llm_prompts.contribute.apply_batch") as mock_apply_batch:
            result = run_sync(
                tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
            )

        assert "#7" in capsys.readouterr().out
        assert result != 0
        mock_apply_batch.assert_not_called()
        assert contribute_remote.fake.matching("push") == []
        assert contribute_remote.fake.matching("gh", "pr", "create") == []
        assert contribute_remote.fake.matching("gh", "pr", "edit") == []


class TestBatchingEndToEnd:
    """Drive real user journeys through run_sync/run_list against a faked remote."""

    def _allow_apply(self, contribute_remote: ContributeRemote) -> None:
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        contribute_remote.fake.on("branch", "--list", stdout="")
        contribute_remote.fake.on("worktree", "add")
        contribute_remote.fake.on("switch", "-c")
        contribute_remote.fake.on("cherry-pick")
        contribute_remote.fake.on("worktree", "remove")
        contribute_remote.fake.on("push")
        contribute_remote.fake.on("branch", "-D")

    def test_three_pending_commits_land_in_one_current_batch(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        commits = [
            ("m1", "feat: add foo"),
            ("m2", "feat: add bar"),
            ("m3", "feat: add baz"),
        ]
        contribute_remote.main(*commits)
        self._allow_apply(contribute_remote)

        apply_result = run_sync(
            tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
        )
        assert apply_result == 0

        branch = contribute_remote.managed("add-foo", commits)
        capsys.readouterr()
        list_result = run_list(tmp_path, contribute_remote.login, PROMPTS_PREFIX)

        out = capsys.readouterr().out
        assert "  needs PR:" in out
        assert f"\n    {branch}\n" in out
        assert list_result == 0

    def test_new_commit_appends_to_existing_batch_without_force(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        existing = [("b1", "feat: add foo"), ("b2", "feat: add bar")]
        contribute_remote.main(*existing, ("m3", "feat: add baz"))
        contribute_remote.managed("add-foo", existing)
        self._allow_apply(contribute_remote)

        result = run_sync(
            tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
        )

        assert result == 0
        push_call = contribute_remote.fake.matching("push")[0]
        assert "--force-with-lease" not in push_call
        branch = batch_branch(contribute_remote.login, "add-foo")
        assert branch in push_call

    def test_six_pending_groups_split_into_batches_of_five_and_one(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        commits = [(f"m{i}", f"feat: add thing{i}") for i in range(1, 7)]
        contribute_remote.main(*commits)
        self._allow_apply(contribute_remote)

        result = run_sync(
            tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
        )
        assert result == 0

        first_branch = contribute_remote.managed("add-thing1", commits[:5])
        second_branch = contribute_remote.managed("add-thing6", commits[5:])
        capsys.readouterr()
        run_list(tmp_path, contribute_remote.login, PROMPTS_PREFIX)

        lines = capsys.readouterr().out.splitlines()
        first_at = lines.index(f"    {first_branch}")
        second_at = lines.index(f"    {second_branch}")
        assert lines[first_at + 1 : second_at] == [
            f"      {sha} {subject}" for sha, subject in commits[:5]
        ]
        assert lines[second_at + 1 :] == [
            f"      {sha} {subject}" for sha, subject in commits[5:]
        ]

    def test_new_commit_after_merge_starts_new_batch_without_repushing_merged(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"), ("m2", "feat: add bar"))
        contribute_remote.merged("add-foo", 10, [("c1", "feat: add foo")])
        self._allow_apply(contribute_remote)

        result = run_sync(
            tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
        )

        assert result == 0
        pushed_branches = [call[-1] for call in contribute_remote.fake.matching("push")]
        old_branch = batch_branch(contribute_remote.login, "add-foo")
        new_branch = batch_branch(contribute_remote.login, "add-bar")
        assert old_branch not in pushed_branches
        assert new_branch in pushed_branches

    def test_amended_commit_rebuilds_batch_with_force_and_shows_current(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m2", "feat: add foo"))
        contribute_remote.managed("add-foo", [("b1", "feat: add foo")])
        self._allow_apply(contribute_remote)

        result = run_sync(
            tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
        )

        assert result == 0
        push_call = contribute_remote.fake.matching("push")[0]
        assert "--force-with-lease" in push_call

        contribute_remote.managed("add-foo", [("m2", "feat: add foo")])
        capsys.readouterr()
        list_result = run_list(tmp_path, contribute_remote.login, PROMPTS_PREFIX)

        out = capsys.readouterr().out
        assert "  needs PR:" in out
        assert "needs sync" not in out
        assert list_result == 0

    def test_commit_already_in_unmanaged_pr_is_excluded_and_shown_as_in_pr(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.unmanaged_pr("someone/add-foo", 82, [("m1", "feat: add foo")])
        self._allow_apply(contribute_remote)

        result = run_sync(
            tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
        )

        assert contribute_remote.fake.matching("cherry-pick") == []
        assert contribute_remote.fake.matching("push") == []
        assert result == 0

        capsys.readouterr()
        run_list(tmp_path, contribute_remote.login, PROMPTS_PREFIX)
        out = capsys.readouterr().out
        assert "    [#82 - needs review] someone/add-foo" in out


class TestApplyBatch:
    def test_append_keeps_existing_shas_and_adds_only_new_commits(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        _stub_cherry_pick(fake_subprocess)

        branch = "tester/contribute/foo"
        new_commit = Commit("bbb222", "feat: new change", (f"{PROMPTS_PREFIX}bar.md",))
        group = Group((new_commit,), "foo", branch, ())
        plan = _plan(branch, group, "append")
        batch = Batch(branch, "foo", None, (), Match({}, frozenset(), ()))

        with patch("llm_prompts.contribute.check", return_value=_passing_check()):
            result = apply_batch(tmp_path, plan, "alt", PROMPTS_PREFIX, batch)

        assert result.outcome == "picked"
        assert result.mode == "append"
        worktree_call = fake_subprocess.matching("worktree", "add")[0]
        assert worktree_call[-1] == f"origin/{branch}"
        cherry_pick_shas = [
            sha for call in fake_subprocess.matching("cherry-pick") for sha in call[4:]
        ]
        assert cherry_pick_shas == ["bbb222"]

    def test_append_excludes_groups_the_batch_already_owns(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        _stub_cherry_pick(fake_subprocess)

        branch = "tester/contribute/foo"
        owned_commit = Commit("aaa111", "feat: a", (f"{PROMPTS_PREFIX}a.md",))
        new_commit = Commit("bbb222", "feat: new change", (f"{PROMPTS_PREFIX}bar.md",))
        owned_group = Group((owned_commit,), "a", branch, ())
        new_group = Group((new_commit,), "foo", branch, ())
        plan = BatchPlan(
            branch=branch,
            slug="foo",
            pr=None,
            groups=(owned_group, new_group),
            mode="append",
        )
        branch_commit = Commit("ccc333", "feat: a", ())
        match = Match(owned={"ccc333": owned_commit}, amended=frozenset(), unmatched=())
        batch = Batch(branch, "foo", None, (branch_commit,), match)

        with patch("llm_prompts.contribute.check", return_value=_passing_check()):
            result = apply_batch(tmp_path, plan, "alt", PROMPTS_PREFIX, batch)

        assert result.outcome == "picked"
        cherry_pick_shas = [
            sha for call in fake_subprocess.matching("cherry-pick") for sha in call[4:]
        ]
        assert cherry_pick_shas == ["bbb222"]

    def test_rebuild_is_base_plus_every_groups_commits_in_order(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        _stub_cherry_pick(fake_subprocess)

        branch = "tester/contribute/foo"
        commit_a = Commit("aaa111", "feat: a", (f"{PROMPTS_PREFIX}a.md",))
        commit_b = Commit("bbb222", "feat: b", (f"{PROMPTS_PREFIX}b.md",))
        group_a = Group((commit_a,), "a", branch, ())
        group_b = Group((commit_b,), "b", branch, ())
        plan = BatchPlan(
            branch=branch,
            slug="foo",
            pr=None,
            groups=(group_a, group_b),
            mode="rebuild",
        )

        with patch("llm_prompts.contribute.check", return_value=_passing_check()):
            result = apply_batch(tmp_path, plan, "alt", PROMPTS_PREFIX)

        assert result.outcome == "picked"
        assert result.mode == "rebuild"
        worktree_call = fake_subprocess.matching("worktree", "add")[0]
        assert worktree_call[-1] == "alt"
        cherry_pick_shas = [
            sha for call in fake_subprocess.matching("cherry-pick") for sha in call[4:]
        ]
        assert cherry_pick_shas == ["aaa111", "bbb222"]

    def test_new_is_base_plus_the_plans_groups(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        _stub_cherry_pick(fake_subprocess)

        branch = "tester/contribute/foo"
        commit = Commit("aaa111", "feat: a", (f"{PROMPTS_PREFIX}a.md",))
        group = Group((commit,), "foo", branch, ())
        plan = _plan(branch, group, "new")

        with patch("llm_prompts.contribute.check", return_value=_passing_check()):
            result = apply_batch(tmp_path, plan, "alt", PROMPTS_PREFIX)

        assert result.outcome == "picked"
        assert result.mode == "new"
        worktree_call = fake_subprocess.matching("worktree", "add")[0]
        assert worktree_call[-1] == "alt"
        cherry_pick_shas = [
            sha for call in fake_subprocess.matching("cherry-pick") for sha in call[4:]
        ]
        assert cherry_pick_shas == ["aaa111"]

    def test_existing_local_branch_of_the_same_name_still_succeeds(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        branch = "tester/contribute/foo"
        fake_subprocess.on("branch", "--list", stdout=f"{branch}\n")
        fake_subprocess.on("branch", "-D")
        fake_subprocess.on("worktree", "add")
        fake_subprocess.on("switch", "-c")
        fake_subprocess.on("cherry-pick")
        fake_subprocess.on("worktree", "remove")

        commit = Commit("aaa111", "feat: a", (f"{PROMPTS_PREFIX}a.md",))
        group = Group((commit,), "foo", branch, ())
        plan = _plan(branch, group, "new")

        with patch("llm_prompts.contribute.check", return_value=_passing_check()):
            result = apply_batch(tmp_path, plan, "alt", PROMPTS_PREFIX)

        assert result.outcome == "picked"
        assert fake_subprocess.matching("branch", "-D") != []


class TestApplyGroupConflict:
    def _register_conflicting_cherry_pick(
        self, fake_subprocess: FakeSubprocess, *, branch_exists: bool
    ) -> None:
        fake_subprocess.on(
            "branch",
            "--list",
            stdout="tester/contribute/foo\n" if branch_exists else "",
        )
        fake_subprocess.on("branch", "-D")
        fake_subprocess.on(
            "cherry-pick",
            stderr=(
                "error: could not apply aaa111... feat: main change\n"
                "hint: After resolving the conflicts, mark them with\n"
            ),
            returncode=1,
        )
        fake_subprocess.on("cherry-pick", "--abort")
        fake_subprocess.on(
            "diff", "--name-only", "--diff-filter=U", stdout="file.txt\n"
        )

    def test_rebuild_conflict_returns_conflict_with_paths_and_message(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        self._register_conflicting_cherry_pick(fake_subprocess, branch_exists=False)

        commit = Commit("aaa111", "feat: main change", ("file.txt",))
        branch = "tester/contribute/foo"
        group = Group((commit,), "foo", branch, ())
        plan = _plan(branch, group, "rebuild")

        result = apply_batch(tmp_path, plan, "alt", PROMPTS_PREFIX)

        assert result.outcome == "conflict"
        assert result.mode == "rebuild"
        assert result.paths == ("file.txt",)
        assert result.message == "error: could not apply aaa111... feat: main change"

    def test_append_conflict_falls_back_to_rebuild(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("branch", "--list", stdout="")
        fake_subprocess.on("branch", "-D")
        fake_subprocess.on("worktree", "add")
        fake_subprocess.on("switch", "-c")
        fake_subprocess.on(
            "cherry-pick",
            returncode=[1, 0],
            stderr=["error: could not apply bbb222... feat: new change\n", ""],
        )
        fake_subprocess.on("cherry-pick", "--abort")
        fake_subprocess.on(
            "diff", "--name-only", "--diff-filter=U", stdout="file.txt\n"
        )
        fake_subprocess.on("worktree", "remove")

        commit = Commit("bbb222", "feat: new change", (f"{PROMPTS_PREFIX}bar.md",))
        branch = "tester/contribute/foo"
        group = Group((commit,), "foo", branch, ())
        plan = _plan(branch, group, "append")
        batch = Batch(branch, "foo", None, (), Match({}, frozenset(), ()))

        with patch("llm_prompts.contribute.check", return_value=_passing_check()):
            result = apply_batch(tmp_path, plan, "alt", PROMPTS_PREFIX, batch)

        assert result.outcome == "picked"
        assert result.mode == "rebuild"
        abort_call = fake_subprocess.matching("cherry-pick", "--abort")[0]
        abort_index = fake_subprocess.commands.index(abort_call)
        assert any(
            "alt" in call for call in fake_subprocess.commands[abort_index + 1 :]
        )


class TestApplyGroupOversize:
    def test_failed_size_check_returns_its_report(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        _stub_cherry_pick(fake_subprocess)

        commit = Commit("aaa111", "feat: main change", (f"{PROMPTS_PREFIX}foo.md",))
        branch = "tester/contribute/foo"
        group = Group((commit,), "foo", branch, ())
        plan = _plan(branch, group, "new")

        with patch(
            "llm_prompts.contribute.check",
            return_value=CheckResult(
                passed=False, artifacts=[], violations=[], report="too big"
            ),
        ):
            result = apply_batch(tmp_path, plan, "alt", PROMPTS_PREFIX)

        assert result.outcome == "oversize"
        assert result.paths == ()
        assert result.message == "too big"


class TestRunSyncApplyPickedCleanup:
    def test_append_plan_pushes_without_force(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("aaa111", "feat: add foo skill"))
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        contribute_remote.fake.on("push")
        contribute_remote.fake.on("branch", "-D")

        with (
            patch(
                "llm_prompts.contribute.apply_batch",
                return_value=ApplyResult(
                    outcome="picked", mode="append", paths=(), message=""
                ),
            ),
            patch("llm_prompts.contribute.run_list", return_value=0),
        ):
            result = run_sync(
                tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
            )

        assert result == 0
        push_call = contribute_remote.fake.matching("push")[0]
        assert "--force-with-lease" not in push_call

    def test_rebuild_or_new_plan_pushes_with_force_with_lease(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("aaa111", "feat: add foo skill"))
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        contribute_remote.fake.on("push")
        contribute_remote.fake.on("branch", "-D")

        with (
            patch(
                "llm_prompts.contribute.apply_batch",
                return_value=ApplyResult(
                    outcome="picked", mode="new", paths=(), message=""
                ),
            ),
            patch("llm_prompts.contribute.run_list", return_value=0),
        ):
            result = run_sync(
                tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
            )

        assert result == 0
        push_call = contribute_remote.fake.matching("push")[0]
        assert "--force-with-lease" in push_call


class TestRunSyncApplyListsAfter:
    def test_only_applies_just_the_named_batch(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1a", "feat: existing"), ("m2a", "feat: other"))
        first = contribute_remote.managed("existing-batch", [("b1", "feat: existing")])
        second = contribute_remote.managed("other-batch", [("b2", "feat: other")])
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        contribute_remote.fake.on("push")
        contribute_remote.fake.on("branch", "-D")

        with (
            patch(
                "llm_prompts.contribute.apply_batch",
                return_value=ApplyResult(
                    outcome="picked", mode="rebuild", paths=(), message=""
                ),
            ) as mock_apply_batch,
            patch("llm_prompts.contribute.run_list", return_value=0),
        ):
            run_sync(
                tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, first, None
            )

        applied_branches = [
            call.args[1].branch for call in mock_apply_batch.call_args_list
        ]
        assert applied_branches == [first]
        assert not any(
            second in call for call in contribute_remote.fake.matching("push")
        )


class TestRunSyncApplyCommits:
    def test_commits_pushes_only_the_selected_batch_and_keeps_orphans(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"), ("m2", "feat: add bar"))
        contribute_remote.legacy("tester/orphan-branch")
        contribute_remote.fake.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        contribute_remote.fake.on("push")
        contribute_remote.fake.on("branch", "-D")

        with (
            patch(
                "llm_prompts.contribute.apply_batch",
                return_value=ApplyResult(
                    outcome="picked", mode="new", paths=(), message=""
                ),
            ) as mock_apply_batch,
            patch("llm_prompts.contribute.run_list", return_value=0),
        ):
            run_sync(
                tmp_path,
                contribute_remote.login,
                PROMPTS_PREFIX,
                True,
                None,
                None,
                ("m2",),
            )

        applied = [call.args[1] for call in mock_apply_batch.call_args_list]
        assert [
            commit.sha
            for plan in applied
            for group in plan.groups
            for commit in group.commits
        ] == ["m2"]
        assert contribute_remote.fake.matching("push", "origin", "--delete") == []


class TestRunSyncApplyOrphanCleanup:
    def test_apply_deletes_a_legacy_orphan_with_no_pr(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.legacy("tester/orphan-branch")
        contribute_remote.fake.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        contribute_remote.fake.on("push")

        with patch("llm_prompts.contribute.run_list", return_value=0):
            result = run_sync(
                tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
            )

        out = capsys.readouterr().out
        assert "tester/orphan-branch: deleted (orphan, no PR)" in out
        assert result == 0
        delete_calls = contribute_remote.fake.matching("push", "origin", "--delete")
        assert any("tester/orphan-branch" in call for call in delete_calls)

    def test_apply_retries_a_transient_push_failure(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
    ) -> None:
        contribute_remote.legacy("tester/orphan-branch")
        contribute_remote.fake.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        contribute_remote.fake.on(
            "push",
            returncode=[128, 0],
            stderr=["fatal: unable to access: Couldn't connect to server\n", ""],
        )

        with patch("llm_prompts.contribute.run_list", return_value=0):
            result = run_sync(
                tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
            )

        assert result == 0
        assert len(contribute_remote.fake.matching("push", "origin", "--delete")) == 2

    def test_apply_does_not_delete_a_legacy_branch_with_a_commit_not_on_main(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        branch = contribute_remote.legacy("tester/old-fix")
        contribute_remote.fake.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")
        contribute_remote.fake.on(
            "show", "-U0", "b1", stdout="commit b1\nfake diff b1\n"
        )
        contribute_remote.fake.on_match(
            lambda argv: (
                "--format=%H%x09%s" in argv and argv[-1].endswith(f"..origin/{branch}")
            ),
            stdout=contribute_remote.fake.sha_subjects(("b1", "feat: unmerged change")),
        )
        contribute_remote.fake.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        contribute_remote.fake.on("push")

        with patch("llm_prompts.contribute.run_list", return_value=0):
            run_sync(
                tmp_path, contribute_remote.login, PROMPTS_PREFIX, True, None, None
            )

        assert contribute_remote.fake.matching("push", "origin", "--delete") == []

    def test_cleanup_of_a_legacy_branch_with_a_pr_is_refused(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        pr = Pr(31, "OPEN", "https://github.com/o/r/pull/31")
        contribute_remote.legacy("tester/old-fix", pr=pr)

        result = run_sync(
            tmp_path,
            contribute_remote.login,
            PROMPTS_PREFIX,
            True,
            None,
            "tester/old-fix",
        )

        out = capsys.readouterr().out
        assert "refusing to clean up" in out
        assert result == 1
        assert contribute_remote.fake.matching("push", "origin", "--delete") == []


class TestFindBlockingCommits:
    def test_finds_earlier_group_touching_the_same_path(self) -> None:
        blocker_commit = Commit("aaa111", "feat: add foo skill", ("shared/foo.md",))
        blocker_group = Group((blocker_commit,), "add-foo", "user/add-foo", ())

        target_commit = Commit("bbb222", "feat: tweak bar skill", ("shared/bar.md",))
        target_group = Group((target_commit,), "tweak-bar", "user/tweak-bar", ())

        groups = [blocker_group, target_group]

        blockers = find_blocking_commits(groups, target_group, ("shared/foo.md",))

        assert blockers == [blocker_commit]

    def test_no_blockers_when_no_earlier_group_touches_the_path(self) -> None:
        target_commit = Commit("bbb222", "feat: tweak bar skill", ("shared/bar.md",))
        target_group = Group((target_commit,), "tweak-bar", "user/tweak-bar", ())

        groups = [target_group]

        blockers = find_blocking_commits(groups, target_group, ("shared/bar.md",))

        assert blockers == []


def _report(exit: int = 0, warnings: list[str] | None = None) -> contribute.Report:
    return contribute.Report(None, [], [], warnings or [], exit, {}, {})


def test_list_targets_prints_headers_in_order_and_returns_max_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    targets = [("alpha", Path("/repo-a"), "feat"), ("beta", Path("/repo-b"), "fix")]

    def fake_collect(repo: Path, login: str, prefix: str) -> contribute.Report:
        return _report(int(repo == Path("/repo-b")), [f"listed {repo}"])

    with patch("llm_prompts.contribute.collect_report", side_effect=fake_collect):
        status = contribute.list_targets(targets, "someone")

    assert status == 1
    assert capsys.readouterr().out == (
        "[alpha]\n  no pending changes\n  listed /repo-a\n\n"
        "[beta]\n  no pending changes\n  listed /repo-b\n\n"
    )


def test_sync_targets_runs_each_target_in_order_and_returns_max_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    targets = [("alpha", Path("/repo-a"), "feat"), ("beta", Path("/repo-b"), "fix")]
    seen: list[Path] = []

    def fake_sync(repo: Path, *args: Any) -> int:
        seen.append(repo)
        return 2 if repo == Path("/repo-a") else 0

    with patch("llm_prompts.contribute.run_sync", side_effect=fake_sync) as mock_sync:
        status = contribute.sync_targets(targets, "someone", True, "only", None)

    assert status == 2
    assert seen == [Path("/repo-a"), Path("/repo-b")]
    assert mock_sync.call_args.args[1:] == ("someone", "fix", True, "only", None, ())
    assert capsys.readouterr().out == "[alpha]\n\n[beta]\n\n"


def _link_file(path: Path, dependent: Commit, dependency: Commit) -> None:
    links.save_links(
        path,
        (
            links.Link(
                "beta",
                dependent.subject,
                dependent.authored_date,
                "alpha",
                dependency.subject,
                dependency.authored_date,
            ),
        ),
    )


ALPHA_COMMIT = Commit("a1", "feat: add alpha thing", (_IN_SCOPE,), "", "2026-01-01")
BETA_COMMIT = Commit("b1", "feat: add beta thing", (_IN_SCOPE,), "", "2026-01-02")
CODE_COMMIT = Commit("c1", "fix: code change", ("src/app.py",), "", "2026-01-03")
TWO_TARGETS = [
    ("alpha", Path("/tmp/alpha"), PROMPTS_PREFIX),
    ("beta", Path("/tmp/beta"), PROMPTS_PREFIX),
]


class TestCollectReportStatuses:
    DATE = "2024-01-01T00:00:00+00:00"

    def _statuses(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> dict[tuple[str, str], links.Status]:
        return contribute.collect_report(
            tmp_path, contribute_remote.login, PROMPTS_PREFIX
        ).statuses

    def test_commit_in_a_reviewed_batch_carries_stage_url_and_branch(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        pr = Pr(5, "OPEN", "https://github.com/o/r/pull/5")
        contribute_remote.main(("m1", "feat: add foo"))
        branch = contribute_remote.managed("add-foo", [("m1", "feat: add foo")], pr=pr)

        assert self._statuses(contribute_remote, tmp_path) == {
            ("feat: add foo", self.DATE): links.Status(
                "waiting for review", pr.url, branch
            )
        }

    def test_unpushed_commit_is_local_only_without_a_url(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))

        assert self._statuses(contribute_remote, tmp_path) == {
            ("feat: add foo", self.DATE): links.Status(
                "local only", None, "tester/contribute/add-foo"
            )
        }

    def test_merged_commit_is_absent(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.merged("add-foo", 9, [("c1", "feat: add foo")])

        assert self._statuses(contribute_remote, tmp_path) == {}


class TestRunSyncHeld:
    def _preview(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        held: dict[str, str] | None,
        commits: tuple[str, ...] = (),
    ) -> str:
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            run_sync(
                tmp_path,
                contribute_remote.login,
                PROMPTS_PREFIX,
                False,
                None,
                None,
                commits,
                held,
            )
        return out.getvalue()

    def test_held_commit_is_listed_and_left_out_of_the_plan(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"), ("m2", "feat: add bar"))

        out = self._preview(
            contribute_remote, tmp_path, {"m1": "alpha: dep is local only"}
        )

        assert "m1: held while alpha: dep is local only" in out
        assert "git cherry-pick m2" in out
        assert "cherry-pick m1" not in out

    def test_any_held_commit_holds_its_whole_group(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("c1", "chore: compress foo"), ("c2", "feat: add foo"))

        out = self._preview(
            contribute_remote, tmp_path, {"c2": "alpha: dep is local only"}
        )

        assert "c1: held while alpha: dep is local only" in out
        assert "c2: held while alpha: dep is local only" in out
        assert "cherry-pick" not in out

    def test_group_already_owned_by_a_batch_is_never_held(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))
        contribute_remote.managed("add-foo", [("m1", "feat: add foo")])

        out = self._preview(
            contribute_remote, tmp_path, {"m1": "alpha: dep is local only"}
        )

        assert "held while" not in out

    def test_nothing_held_leaves_the_selection_unset(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"))

        with patch(
            "llm_prompts.contribute.pending_plans", wraps=pending_plans
        ) as mock_plans:
            self._preview(contribute_remote, tmp_path, None)

        assert mock_plans.call_args.args[3] is None

    def test_held_commits_are_removed_from_an_explicit_selection(
        self, contribute_remote: ContributeRemote, tmp_path: Path
    ) -> None:
        contribute_remote.main(("m1", "feat: add foo"), ("m2", "feat: add bar"))

        with patch(
            "llm_prompts.contribute.pending_plans", wraps=pending_plans
        ) as mock_plans:
            self._preview(
                contribute_remote, tmp_path, {"m1": "alpha: dep"}, ("m1", "m2")
            )

        assert mock_plans.call_args.args[3] == frozenset({"m2"})


class TestSyncTargetsLinks:
    def _patched(
        self,
        dependency_statuses: dict[tuple[str, str], links.Status] | None = None,
        beta_commits: list[Commit] | None = None,
    ) -> Any:
        commits = {"alpha": [ALPHA_COMMIT], "beta": beta_commits or [BETA_COMMIT]}
        return (
            patch("llm_prompts.contribute.base_ref", return_value="origin/main"),
            patch(
                "llm_prompts.contribute.log_commits",
                side_effect=lambda repo, base: commits[repo.name],
            ),
            patch(
                "llm_prompts.contribute.collect_report",
                return_value=_report_with(dependency_statuses or {}),
            ),
        )

    def test_cross_repo_commits_resolve_per_repo_and_the_dependency_runs_first(
        self, isolated_links_path: Path
    ) -> None:
        order: list[tuple[str, Any]] = []

        def record_sync(repo: Any, *args: Any) -> int:
            order.append((repo.name, args[-1]))
            return 0

        base, log, report = self._patched()
        with (
            base,
            log,
            report,
            patch(
                "llm_prompts.contribute.run_sync",
                side_effect=record_sync,
            ),
        ):
            status = contribute.sync_targets(
                list(reversed(TWO_TARGETS)), "me", False, None, None, ("a1", "b1")
            )

        assert status == 0
        assert order == [("alpha", ["a1"]), ("beta", ["b1"])]

    def test_code_only_dependent_is_linked_but_never_synced(
        self, isolated_links_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base, log, report = self._patched(beta_commits=[CODE_COMMIT])
        with (
            base,
            log,
            report,
            patch("llm_prompts.contribute.run_sync", return_value=0) as mock_sync,
        ):
            contribute.sync_targets(TWO_TARGETS, "me", True, None, None, ("a1", "c1"))

        assert [call.args[0].name for call in mock_sync.call_args_list] == ["alpha"]
        assert links.load_links(isolated_links_path) == (
            links.Link(
                "beta",
                CODE_COMMIT.subject,
                CODE_COMMIT.authored_date,
                "alpha",
                ALPHA_COMMIT.subject,
                ALPHA_COMMIT.authored_date,
            ),
        )
        assert (
            "c1: code-only, open its PR by hand (llm-prompts-contribute skill)"
            in capsys.readouterr().out
        )

    def test_mixed_target_syncs_only_its_in_scope_commits(
        self, isolated_links_path: Path
    ) -> None:
        base, log, report = self._patched(beta_commits=[BETA_COMMIT, CODE_COMMIT])
        with (
            base,
            log,
            report,
            patch("llm_prompts.contribute.run_sync", return_value=0) as mock_sync,
        ):
            contribute.sync_targets(
                TWO_TARGETS, "me", False, None, None, ("a1", "b1", "c1")
            )

        assert mock_sync.call_args_list[1].args[-1] == ["b1"]

    @pytest.mark.parametrize(
        ("values", "message"),
        [
            (("zzz",), "zzz: not a local commit ahead of the base branch"),
            (("", "a1"), "empty commit value"),
        ],
    )
    def test_unresolvable_commit_prints_the_problem_and_runs_nothing(
        self,
        values: tuple[str, ...],
        message: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        base, log, report = self._patched()
        with base, log, report, patch("llm_prompts.contribute.run_sync") as mock_sync:
            status = contribute.sync_targets(
                TWO_TARGETS, "me", True, None, None, values
            )

        assert status == 1
        assert message in capsys.readouterr().out
        mock_sync.assert_not_called()

    def test_dry_run_writes_no_links_and_apply_writes_them_before_any_sync(
        self, isolated_links_path: Path
    ) -> None:
        existed_at_sync: list[bool] = []

        def record_sync(*args: Any) -> int:
            existed_at_sync.append(isolated_links_path.exists())
            return 0

        base, log, report = self._patched()
        with (
            base,
            log,
            report,
            patch(
                "llm_prompts.contribute.run_sync",
                side_effect=record_sync,
            ),
        ):
            contribute.sync_targets(TWO_TARGETS, "me", False, None, None, ("a1", "b1"))
            assert not isolated_links_path.exists()
            contribute.sync_targets(TWO_TARGETS, "me", True, None, None, ("a1", "b1"))

        assert existed_at_sync == [False, False, True, True]
        assert links.load_links(isolated_links_path) == (
            links.Link(
                "beta",
                BETA_COMMIT.subject,
                BETA_COMMIT.authored_date,
                "alpha",
                ALPHA_COMMIT.subject,
                ALPHA_COMMIT.authored_date,
            ),
        )

    def test_dependent_is_held_while_the_dependency_is_unpushed_and_later_syncs_too(
        self, isolated_links_path: Path
    ) -> None:
        _link_file(isolated_links_path, BETA_COMMIT, ALPHA_COMMIT)
        unpushed = {
            (ALPHA_COMMIT.subject, ALPHA_COMMIT.authored_date): links.Status(
                "local only", None, "tester/contribute/add-alpha-thing"
            )
        }
        base, log, report = self._patched(unpushed)
        with (
            base,
            log,
            report,
            patch("llm_prompts.contribute.run_sync", return_value=0) as mock_sync,
        ):
            contribute.sync_targets(TWO_TARGETS, "me", True, None, None)

        beta_call = mock_sync.call_args_list[1]
        assert beta_call.args[-1] == {
            "b1": "alpha: feat: add alpha thing is local only"
        }

    def test_dependent_is_released_once_the_dependency_is_pushed(
        self, isolated_links_path: Path
    ) -> None:
        _link_file(isolated_links_path, BETA_COMMIT, ALPHA_COMMIT)
        base, log, report = self._patched({})
        with (
            base,
            log,
            report,
            patch("llm_prompts.contribute.run_sync", return_value=0) as mock_sync,
        ):
            contribute.sync_targets(TWO_TARGETS, "me", True, None, None)

        assert mock_sync.call_args_list[1].args[-1] == ()

    def test_link_cycle_aborts_before_any_sync(
        self, isolated_links_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        links.save_links(
            isolated_links_path,
            (
                links.Link(
                    "alpha",
                    ALPHA_COMMIT.subject,
                    ALPHA_COMMIT.authored_date,
                    "beta",
                    BETA_COMMIT.subject,
                    BETA_COMMIT.authored_date,
                ),
            ),
        )
        base, log, report = self._patched()
        with base, log, report, patch("llm_prompts.contribute.run_sync") as mock_sync:
            status = contribute.sync_targets(
                TWO_TARGETS, "me", True, None, None, ("a1", "b1")
            )

        assert status == 1
        assert "depend on itself" in capsys.readouterr().out
        mock_sync.assert_not_called()


def _report_with(statuses: dict[tuple[str, str], links.Status]) -> contribute.Report:
    return contribute.Report(None, [], [], [], 0, statuses, {})


class TestListTargetsLinks:
    def test_single_target_list_also_reads_its_dependency_repo_and_writes_nothing(
        self, isolated_links_path: Path
    ) -> None:
        _link_file(isolated_links_path, BETA_COMMIT, ALPHA_COMMIT)
        before = isolated_links_path.read_text(encoding="utf-8")
        with patch(
            "llm_prompts.contribute.collect_report", return_value=_report_with({})
        ) as mock_collect:
            contribute.list_targets([TWO_TARGETS[1]], "me", lambda: TWO_TARGETS)

        assert {call.args[0] for call in mock_collect.call_args_list} == {
            Path("/tmp/alpha"),
            Path("/tmp/beta"),
        }
        assert isolated_links_path.read_text(encoding="utf-8") == before


class TestCrossRepoSync:
    def _remotes(
        self, fake: FakeSubprocess, tmp_path: Path
    ) -> tuple[ContributeRemote, ContributeRemote]:
        alpha_dir, beta_dir = tmp_path / "alpha", tmp_path / "beta"
        alpha = ContributeRemote(fake, repo=alpha_dir)
        beta = ContributeRemote(fake, repo=beta_dir)
        alpha.main(("a1", ALPHA_COMMIT.subject))
        beta.main(("b1", BETA_COMMIT.subject))
        for remote in (alpha, beta):
            remote.fake.on(
                "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
            )
            remote.fake.on("branch", "-D")
        return alpha, beta

    def _run(self, fake: FakeSubprocess, tmp_path: Path) -> tuple[int, list[str]]:
        targets = [
            ("beta", tmp_path / "beta", PROMPTS_PREFIX),
            ("alpha", tmp_path / "alpha", PROMPTS_PREFIX),
        ]
        picked = ApplyResult(outcome="picked", mode="new", paths=(), message="")
        with (
            patch("llm_prompts.contribute.apply_batch", return_value=picked),
            patch("llm_prompts.contribute.run_list", return_value=0),
        ):
            status = contribute.sync_targets(
                targets, "tester", True, None, None, ("a1", "b1")
            )
        pushed_repos = [Path(argv[2]).name for argv in fake.matching("push")]
        return status, pushed_repos

    def test_dependency_is_pushed_before_the_dependent(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        alpha, beta = self._remotes(fake_subprocess, tmp_path)

        def register_pushed_branch(argv: list[str], kwargs: dict[str, Any]) -> None:
            alpha.managed("add-alpha-thing", [("a1", ALPHA_COMMIT.subject)])

        alpha.fake.on("push", side_effect=register_pushed_branch)
        beta.fake.on("push")

        status, pushed_repos = self._run(fake_subprocess, tmp_path)

        assert status == 0
        assert pushed_repos == ["alpha", "beta"]

    def test_dependent_stays_held_when_the_dependency_push_is_rejected(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        alpha, beta = self._remotes(fake_subprocess, tmp_path)
        alpha.fake.on("push", returncode=1)
        beta.fake.on("push")

        status, pushed_repos = self._run(fake_subprocess, tmp_path)

        assert status == 1
        assert pushed_repos == ["alpha"]

    def test_list_shows_the_dependency_pr_url_beside_the_dependent_commit(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        isolated_links_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        alpha, _ = self._remotes(fake_subprocess, tmp_path)
        pr = Pr(5, "OPEN", "https://github.com/o/r/pull/5")
        alpha.managed("add-alpha-thing", [("a1", ALPHA_COMMIT.subject)], pr=pr)
        date = "2024-01-01T00:00:00+00:00"
        _link_file(
            isolated_links_path,
            BETA_COMMIT._replace(authored_date=date),
            ALPHA_COMMIT._replace(authored_date=date),
        )
        targets = [
            ("alpha", tmp_path / "alpha", PROMPTS_PREFIX),
            ("beta", tmp_path / "beta", PROMPTS_PREFIX),
        ]

        contribute.list_targets(targets, "tester")

        out = capsys.readouterr().out
        assert f"b1 feat: add beta thing\n        -> depends on {pr.url}\n" in out
        assert out.count("depends on") == 1

    def _list_with_dependent_pr_body(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        isolated_links_path: Path,
        capsys: pytest.CaptureFixture[str],
        body: str,
    ) -> str:
        alpha, beta = self._remotes(fake_subprocess, tmp_path)
        alpha_pr = Pr(5, "OPEN", "https://github.com/o/r/pull/5")
        alpha.managed("add-alpha-thing", [("a1", ALPHA_COMMIT.subject)], pr=alpha_pr)
        beta.managed(
            "add-beta-thing",
            [("b1", BETA_COMMIT.subject)],
            pr=Pr(6, "OPEN", "https://github.com/o/r/pull/6"),
        )
        beta.body(6, body)
        date = "2024-01-01T00:00:00+00:00"
        _link_file(
            isolated_links_path,
            BETA_COMMIT._replace(authored_date=date),
            ALPHA_COMMIT._replace(authored_date=date),
        )

        contribute.list_targets(
            [("beta", tmp_path / "beta", PROMPTS_PREFIX)],
            "tester",
            lambda: [("alpha", tmp_path / "alpha", PROMPTS_PREFIX)],
        )

        return capsys.readouterr().out

    def test_list_flags_a_dependency_url_missing_from_the_dependent_pr_body(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        isolated_links_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        out = self._list_with_dependent_pr_body(
            fake_subprocess, tmp_path, isolated_links_path, capsys, ""
        )

        assert "-> depends on https://github.com/o/r/pull/5 - missing from PR" in out

    def test_list_does_not_flag_a_dependency_url_present_in_the_dependent_pr_body(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        isolated_links_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        out = self._list_with_dependent_pr_body(
            fake_subprocess,
            tmp_path,
            isolated_links_path,
            capsys,
            "Depends on https://github.com/o/r/pull/5",
        )

        assert "-> depends on https://github.com/o/r/pull/5\n" in out
        assert "missing from PR" not in out

    def _code_only_alpha(self, fake_subprocess: FakeSubprocess, tmp_path: Path) -> Any:
        alpha, beta = self._remotes(fake_subprocess, tmp_path)
        alpha.main(("a1", ALPHA_COMMIT.subject), paths={"a1": (_OUT_SCOPE,)})
        return alpha, beta

    def _link_beta_to_alpha(self, path: Path) -> None:
        date = "2024-01-01T00:00:00+00:00"
        _link_file(
            path,
            BETA_COMMIT._replace(authored_date=date),
            ALPHA_COMMIT._replace(authored_date=date),
        )

    def _two_targets(self, tmp_path: Path) -> list[contribute.Target]:
        return [
            ("alpha", tmp_path / "alpha", PROMPTS_PREFIX),
            ("beta", tmp_path / "beta", PROMPTS_PREFIX),
        ]

    def test_code_only_dependency_without_a_remote_ref_holds_the_dependent(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        isolated_links_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        alpha, _ = self._code_only_alpha(fake_subprocess, tmp_path)
        alpha.fake.on("branch", "-r", "--contains", "a1", stdout="")
        self._link_beta_to_alpha(isolated_links_path)

        contribute.sync_targets(
            self._two_targets(tmp_path), "tester", False, None, None
        )

        assert (
            "b1: held while alpha: feat: add alpha thing is local only"
            in capsys.readouterr().out
        )

    def test_code_only_dependency_on_a_remote_branch_does_not_hold_and_lists_no_pr_yet(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        isolated_links_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        alpha, _ = self._code_only_alpha(fake_subprocess, tmp_path)
        alpha.fake.on("branch", "-r", "--contains", "a1", stdout="origin/feature\n")
        self._link_beta_to_alpha(isolated_links_path)
        targets = self._two_targets(tmp_path)

        contribute.sync_targets(targets, "tester", False, None, None)
        contribute.list_targets(targets, "tester")

        out = capsys.readouterr().out
        assert "held while" not in out
        assert "b1 feat: add beta thing\n        -> depends on alpha: no PR yet" in out

    def test_code_only_dependency_with_a_pr_shows_its_url_and_the_missing_flag(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        isolated_links_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        alpha, beta = self._code_only_alpha(fake_subprocess, tmp_path)
        alpha.unmanaged_pr("someone/alpha", 5, [("a1", ALPHA_COMMIT.subject)])
        beta.managed(
            "add-beta-thing",
            [("b1", BETA_COMMIT.subject)],
            pr=Pr(6, "OPEN", "https://github.com/o/r/pull/6"),
        )
        self._link_beta_to_alpha(isolated_links_path)

        contribute.list_targets(self._two_targets(tmp_path), "tester")

        assert (
            "-> depends on https://github.com/o/r/pull/5 - missing from PR"
            in capsys.readouterr().out
        )

    def test_manual_pr_dependent_line_shows_the_dependency_url(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        isolated_links_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        alpha, beta = self._remotes(fake_subprocess, tmp_path)
        beta.main(("b1", BETA_COMMIT.subject), paths={"b1": (_OUT_SCOPE,)})
        alpha.managed(
            "add-alpha-thing",
            [("a1", ALPHA_COMMIT.subject)],
            pr=Pr(5, "OPEN", "https://github.com/o/r/pull/5"),
        )
        self._link_beta_to_alpha(isolated_links_path)

        contribute.list_targets(self._two_targets(tmp_path), "tester")

        assert (
            "b1 feat: add beta thing [code]\n        -> depends on https://github.com/o/r/pull/5"
            in capsys.readouterr().out
        )

    def test_rewritten_sha_error_names_the_commit_that_replaced_it(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        alpha, _ = self._remotes(fake_subprocess, tmp_path)
        date = "2024-01-01T00:00:00+00:00"
        alpha.fake.on(
            "show",
            "-s",
            "--format=%aI%x09%s",
            "old1234",
            stdout=f"{date}\t{ALPHA_COMMIT.subject}\n",
        )

        status = contribute.sync_targets(
            [
                ("alpha", tmp_path / "alpha", PROMPTS_PREFIX),
                ("beta", tmp_path / "beta", PROMPTS_PREFIX),
            ],
            "tester",
            False,
            None,
            None,
            ("old1234", "b1"),
        )

        assert status == 1
        assert (
            "old1234: rewritten - alpha main now has a1 feat: add alpha thing"
            in capsys.readouterr().out
        )
