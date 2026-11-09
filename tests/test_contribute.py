"""Tests for the contribute module (derived PR branch management)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from conftest import ContributeRemote, FakeGitHub, FakeSubprocess

from llm_prompts import contribute, github_api
from llm_prompts.contribute import (
    Commit,
    Pr,
    base_ref,
    fetch_base,
    open_prs,
    pr_body,
    pr_template,
    pr_title,
    push_remote,
    rewrite_what,
    stale_main_warning,
)

PROMPTS_PREFIX = "src/llm_prompts/prompts/"

_IN_SCOPE = f"{PROMPTS_PREFIX}shared/skills/foo/SKILL.md"
_OUT_SCOPE = "docs/notes.md"


@pytest.fixture(autouse=True)
def _gh_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to a host with gh installed, and start with no cached GitHub lookups."""
    monkeypatch.setattr(contribute, "_gh_installed", lambda: True)
    for cached in (github_api.token, github_api.login, github_api.base_repo):
        cached.cache_clear()


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
            "number,state,url,headRefName,isDraft,reviewDecision,body,headRefOid,baseRefName,title",
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


class TestOpenPrHeads:
    JSON_FIELDS = (
        "number,state,url,headRefName,isDraft,reviewDecision,body,"
        "headRefOid,baseRefName,title"
    )

    def _list(self, fake: FakeSubprocess, extra: dict[str, Any]) -> None:
        fake.on(
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--author",
            "@me",
            "--json",
            self.JSON_FIELDS,
            stdout=json.dumps(
                [
                    {
                        "number": 1,
                        "state": "OPEN",
                        "url": "https://x/pull/1",
                        "headRefName": "someone/a",
                        "isDraft": False,
                        "reviewDecision": "",
                        **extra,
                    }
                ]
            ),
        )
        fake.on("gh", "pr", "view", stdout=json.dumps({"commits": []}))

    def test_reads_head_sha_and_base_branch(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        self._list(fake_subprocess, {"headRefOid": "abc", "baseRefName": "main"})

        prs, _ = open_prs(tmp_path)

        assert (prs[0].head_sha, prs[0].base_branch) == ("abc", "main")

    def test_missing_head_sha_and_base_branch_map_to_empty(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        self._list(fake_subprocess, {"headRefOid": None})

        prs, _ = open_prs(tmp_path)

        assert (prs[0].head_sha, prs[0].base_branch) == ("", "")

    def test_reads_title(self, fake_subprocess: FakeSubprocess, tmp_path: Path) -> None:
        self._list(fake_subprocess, {"title": "docs: note"})

        prs, _ = open_prs(tmp_path)

        assert prs[0].title == "docs: note"

    def test_missing_title_maps_to_empty(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        self._list(fake_subprocess, {"title": None})

        prs, _ = open_prs(tmp_path)

        assert prs[0].title == ""


def _open_pr(
    number: int, head_sha: str = "", base_branch: str = "main"
) -> contribute.OpenPr:
    return contribute.OpenPr(
        pr=Pr(number, "OPEN", f"https://github.com/octo/widgets/pull/{number}"),
        branch=f"someone/pr-{number}",
        review_decision="",
        commits=(),
        head_sha=head_sha,
        base_branch=base_branch,
    )


class TestBehindPrs:
    def _ancestry(self, fake: FakeSubprocess, *, current: set[str]) -> None:
        def side_effect(
            argv: list[str], kwargs: dict[str, Any]
        ) -> subprocess.CompletedProcess[str] | None:
            if argv[-1] not in current:
                raise subprocess.CalledProcessError(1, argv, stderr="")
            return None

        fake.on("merge-base", "--is-ancestor", side_effect=side_effect)

    def test_lists_prs_whose_head_lacks_base_ordered_by_number(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        self._ancestry(fake_subprocess, current={"s2"})
        prs = [_open_pr(9, "s9"), _open_pr(2, "s2"), _open_pr(5, "s5")]

        behind = contribute.behind_prs(tmp_path, "origin/main", "origin", prs)

        assert [open_pr.pr.number for open_pr in behind] == [5, 9]

    def test_fetches_every_candidate_head_in_one_call(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        self._ancestry(fake_subprocess, current=set())

        contribute.behind_prs(
            tmp_path, "origin/main", "origin", [_open_pr(1, "s1"), _open_pr(2, "s2")]
        )

        fetches = fake_subprocess.matching("fetch")
        assert len(fetches) == 1
        assert fetches[0][-4:] == ["--quiet", "origin", "s1", "s2"]

    def test_skips_prs_not_based_on_main_and_fetches_nothing_without_candidates(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        prs = [_open_pr(1, "s1", "release"), _open_pr(2, "")]

        behind = contribute.behind_prs(tmp_path, "origin/main", "origin", prs)

        assert behind == []
        assert fake_subprocess.commands == []

    def test_unexpected_git_failure_propagates(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "merge-base", "--is-ancestor", returncode=128, stderr="fatal: bad object"
        )

        with pytest.raises(subprocess.CalledProcessError):
            contribute.behind_prs(
                tmp_path, "origin/main", "origin", [_open_pr(1, "s1")]
            )


class TestRunUpdate:
    def _behind(
        self, contribute_remote: ContributeRemote, *numbers: int, current: int = 0
    ) -> None:
        contribute_remote.main()
        for number in (*numbers, *([current] if current else [])):
            contribute_remote.unmanaged_pr(f"someone/{number}", number, [])
            contribute_remote.head(number, f"s{number}")

        def side_effect(
            argv: list[str], kwargs: dict[str, Any]
        ) -> subprocess.CompletedProcess[str] | None:
            if argv[-1] == f"s{current}":
                return None
            raise subprocess.CalledProcessError(1, argv, stderr="")

        contribute_remote.fake.on(
            "merge-base", "--is-ancestor", side_effect=side_effect
        )

    def _run(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        apply: bool,
        numbers: tuple[int, ...] = (),
    ) -> tuple[int, str]:
        status = contribute.run_update(tmp_path, apply, numbers)
        return status, capsys.readouterr().out

    def test_dry_run_prints_the_command_and_updates_nothing(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._behind(contribute_remote, 3)

        status, out = self._run(contribute_remote, tmp_path, capsys, False)

        assert status == 0
        assert "gh pr update-branch 3 --rebase" in out
        assert contribute_remote.fake.matching("gh", "pr", "update-branch") == []

    def test_apply_rebases_each_behind_pr(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._behind(contribute_remote, 3, 4, current=5)

        status, out = self._run(contribute_remote, tmp_path, capsys, True)

        updates = contribute_remote.fake.matching("gh", "pr", "update-branch")
        assert sorted(argv[3] for argv in updates) == ["3", "4"]
        assert all(argv[-1] == "--rebase" for argv in updates)
        assert "someone/3: rebased onto main https://github.com/o/r/pull/3" in out
        assert status == 0

    def test_one_failure_is_reported_while_the_others_still_run(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._behind(contribute_remote, 3, 4)
        contribute_remote.fake.on(
            "gh", "pr", "update-branch", "3", returncode=1, stderr="conflict\n"
        )

        status, out = self._run(contribute_remote, tmp_path, capsys, True)

        assert "someone/3: not updated (conflict)" in out
        assert "someone/4: rebased onto main" in out
        assert status == 1

    def test_unknown_pr_number_fails(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._behind(contribute_remote, 3)

        status, out = self._run(contribute_remote, tmp_path, capsys, True, (99,))

        assert "#99: not one of your open PRs" in out
        assert contribute_remote.fake.matching("gh", "pr", "update-branch") == []
        assert status == 1

    def test_named_pr_that_is_current_is_reported_up_to_date(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._behind(contribute_remote, 3, current=5)

        status, out = self._run(contribute_remote, tmp_path, capsys, True, (5,))

        assert "#5: already up to date with main" in out
        assert contribute_remote.fake.matching("gh", "pr", "update-branch") == []
        assert status == 0

    def test_named_pr_restricts_the_update(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._behind(contribute_remote, 3, 4)

        self._run(contribute_remote, tmp_path, capsys, True, (4,))

        updates = contribute_remote.fake.matching("gh", "pr", "update-branch")
        assert [argv[3] for argv in updates] == ["4"]

    def test_nothing_behind_says_so(
        self,
        contribute_remote: ContributeRemote,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._behind(contribute_remote, current=5)

        status, out = self._run(contribute_remote, tmp_path, capsys, True)

        assert "nothing behind main" in out
        assert status == 0


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
        assert stale_main_warning(tmp_path, "origin/main") is None

    def test_plus_only_output_returns_none(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("cherry", "origin/main", "main", stdout="+abc123 new\n")
        assert stale_main_warning(tmp_path, "origin/main") is None

    def test_minus_line_warns_with_the_fix_command(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("cherry", "origin/main", "main", stdout="-abc123 old\n")
        warning = stale_main_warning(tmp_path, "origin/main")
        assert warning is not None
        assert "fix with: llm-prompts update" in warning

    def test_mixed_minus_and_plus_lines_still_warns(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "cherry", "origin/main", "main", stdout="-abc123 old\n+def456 new\n"
        )
        assert stale_main_warning(tmp_path, "origin/main") is not None

    def test_names_the_given_base_not_origin(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("cherry", "upstream/main", "main", stdout="-abc123 old\n")
        warning = stale_main_warning(tmp_path, "upstream/main")
        assert warning is not None
        assert "upstream/main" in warning
        assert "origin" not in warning


class TestPushRemote:
    def test_admin_permission_uses_origin_without_forking(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "ADMIN"})
        )
        result = push_remote(tmp_path)
        assert result == ("origin", False)
        assert fake_subprocess.matching("gh", "repo", "fork") == []

    def test_read_permission_forks_before_using_origin(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "READ"})
        )
        fake_subprocess.on("gh", "repo", "fork", "--remote")
        result = push_remote(tmp_path)
        assert result == ("origin", True)
        assert fake_subprocess.matching("gh", "repo", "fork") != []

    def test_read_permission_only_reports_the_fork_when_told_not_to_fork(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "gh", "repo", "view", stdout=json.dumps({"viewerPermission": "READ"})
        )
        assert push_remote(tmp_path, fork=False) == ("origin", True)
        assert fake_subprocess.matching("gh", "repo", "fork") == []


class TestPrStatesWithoutGh:
    def test_one_graphql_query_returns_each_found_pr(
        self, fake_github: FakeGitHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(contribute, "_gh_installed", lambda: False)
        monkeypatch.setattr(github_api, "base_repo", lambda repo: ("o", "r"))
        node = {
            "state": "OPEN",
            "isDraft": True,
            "headRefOid": "abc",
            "title": "t",
            "body": None,
            "headRefName": "feat/a",
        }
        fake_github.on_graphql(
            "pullRequest(", {"data": {"repository": {"pr3": node, "pr4": None}}}
        )

        assert contribute.pr_states(tmp_path, [3, 4]) == {
            3: contribute.PrState("OPEN", True, "abc", "t", "", "feat/a")
        }
        assert len(fake_github.graphql_variables("pullRequest(")) == 1


def test_update_targets_runs_each_target_in_order_and_returns_max_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    targets = [("alpha", Path("/repo-a"), "feat"), ("beta", Path("/repo-b"), "fix")]
    seen: list[Path] = []

    def fake_update(repo: Path, *args: Any) -> int:
        seen.append(repo)
        return 1 if repo == Path("/repo-a") else 0

    with patch("llm_prompts.contribute.run_update", side_effect=fake_update) as mock:
        status = contribute.update_targets(targets, True, (3,))

    assert status == 1
    assert seen == [Path("/repo-a"), Path("/repo-b")]
    assert mock.call_args.args[1:] == (True, (3,))
    assert capsys.readouterr().out == "[alpha]\n\n[beta]\n\n"


class TestPrTitle:
    def test_single_commit_uses_its_subject(self) -> None:
        assert pr_title([Commit("a1", "feat: add foo", ())]) == "feat: add foo"

    def test_extra_commits_are_counted(self) -> None:
        commits = [
            Commit("a1", "feat: add foo", ()),
            Commit("a2", "feat: add bar", ()),
            Commit("a3", "feat: add baz", ()),
        ]
        assert pr_title(commits) == "feat: add foo (+2 more)"


_TEMPLATE = (
    "## What\n\n<!-- What changed. -->\n\n"
    "## Why\n\n<!-- Why it changed. -->\n\n"
    "## Testing\n\n<!-- How tested. -->\n\n"
    "## Checks\n\n- [ ] Within budget\n"
)


class TestPrBody:
    def test_commit_subjects_listed_directly_under_what(self) -> None:
        commits = [Commit("a1", "feat: add foo", ()), Commit("a2", "fix: bar", ())]
        assert pr_body(_TEMPLATE, commits) == (
            "## What\n\n- feat: add foo\n- fix: bar\n\n"
            "## Why\n\n## Testing\n\n## Checks\n\n- [ ] Within budget\n"
        )

    def test_placeholder_comments_are_removed_and_the_rest_kept(self) -> None:
        body = pr_body(_TEMPLATE, [Commit("a1", "feat: add foo", ())])
        assert "<!--" not in body
        for kept in ("## Why", "## Testing", "## Checks", "- [ ] Within budget"):
            assert kept in body

    def test_template_without_what_heading_gets_one_prepended(self) -> None:
        commits = [Commit("a1", "feat: add foo", ())]
        template = "## Why\n\n<!-- Why. -->\n"
        assert pr_body(template, commits) == "## What\n\n- feat: add foo\n\n## Why\n\n"

    def test_what_section_lists_every_commit(self) -> None:
        commits = [Commit(f"a{i}", f"feat: add thing{i}", ()) for i in range(1, 6)]
        subjects = "\n".join(f"- feat: add thing{i}" for i in range(1, 6))
        body = pr_body(_TEMPLATE, commits)
        assert body.startswith(f"## What\n\n{subjects}\n\n## Why")

    def test_depends_on_lines_follow_the_body(self) -> None:
        commits = [Commit(f"a{i}", f"feat: add thing{i}", ()) for i in range(1, 3)]
        body = pr_body(_TEMPLATE, commits, ["https://example.test/pr/1"])
        assert body.startswith(
            "## What\n\n- feat: add thing1\n- feat: add thing2\n\n## Why"
        )
        assert body.endswith("\n\nDepends on https://example.test/pr/1\n")

    def test_depends_on_lines_go_under_the_dependencies_heading(self) -> None:
        template = "## What\n\n## Dependencies\n\nHand note.\n\n## Issues\n"
        body = pr_body(template, [Commit("a1", "feat: a", ())], ["o/r#1", "o/r#2"])
        assert body == (
            "## What\n\n- feat: a\n\n## Dependencies\n\nHand note.\n"
            "Depends on o/r#1\nDepends on o/r#2\n\n## Issues\n"
        )


_EDITED_BODY = (
    "## What\n\n- feat: add foo\n\n"
    "## Why\n\nBecause of reasons.\n\n"
    "## Testing\n\nRan it.\n\n"
    "## Checks\n\n- [x] Within budget\n"
)


class TestRewriteWhat:
    def test_generated_run_is_replaced_and_other_sections_are_untouched(
        self,
    ) -> None:
        commits = [Commit("a1", "feat: add foo", ()), Commit("a2", "fix: bar", ())]
        assert rewrite_what(_EDITED_BODY, commits) == _EDITED_BODY.replace(
            "- feat: add foo\n", "- feat: add foo\n- fix: bar\n", 1
        )

    def test_user_prose_is_kept_and_pasted_duplicate_depends_line_dropped(
        self,
    ) -> None:
        commits = [Commit("a1", "feat: add foo", ())]
        body = (
            "## What\n\n- feat: add foo\n\nSee the thread.\n"
            "Depends on https://example.test/pr/1\n"
            "Depends on https://example.test/pr/2\n\n## Why\n\nx\n"
        )
        assert rewrite_what(body, commits, ["https://example.test/pr/1"]) == (
            "## What\n\n- feat: add foo\n\nSee the thread.\n"
            "Depends on https://example.test/pr/2\n\n## Why\n\nx\n\n"
            "Depends on https://example.test/pr/1\n"
        )

    def test_top_of_what_depends_lines_move_to_the_bottom(self) -> None:
        commits = [Commit("a1", "feat: add foo", ())]
        url = "https://example.test/pr/1"
        body = f"## What\n\nDepends on {url}\n- feat: add foo\n\n## Why\n\nx\n"
        assert rewrite_what(body, commits, [url]) == (
            f"## What\n\n- feat: add foo\n\n## Why\n\nx\n\nDepends on {url}\n"
        )

    def test_top_of_what_hand_written_depends_line_is_kept(self) -> None:
        commits = [Commit("a1", "feat: add foo", ())]
        url = "https://example.test/pr/1"
        body = "## What\n\nDepends on HAND\n- feat: add foo\n\n## Why\n\nx\n"
        assert rewrite_what(body, commits, [url]) == (
            f"## What\n\n- feat: add foo\n\nDepends on HAND\n\n## Why\n\nx\n\nDepends on {url}\n"
        )

    def test_trailing_hand_written_depends_line_is_kept(self) -> None:
        commits = [Commit("a1", "feat: add foo", ())]
        url = "https://example.test/pr/1"
        body = f"## What\n\n- feat: add foo\n\n## Why\n\nx\n\nDepends on OLD\nDepends on {url}\n"
        assert rewrite_what(body, commits, [url]) == (
            f"## What\n\n- feat: add foo\n\n## Why\n\nx\n\nDepends on OLD\n\nDepends on {url}\n"
        )

    def test_dropped_refs_lose_only_their_exact_line(self) -> None:
        commits = [Commit("a1", "feat: add foo", ())]
        body = (
            "## What\n\n- feat: add foo\n\n## Dependencies\n\n"
            "Depends on o/r#1\nDepends on o/r#10\nDepends on hand\n"
        )
        assert rewrite_what(body, commits, [], ["o/r#1"]) == (
            "## What\n\n- feat: add foo\n\n## Dependencies\n\n"
            "Depends on o/r#10\nDepends on hand\n"
        )

    def test_missing_what_heading_is_prepended(self) -> None:
        commits = [Commit("a1", "feat: add foo", ())]
        assert rewrite_what("## Why\n\nx\n", commits) == (
            "## What\n\n- feat: add foo\n\n## Why\n\nx\n"
        )

    def test_rewriting_twice_changes_nothing(self) -> None:
        commits = [Commit("a1", "feat: add foo", ()), Commit("a2", "fix: bar", ())]
        once = rewrite_what(_EDITED_BODY, commits, ["https://example.test/pr/1"])
        assert rewrite_what(once, commits, ["https://example.test/pr/1"]) == once


class TestPrTemplate:
    def test_reads_template_from_base_ref(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("show", stdout=_TEMPLATE)
        assert pr_template(tmp_path, "origin/main") == _TEMPLATE.strip()
        show_call = fake_subprocess.matching("show")[0]
        assert "origin/main:.github/PULL_REQUEST_TEMPLATE.md" in show_call

    def test_falls_back_when_base_has_no_template(
        self, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on("show", returncode=128)
        assert (
            pr_template(tmp_path, "origin/main")
            == "## What\n\n## Why\n\n## Dependencies\n\n## Issues\n"
        )


class TestWithoutGh:
    """The same operations through the GitHub API when gh is not installed."""

    @pytest.fixture(autouse=True)
    def _no_gh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(contribute, "_gh_installed", lambda: False)

    @pytest.fixture
    def repo(self, fake_github: FakeGitHub, fake_subprocess: FakeSubprocess) -> None:
        fake_subprocess.on("remote", "get-url", "upstream", returncode=2)
        fake_subprocess.on(
            "remote", "get-url", "origin", stdout="git@github.com:octo/widgets.git\n"
        )
        fake_github.on_graphql(
            "viewer { login", {"data": {"viewer": {"login": "tester"}}}
        )

    @staticmethod
    def _search(*nodes: dict[str, Any]) -> dict[str, Any]:
        page_info = {"hasNextPage": False, "endCursor": None}
        return {"data": {"search": {"pageInfo": page_info, "nodes": list(nodes)}}}

    def test_the_open_pr_of_a_branch_is_found(
        self, fake_github: FakeGitHub, repo: None, tmp_path: Path
    ) -> None:
        fake_github.on_graphql(
            "search(",
            self._search(
                {"number": 6, "headRefName": "feat/ab"},
                {"number": 7, "headRefName": "feat/a"},
            ),
        )

        assert contribute._pr_number_of(tmp_path, "feat/a") == 7

    def test_open_prs_carry_head_and_base_and_commits(
        self, fake_github: FakeGitHub, repo: None, tmp_path: Path
    ) -> None:
        node = {
            "number": 3,
            "state": "OPEN",
            "url": "u",
            "headRefName": "tester/x",
            "isDraft": True,
            "reviewDecision": None,
            "body": "b",
            "headRefOid": "abc",
            "baseRefName": "main",
            "title": "feat: x",
        }
        commit = {
            "oid": "c1",
            "messageHeadline": "feat: x",
            "messageBody": "",
            "authoredDate": "2024-01-01T00:00:00+00:00",
        }
        fake_github.on_graphql("search(", self._search(node))
        fake_github.on_graphql(
            "pullRequest(",
            {
                "data": {
                    "repository": {
                        "pullRequest": {"commits": {"nodes": [{"commit": commit}]}}
                    }
                }
            },
        )

        prs, skipped = open_prs(tmp_path)

        assert skipped == frozenset()
        assert (prs[0].head_sha, prs[0].base_branch, prs[0].review_decision) == (
            "abc",
            "main",
            "",
        )
        assert prs[0].title == "feat: x"
        assert [c.sha for c in prs[0].commits] == ["c1"]
        assert "is:open" in fake_github.graphql_variables("search(")[0]["q"]

    @pytest.mark.parametrize("permission", ["WRITE", "MAINTAIN", "ADMIN"])
    def test_push_access_uses_origin_directly(
        self, fake_github: FakeGitHub, repo: None, tmp_path: Path, permission: str
    ) -> None:
        fake_github.on_graphql(
            "viewerPermission",
            {"data": {"repository": {"viewerPermission": permission}}},
        )

        assert push_remote(tmp_path) == ("origin", False)

    def test_read_access_with_upstream_pushes_to_the_fork(
        self, fake_github: FakeGitHub, fake_subprocess: FakeSubprocess, tmp_path: Path
    ) -> None:
        fake_subprocess.on(
            "remote", "get-url", "upstream", stdout="git@github.com:octo/widgets.git\n"
        )
        fake_github.on_graphql(
            "viewerPermission", {"data": {"repository": {"viewerPermission": "READ"}}}
        )

        assert push_remote(tmp_path) == ("origin", True)

    def test_read_access_without_upstream_asks_for_a_fork(
        self, fake_github: FakeGitHub, repo: None, tmp_path: Path
    ) -> None:
        fake_github.on_graphql(
            "viewerPermission", {"data": {"repository": {"viewerPermission": "READ"}}}
        )

        with pytest.raises(SystemExit, match=r"octo/widgets.*git remote rename origin"):
            push_remote(tmp_path)

    def test_open_draft_pr_posts_to_the_base_branch(
        self, fake_github: FakeGitHub, repo: None, tmp_path: Path
    ) -> None:
        fake_github.on("POST", "/repos/octo/widgets/pulls", {"html_url": "https://x/9"})

        url = contribute.open_draft_pr(tmp_path, "origin/main", "me:topic", "t", "b")

        assert url == "https://x/9"
        assert fake_github.requests[-1][2] == {
            "base": "main",
            "head": "me:topic",
            "title": "t",
            "body": "b",
            "draft": True,
        }

    def test_edit_pr_patches(
        self, fake_github: FakeGitHub, repo: None, tmp_path: Path
    ) -> None:
        fake_github.on("PATCH", "/repos/octo/widgets/pulls/4", {})

        contribute.edit_pr(tmp_path, 4, "t", "new")

        assert fake_github.requests[-1][2] == {"title": "t", "body": "new"}

    def test_update_pr_branch_rebases(
        self, fake_github: FakeGitHub, repo: None, tmp_path: Path
    ) -> None:
        fake_github.on_graphql(
            "pullRequest(", {"data": {"repository": {"pullRequest": {"id": "PR_1"}}}}
        )
        fake_github.on_graphql("updatePullRequestBranch", {"data": {}})

        contribute.update_pr_branch(tmp_path, 4)

        assert "updateMethod: REBASE" in fake_github.requests[-1][2]["query"]
