"""Tests for the contribute module (derived PR branch management)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import FakeSubprocess

from llm_prompts.contribute import (
    Commit,
    Group,
    Pr,
    apply_group,
    base_ref,
    branch_name,
    classify,
    find_blocking_commits,
    group_commits,
    is_conventional,
    open_prs,
    push_remote,
    remote_branches,
    run_list,
    run_sync,
    scope_commits,
    slug_for,
    stale_main_warning,
)

PROMPTS_PREFIX = "src/llm_prompts/prompts/"

_IN_SCOPE = f"{PROMPTS_PREFIX}shared/skills/foo/SKILL.md"
_OUT_SCOPE = "docs/notes.md"


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


class TestClassify:
    def _group(self, subject: str = "feat: add foo skill") -> Group:
        commit = Commit("s1", subject, (_IN_SCOPE,))
        slug = slug_for(subject)
        return Group((commit,), slug, branch_name("tester", slug), ())

    def test_matching_subjects_and_diff_is_not_stale(self) -> None:
        group = self._group()
        state = classify(
            group,
            group.branch,
            {group.branch},
            None,
            ("feat: add foo skill",),
            "diff-a",
            ("feat: add foo skill",),
            "diff-a",
        )
        assert state.stale is False
        assert state.pushed is True

    def test_differing_diff_is_stale(self) -> None:
        group = self._group()
        state = classify(
            group,
            group.branch,
            {group.branch},
            None,
            ("feat: add foo skill",),
            "diff-a",
            ("feat: add foo skill",),
            "diff-b",
        )
        assert state.stale is True

    def test_differing_subjects_is_stale(self) -> None:
        group = self._group()
        state = classify(
            group,
            group.branch,
            {group.branch},
            None,
            ("feat: add foo skill v2",),
            "diff-a",
            ("feat: add foo skill",),
            "diff-a",
        )
        assert state.stale is True

    def test_branch_not_on_remote_is_new(self) -> None:
        group = self._group()
        state = classify(
            group,
            group.branch,
            set(),
            None,
            ("feat: add foo skill",),
            "diff-a",
            (),
            "",
        )
        assert state.pushed is False
        assert state.pr is None

    def test_open_pr_and_current_content_is_ok(self) -> None:
        group = self._group()
        pr = Pr(12, "OPEN", "https://github.com/o/r/pull/12")
        state = classify(
            group,
            group.branch,
            {group.branch},
            pr,
            ("feat: add foo skill",),
            "diff-a",
            ("feat: add foo skill",),
            "diff-a",
        )
        assert state.pushed is True
        assert state.stale is False
        assert state.pr == pr

    def test_no_group_with_open_pr_is_orphan(self) -> None:
        pr = Pr(12, "OPEN", "https://github.com/o/r/pull/12")
        state = classify(
            None,
            "tester/removed-skill",
            {"tester/removed-skill"},
            pr,
            (),
            "",
            (),
            "",
        )
        assert state.group is None
        assert state.pr == pr

    @pytest.mark.parametrize("pr_state", ["MERGED", "CLOSED"])
    def test_no_group_with_merged_or_closed_pr_is_orphan(self, pr_state: str) -> None:
        pr = Pr(9, pr_state, "https://github.com/o/r/pull/9")
        state = classify(
            None,
            "tester/old-fix",
            {"tester/old-fix"},
            pr,
            (),
            "",
            (),
            "",
        )
        assert state.group is None
        assert state.pr == pr


class TestScopeCommits:
    def test_excludes_out_of_scope_and_includes_mixed_scope(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "log",
            "--format=%H%x09%s",
            stdout=fake_subprocess.sha_subjects(
                ("aaa111", "feat: add foo skill"),
                ("bbb222", "docs: unrelated notes"),
                ("ccc333", "fix(rules): mixed change"),
            ),
        )
        fake_subprocess.on_match(
            lambda argv: "show" in argv and "aaa111" in argv,
            stdout=f"{_IN_SCOPE}\n",
        )
        fake_subprocess.on_match(
            lambda argv: "show" in argv and "bbb222" in argv,
            stdout=f"{_OUT_SCOPE}\n",
        )
        fake_subprocess.on_match(
            lambda argv: "show" in argv and "ccc333" in argv,
            stdout=f"{_IN_SCOPE}\n{_OUT_SCOPE}\n",
        )

        commits = scope_commits(tmp_path, "origin/main", PROMPTS_PREFIX)

        assert [c.sha for c in commits] == ["aaa111", "ccc333"]
        assert commits[0].paths == (_IN_SCOPE,)
        assert commits[1].paths == (_IN_SCOPE, _OUT_SCOPE)


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


class TestOpenPrs:
    def test_parses_prs_keyed_by_branch(
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
                        "headRefName": "tester/old-fix",
                    },
                ]
            ),
        )
        result = open_prs(tmp_path)
        assert result == {
            "tester/add-foo-skill": Pr(12, "OPEN", "https://github.com/o/r/pull/12"),
            "tester/old-fix": Pr(9, "MERGED", "https://github.com/o/r/pull/9"),
        }
        _, kwargs = fake_subprocess.calls[-1]
        assert kwargs["cwd"] == tmp_path


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
    def test_dry_run_never_pushes_or_cherry_picks(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")

        run_sync(tmp_path, "tester", PROMPTS_PREFIX, False, None, None)

        assert fake_subprocess.matching("push") == []
        assert fake_subprocess.matching("cherry-pick") == []

    def test_dry_run_previews_orphan_cleanup(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on(
            "ls-remote",
            "--heads",
            "origin",
            stdout="abc123\trefs/heads/tester/orphan-branch\n",
        )
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")

        with patch("llm_prompts.contribute.run_list") as mock_run_list:
            result = run_sync(tmp_path, "tester", PROMPTS_PREFIX, False, None, None)

        out = capsys.readouterr().out
        assert "tester/orphan-branch: would delete (orphan, no PR)" in out
        assert fake_subprocess.matching("push", "origin", "--delete") == []
        mock_run_list.assert_not_called()
        assert result == 0


class TestOrphanScopeFilter:
    def test_pushed_branch_touching_only_out_of_scope_paths_is_not_orphan(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on(
            "ls-remote",
            "--heads",
            "origin",
            stdout="abc123\trefs/heads/tester/unrelated-pr\n",
        )
        fake_subprocess.on(
            "gh",
            "pr",
            "list",
            stdout=json.dumps(
                [
                    {
                        "number": 31,
                        "state": "OPEN",
                        "url": "https://github.com/o/r/pull/31",
                        "headRefName": "tester/unrelated-pr",
                    }
                ]
            ),
        )
        fake_subprocess.on("diff", "--name-only", stdout=f"{_OUT_SCOPE}\n")

        result = run_list(tmp_path, "tester", PROMPTS_PREFIX)

        out = capsys.readouterr().out
        assert "tester/unrelated-pr" not in out
        assert result == 0


class TestRunListStaleMainWarning:
    def test_warns_when_a_commit_is_squash_merged(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on("cherry", "origin/main", "main", stdout="-abc123 old\n")

        result = run_list(tmp_path, "tester", PROMPTS_PREFIX)

        out = capsys.readouterr().out
        assert "git fetch origin main && git rebase origin/main" in out
        assert result == 0

    def test_no_warning_without_a_stale_cherry_line(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")

        run_list(tmp_path, "tester", PROMPTS_PREFIX)

        out = capsys.readouterr().out
        assert "git fetch" not in out

    def test_fetch_happens_before_cherry(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on("cherry", "origin/main", "main", stdout="-abc123 old\n")

        run_list(tmp_path, "tester", PROMPTS_PREFIX)

        verbs = fake_subprocess.verbs
        assert verbs.index("fetch --quiet origin main") < verbs.index(
            "cherry origin/main main"
        )


class TestRunSyncStaleMainWarning:
    def test_warns_when_a_commit_is_squash_merged(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on("cherry", "origin/main", "main", stdout="-abc123 old\n")

        run_sync(tmp_path, "tester", PROMPTS_PREFIX, False, None, None)

        out = capsys.readouterr().out
        assert "git fetch origin main && git rebase origin/main" in out

    def test_no_warning_without_a_stale_cherry_line(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")

        run_sync(tmp_path, "tester", PROMPTS_PREFIX, False, None, None)

        out = capsys.readouterr().out
        assert "git fetch" not in out

    def test_fetch_happens_before_cherry(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on("cherry", "origin/main", "main", stdout="-abc123 old\n")

        run_sync(tmp_path, "tester", PROMPTS_PREFIX, False, None, None)

        verbs = fake_subprocess.verbs
        assert verbs.index("fetch --quiet origin main") < verbs.index(
            "cherry origin/main main"
        )


class TestRunSyncApplyConflict:
    def test_conflict_names_the_blocking_commit(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        path = f"{PROMPTS_PREFIX}shared/skills/foo/SKILL.md"
        fake_subprocess.on(
            "log",
            "--format=%H%x09%s",
            stdout=fake_subprocess.sha_subjects(
                ("aaa111", "feat: add foo skill"),
                ("bbb222", "feat: tweak foo again"),
            ),
        )
        fake_subprocess.on_match(lambda argv: "show" in argv, stdout=f"{path}\n")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )

        with patch(
            "llm_prompts.contribute.apply_group",
            side_effect=[
                ("picked", (), ""),
                (
                    "conflict",
                    (path,),
                    "error: could not apply bbb222... feat: tweak foo again",
                ),
            ],
        ):
            run_sync(tmp_path, "tester", PROMPTS_PREFIX, True, None, None)

        out = capsys.readouterr().out
        conflict_line = next(
            line for line in out.splitlines() if "tweak-foo-again" in line
        )
        assert "conflict" in conflict_line
        assert "depends on unmerged commit(s) aaa111" in conflict_line
        assert "feat: add foo skill" in conflict_line

    def test_conflict_without_a_blocker_has_no_suggestion(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        path = f"{PROMPTS_PREFIX}shared/skills/foo/SKILL.md"
        fake_subprocess.on(
            "log",
            "--format=%H%x09%s",
            stdout=fake_subprocess.sha_subjects(("bbb222", "feat: tweak foo again")),
        )
        fake_subprocess.on_match(lambda argv: "show" in argv, stdout=f"{path}\n")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )

        with patch(
            "llm_prompts.contribute.apply_group",
            return_value=("conflict", (path,), "error: could not apply bbb222..."),
        ):
            run_sync(tmp_path, "tester", PROMPTS_PREFIX, True, None, None)

        out = capsys.readouterr().out
        conflict_line = next(
            line for line in out.splitlines() if "tweak-foo-again" in line
        )
        assert "conflict" in conflict_line
        assert "depends on" not in conflict_line


class TestStalenessIntegration:
    """Exercise the staleness mechanism against a real git repo, no network."""

    def _git(self, repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def test_reword_of_source_commit_flips_staleness(self, tmp_path: Path) -> None:
        repo = tmp_path
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.email", "a@b.c")
        self._git(repo, "config", "user.name", "Test")
        (repo / "README.md").write_text("base\n")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-q", "-m", "chore: base")

        skill_dir = (
            repo / "src" / "llm_prompts" / "prompts" / "shared" / "skills" / "demo"
        )
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("hello\n")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-q", "-m", "feat: add demo skill")
        main_sha = self._git(repo, "rev-parse", "HEAD").strip()
        rel_path = str((skill_dir / "SKILL.md").relative_to(repo))

        commit = Commit(main_sha, "feat: add demo skill", (rel_path,))
        slug = slug_for(commit.subject)
        branch = branch_name("tester", slug)
        group = Group((commit,), slug, branch, ())

        apply_group(repo, group, "main~1", PROMPTS_PREFIX)

        branch_diff = self._git(repo, "diff", "main~1", branch)
        main_diff = self._git(repo, "diff", "main~1", "main")
        assert branch_diff == main_diff

        fresh_state = classify(
            group,
            branch,
            {branch},
            None,
            (commit.subject,),
            main_diff,
            (commit.subject,),
            branch_diff,
        )
        assert fresh_state.stale is False

        self._git(repo, "commit", "--amend", "-q", "-m", "feat: add demo skill v2")
        reworded_diff = self._git(repo, "diff", "main~1", "main")
        assert reworded_diff == main_diff

        stale_state = classify(
            group,
            branch,
            {branch},
            None,
            ("feat: add demo skill v2",),
            reworded_diff,
            (commit.subject,),
            branch_diff,
        )
        assert stale_state.stale is True


class TestApplyGroupConflict:
    def _register_conflicting_cherry_pick(
        self, fake_subprocess: FakeSubprocess, *, branch_exists: bool
    ) -> None:
        fake_subprocess.on(
            "branch", "--list", stdout="alexfayers/tweak-foo\n" if branch_exists else ""
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

    def test_conflicting_cherry_pick_returns_detail(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        self._register_conflicting_cherry_pick(fake_subprocess, branch_exists=False)

        commit = Commit("aaa111", "feat: main change", ("file.txt",))
        slug = slug_for(commit.subject)
        branch = branch_name("tester", slug)
        group = Group((commit,), slug, branch, ())

        outcome, paths, message = apply_group(tmp_path, group, "alt", PROMPTS_PREFIX)

        assert outcome == "conflict"
        assert paths == ("file.txt",)
        assert message == "error: could not apply aaa111... feat: main change"
        assert fake_subprocess.matching("branch", "-D") == []

    def test_stale_branch_is_deleted_before_reapplying(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        self._register_conflicting_cherry_pick(fake_subprocess, branch_exists=True)

        commit = Commit("aaa111", "feat: main change", ("file.txt",))
        slug = slug_for(commit.subject)
        branch = branch_name("tester", slug)
        group = Group((commit,), slug, branch, ())

        outcome, _paths, _message = apply_group(tmp_path, group, "alt", PROMPTS_PREFIX)

        assert outcome == "conflict"
        assert fake_subprocess.matching("branch", "-D") != []


class TestApplyGroupOversize:
    def test_failed_size_check_returns_its_report(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("branch", "--list", stdout="")
        fake_subprocess.on("worktree", "add")
        fake_subprocess.on("switch", "-c")
        fake_subprocess.on("cherry-pick")
        fake_subprocess.on("worktree", "remove")

        commit = Commit("aaa111", "feat: main change", (f"{PROMPTS_PREFIX}foo.md",))
        slug = slug_for(commit.subject)
        branch = branch_name("tester", slug)
        group = Group((commit,), slug, branch, ())

        from llm_prompts.size_guard import CheckResult

        with patch(
            "llm_prompts.contribute.check",
            return_value=CheckResult(
                passed=False, artifacts=[], violations=[], report="too big"
            ),
        ):
            outcome, paths, message = apply_group(
                tmp_path, group, "alt", PROMPTS_PREFIX
            )

        assert outcome == "oversize"
        assert paths == ()
        assert message == "too big"

    def test_passed_size_check_returns_picked(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("branch", "--list", stdout="")
        fake_subprocess.on("worktree", "add")
        fake_subprocess.on("switch", "-c")
        fake_subprocess.on("cherry-pick")
        fake_subprocess.on("worktree", "remove")

        commit = Commit("aaa111", "feat: main change", (f"{PROMPTS_PREFIX}foo.md",))
        slug = slug_for(commit.subject)
        branch = branch_name("tester", slug)
        group = Group((commit,), slug, branch, ())

        from llm_prompts.size_guard import CheckResult

        with patch(
            "llm_prompts.contribute.check",
            return_value=CheckResult(
                passed=True, artifacts=[], violations=[], report=""
            ),
        ):
            outcome, paths, message = apply_group(
                tmp_path, group, "alt", PROMPTS_PREFIX
            )

        assert outcome == "picked"
        assert paths == ()
        assert message == ""


class TestRunSyncApplyOversize:
    def test_oversize_is_reported_and_not_pushed_but_others_still_push(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on(
            "log",
            "--format=%H%x09%s",
            stdout=fake_subprocess.sha_subjects(
                ("aaa111", "feat: add foo skill"),
                ("bbb222", "feat: add bar skill"),
            ),
        )
        fake_subprocess.on_match(
            lambda argv: "show" in argv, stdout=f"{PROMPTS_PREFIX}foo.md\n"
        )
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        fake_subprocess.on("push")

        with patch(
            "llm_prompts.contribute.apply_group",
            side_effect=[
                ("oversize", (), "too big"),
                ("picked", (), ""),
            ],
        ):
            result = run_sync(tmp_path, "tester", PROMPTS_PREFIX, True, None, None)

        out = capsys.readouterr().out
        assert "size check failed" in out
        assert "too big" in out
        assert result == 1
        assert len(fake_subprocess.matching("push", "--force-with-lease")) == 1


class TestRunSyncApplyPickedCleanup:
    def test_successful_push_deletes_the_local_branch(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "log",
            "--format=%H%x09%s",
            stdout=fake_subprocess.sha_subjects(("aaa111", "feat: add foo skill")),
        )
        fake_subprocess.on_match(
            lambda argv: "show" in argv, stdout=f"{PROMPTS_PREFIX}foo.md\n"
        )
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        fake_subprocess.on("push")
        fake_subprocess.on("branch", "-D")

        with patch(
            "llm_prompts.contribute.apply_group",
            return_value=("picked", (), ""),
        ):
            result = run_sync(tmp_path, "tester", PROMPTS_PREFIX, True, None, None)

        assert result == 0
        assert fake_subprocess.matching("branch", "-D") != []


class TestRunSyncApplyListsAfter:
    def test_apply_prints_list_after_syncing_without_affecting_exit_code(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on(
            "log",
            "--format=%H%x09%s",
            stdout=fake_subprocess.sha_subjects(("aaa111", "feat: add foo skill")),
        )
        fake_subprocess.on_match(
            lambda argv: "show" in argv, stdout=f"{PROMPTS_PREFIX}foo.md\n"
        )
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        fake_subprocess.on("push")

        with (
            patch(
                "llm_prompts.contribute.apply_group",
                return_value=("picked", (), ""),
            ),
            patch(
                "llm_prompts.contribute.run_list",
                side_effect=lambda repo, login, prefix: print("LIST-CALLED") or 1,
            ) as mock_run_list,
        ):
            result = run_sync(tmp_path, "tester", PROMPTS_PREFIX, True, None, None)

        out = capsys.readouterr().out
        pushed_index = out.index("pushed")
        list_index = out.index("LIST-CALLED")
        assert pushed_index < list_index
        assert out[pushed_index:list_index].count("\n\n") >= 1
        mock_run_list.assert_called_once_with(tmp_path, "tester", PROMPTS_PREFIX)
        assert result == 0

    def test_dry_run_does_not_print_the_list(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")

        with patch("llm_prompts.contribute.run_list") as mock_run_list:
            run_sync(tmp_path, "tester", PROMPTS_PREFIX, False, None, None)

        mock_run_list.assert_not_called()

    def test_cleanup_does_not_print_the_list(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on("ls-remote", "--heads", "origin", stdout="")
        fake_subprocess.on("gh", "pr", "list", stdout="[]")

        with patch("llm_prompts.contribute.run_list") as mock_run_list:
            run_sync(
                tmp_path, "tester", PROMPTS_PREFIX, True, None, "nonexistent-branch"
            )

        mock_run_list.assert_not_called()


class TestRunSyncApplyOrphanCleanup:
    def test_deletes_orphan_branch_with_no_pr(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        fake_subprocess.on(
            "ls-remote",
            "--heads",
            "origin",
            stdout="abc123\trefs/heads/tester/orphan-branch\n",
        )
        fake_subprocess.on("gh", "pr", "list", stdout="[]")
        fake_subprocess.on("push")
        fake_subprocess.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")

        with patch("llm_prompts.contribute.run_list", return_value=0):
            result = run_sync(tmp_path, "tester", PROMPTS_PREFIX, True, None, None)

        out = capsys.readouterr().out
        assert "tester/orphan-branch: deleted (orphan, no PR)" in out
        assert result == 0
        delete_calls = fake_subprocess.matching("push", "origin", "--delete")
        assert any("tester/orphan-branch" in call for call in delete_calls)

    def test_leaves_orphan_branch_with_a_pr_untouched(
        self,
        fake_subprocess: FakeSubprocess,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake_subprocess.on("log", "--format=%H%x09%s", stdout="")
        fake_subprocess.on("remote", stdout="origin\n")
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        fake_subprocess.on(
            "ls-remote",
            "--heads",
            "origin",
            stdout="abc123\trefs/heads/tester/orphan-branch\n",
        )
        fake_subprocess.on(
            "gh",
            "pr",
            "list",
            stdout=json.dumps(
                [
                    {
                        "number": 5,
                        "state": "OPEN",
                        "url": "https://github.com/o/r/pull/5",
                        "headRefName": "tester/orphan-branch",
                    }
                ]
            ),
        )
        fake_subprocess.on("diff", "--name-only", stdout=f"{_IN_SCOPE}\n")

        with patch("llm_prompts.contribute.run_list", return_value=0):
            result = run_sync(tmp_path, "tester", PROMPTS_PREFIX, True, None, None)

        out = capsys.readouterr().out
        assert "deleted" not in out
        assert result == 0
        assert fake_subprocess.matching("push", "origin", "--delete") == []


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
