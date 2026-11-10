"""Tests for contribute's worktree sync, run against real git and a fake gh."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from llm_prompts import contribute, github_api, main_sync, worktrees
from llm_prompts.contribute import SyncOptions
from llm_prompts.worktrees import Link, WorktreeEntry, load_entries

pytestmark = pytest.mark.real_io

WHY = "Sync opened PRs with nothing under Why."

_IDENTITY = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def _remote(branch: str) -> str:
    """Return the name ``branch`` is pushed under for the login ``tester``."""
    return f"tester/contribute/{branch}"


def git(repo: Path, *args: str) -> str:
    """Run real git in ``repo`` and return stripped stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **_IDENTITY},
    ).stdout.strip()


class Project:
    """A local clone with a bare origin, worktrees and a fake gh."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.clock = 1_700_000_000
        self.origin = root / "origin.git"
        self.repo = root / "repo"
        self.state_path = root / "gh-state.json"
        self.record = root / "record.json"
        self.extra: list[contribute.Target] = []
        self.auto_why = True
        self.state: dict[str, Any] = {"prs": {}, "next": 100, "calls": []}
        self.save_state()
        for key, value in _IDENTITY.items():
            monkeypatch.setenv(key, value)
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True
        )
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        git(self.repo, "remote", "add", "origin", str(self.origin))
        self.commit(self.repo, "base.txt", "base\n", "chore: base")
        git(self.repo, "push", "-q", "-u", "origin", "main")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        shutil.copy(Path(__file__).parent / "fake_gh.py", gh)
        gh.write_text(f"#!{sys.executable}\n" + gh.read_text().split("\n", 1)[1])
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("GH_FAKE", str(self.state_path))
        monkeypatch.setenv("GH_FAKE_ORIGIN", str(self.origin))
        monkeypatch.setenv(worktrees.RECORD_ENV, str(self.record))
        monkeypatch.setattr(
            github_api, "base_repo", lambda repo: ("o", Path(repo).name)
        )
        monkeypatch.setattr(contribute, "_gh_installed", lambda: True)

    @property
    def targets(self) -> list[contribute.Target]:
        return [("tool", self.repo, "src/prompts/"), *self.extra]

    def add_tool(self, name: str) -> Path:
        """Add a second cloned tool with its own origin; its gh state is shared."""
        origin = self.root / f"{name}-origin.git"
        repo = self.root / name
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True
        )
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        git(repo, "remote", "add", "origin", str(origin))
        self.commit(repo, "base.txt", "base\n", "chore: base")
        git(repo, "push", "-q", "-u", "origin", "main")
        self.extra.append((name, repo, "src/prompts/"))
        return repo

    def save_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")

    def load_state(self) -> dict[str, Any]:
        state: dict[str, Any] = json.loads(self.state_path.read_text(encoding="utf-8"))
        return state

    def gh_calls(self, *verb: str) -> list[list[str]]:
        calls = self.load_state()["calls"]
        return [call for call in calls if call[: len(verb)] == list(verb)]

    def add_pr(self, number: int, branch: str, **fields: Any) -> None:
        state = self.load_state()
        state["prs"][str(number)] = {
            "state": "OPEN",
            "isDraft": True,
            "title": "",
            "body": "",
            "headRefName": branch,
            **fields,
        }
        self.state = state
        self.save_state()

    def commit(self, repo: Path, name: str, content: str, message: str) -> str:
        (repo / name).write_text(content, encoding="utf-8")
        git(repo, "add", name)
        self.clock += 60
        git(repo, "commit", "-q", "-m", message, "--date", f"{self.clock} +0000")
        return git(repo, "rev-parse", "HEAD")

    def worktree(
        self,
        branch: str,
        *subjects: str,
        repo: Path | None = None,
        start: str = "main",
        lines: int = 1,
    ) -> Path:
        """Add a worktree on ``branch`` off ``start`` with one ``lines``-line commit per subject."""
        prefix = "" if repo is None else repo.name + "-"
        repo = repo or self.repo
        path = self.root / "wt" / (prefix + branch).replace("/", "-")
        git(repo, "worktree", "add", "-q", "-b", branch, str(path), start)
        for subject in subjects:
            self.commit(
                path,
                f"{branch.replace('/', '-')}-{len(subject)}.txt",
                f"{subject}\n" * lines,
                subject,
            )
        return path

    def run(self, tool: str | None = None, **options: Any) -> int:
        """Sync every tool, or edit the record of ``tool`` (the first when an edit is asked)."""
        editing = any(
            options.get(k)
            for k in (
                "branch",
                "forget",
                "ready",
                "local",
                "depends_on",
                "no_depends_on",
                "why",
            )
        )
        name = tool or ("tool" if editing else None)
        chosen = [t for t in self.targets if name in (None, t[0])]
        status = contribute.sync_targets(
            chosen, "tester", SyncOptions(**options), self.targets
        )
        if self.auto_why and options.get("ready"):
            contribute.sync_targets(
                chosen, "tester", SyncOptions(why=(options["ready"], WHY)), self.targets
            )
        return status

    def entries(self) -> list[WorktreeEntry]:
        return load_entries(self.record)

    def entries_of(self, repo: Path) -> list[WorktreeEntry]:
        return [e for e in self.entries() if e.repo == str(repo.resolve())]

    def main_subjects(self) -> list[str]:
        return git(
            self.repo, "log", "--reverse", "--format=%s", "origin/main..main"
        ).splitlines()

    def remote_branches(self) -> list[str]:
        out = git(
            self.origin, "for-each-ref", "--format=%(refname:short)", "refs/heads"
        )
        return [name for name in out.splitlines() if name != "main"]


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    return Project(tmp_path, monkeypatch)


def test_branch_records_a_worktree_as_local_only(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    path = project.worktree("feat/a", "feat: a")

    assert project.run(branch="feat/a") == 0

    assert project.entries() == [
        WorktreeEntry(
            repo=str(project.repo.resolve()),
            branch="feat/a",
            path=str(path.resolve()),
            pr=None,
            pr_state=None,
            remote_head=None,
            ready=False,
        )
    ]
    assert "feat/a: recorded" in capsys.readouterr().out


def test_recording_a_branch_names_the_sync_command_that_publishes_it(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")

    project.run(branch="feat/a")

    assert "llm-prompts contribute sync --tool tool --ready feat/a" in (
        capsys.readouterr().out
    )


def test_ready_and_local_switch_whether_the_branch_may_go_to_github(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")

    project.run(ready="feat/a")
    assert [e.ready for e in project.entries()] == [True]

    project.run(local="feat/a")
    assert [e.ready for e in project.entries()] == [False]
    assert project.gh_calls() == []


def test_forget_drops_only_the_named_entry(project: Project) -> None:
    project.worktree("feat/a", "feat: a")
    project.worktree("feat/b", "feat: b")
    project.run(branch="feat/a")
    project.run(branch="feat/b")

    assert project.run(forget="feat/a") == 0

    assert [e.branch for e in project.entries()] == ["feat/b"]


def test_editing_an_unrecorded_branch_fails(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run(ready="feat/zzz") == 1

    assert "feat/zzz: not recorded" in capsys.readouterr().out


def test_a_local_only_worktree_is_copied_into_main_and_never_sent_to_github(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")

    assert project.run() == 0
    assert project.main_subjects() == []
    assert "feat/a: would copy into main" in capsys.readouterr().out

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert project.remote_branches() == []
    assert project.gh_calls() == []


def test_a_worktree_with_several_commits_is_squashed_into_one_main_commit(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a", "feat: a2", lines=60)
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "feat-a-7.txt").exists()
    assert (project.repo / "feat-a-8.txt").exists()
    assert "skipped" not in capsys.readouterr().out


def _land_upstream(project: Project, name: str, pull: bool = True) -> None:
    """Push a new commit to origin main from another clone, and pull it into local main unless ``pull`` is false."""
    other = project.root / "upstream-clone"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, name, "upstream\n", f"chore: {name}")
    git(other, "push", "-q", "origin", "main")
    if pull:
        git(project.repo, "pull", "-q", "--ff-only")


def test_a_worktree_started_before_upstream_moved_keeps_the_upstream_change_in_main(
    project: Project,
) -> None:
    project.worktree("feat/a", "feat: a", "feat: a2")
    project.run(branch="feat/a")
    _land_upstream(project, "upstream.txt")

    assert project.run(apply=True) == 0

    assert (project.repo / "upstream.txt").exists()
    copied = git(project.repo, "rev-parse", "main")

    assert project.run(apply=True) == 0

    assert git(project.repo, "rev-parse", "main") == copied


def test_a_rebuild_replays_main_onto_the_fetched_base(project: Project) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    _land_upstream(project, "upstream.txt", pull=False)
    _amend(project, path, "feat: a2")

    assert project.run(apply=True) == 0

    assert (project.repo / "upstream.txt").exists()
    assert project.main_subjects() == ["feat: a2"]


def test_main_is_rebuilt_onto_the_fetched_base_when_no_worktree_changed(
    project: Project,
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    _land_upstream(project, "upstream.txt", pull=False)

    assert project.run(apply=True) == 0

    assert (project.repo / "upstream.txt").exists()
    assert project.main_subjects() == ["feat: a"]


def test_a_worktree_started_from_main_holding_another_worktrees_copy_is_skipped(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    project.worktree("feat/b", "feat: b", start="main")
    project.run(branch="feat/b")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "feat/b: skipped: holds commits of feat/a" in capsys.readouterr().out
    assert project.main_subjects() == ["feat: a"]


def test_a_worktree_holding_an_earlier_version_of_another_worktrees_commit_is_skipped(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    a = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    old = git(a, "rev-parse", "HEAD")
    project.worktree("feat/b", "feat: b", start=old)
    project.run(branch="feat/b")
    _amend(project, a, "feat: a")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "feat/b: skipped: holds commits of feat/a" in capsys.readouterr().out
    assert project.main_subjects() == ["feat: a"]


def test_a_worktree_holding_a_merged_worktrees_copy_on_main_is_skipped_by_list_and_sync(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    a = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    project.worktree("feat/b", "feat: b", start="main")
    project.run(branch="feat/b")
    project.add_pr(
        7, _remote("feat/a"), state="MERGED", headRefOid=git(a, "rev-parse", "HEAD")
    )
    worktrees.save_entries(
        project.record,
        [
            e._replace(pr=7, pr_state="MERGED") if e.branch == "feat/a" else e
            for e in project.entries()
        ],
    )
    capsys.readouterr()

    assert contribute.list_targets(project.targets) == 0
    assert "feat/b  local only  no PR  skipped: holds local main commits" in (
        capsys.readouterr().out
    )

    assert project.run(apply=True) == 0

    assert "feat/b: skipped: holds local main commits" in capsys.readouterr().out
    assert project.main_subjects() == ["feat: a"]


def test_a_first_commit_and_content_changed_in_one_sync_swap_the_copy_in_main(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    git(path, "reset", "-q", "--soft", "origin/main")
    (path / "feat-a-7.txt").write_text("changed\n", encoding="utf-8")
    git(path, "add", "feat-a-7.txt")
    project.clock += 60
    git(
        path, "commit", "-q", "-m", "feat: reworded", "--date", f"{project.clock} +0000"
    )

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: reworded"]
    assert (project.repo / "feat-a-7.txt").read_text(encoding="utf-8") == "changed\n"
    assert project.run(apply=True) == 0
    assert project.main_subjects() == ["feat: reworded"]


def test_an_amended_worktree_commit_replaces_its_copy_in_main(project: Project) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.worktree("feat/b", "feat: b")
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    project.run(apply=True)
    (path / "extra.txt").write_text("more\n", encoding="utf-8")
    git(path, "add", "extra.txt")
    git(path, "commit", "-q", "--amend", "--no-edit")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: b"]
    assert (project.repo / "extra.txt").read_text(encoding="utf-8") == "more\n"


def test_main_is_not_reset_when_the_backup_ref_cannot_be_saved(
    project: Project,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    real_run_git = main_sync.run_git

    def run_git(repo: Path, *args: str, **kwargs: Any) -> Any:
        if args[0] == "update-ref":
            return subprocess.CompletedProcess(args, 1, "", "cannot lock ref")
        return real_run_git(repo, *args, **kwargs)

    monkeypatch.setattr(main_sync, "run_git", run_git)

    assert project.run(apply=True) == 1

    assert project.main_subjects() == []
    assert "cannot lock ref" in capsys.readouterr().out


def test_a_new_commit_in_a_squashed_worktree_replaces_its_main_commit(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a", "feat: a2")
    project.run(branch="feat/a")
    project.run(apply=True)
    project.commit(path, "extra.txt", "more\n", "feat: a3")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "extra.txt").read_text(encoding="utf-8") == "more\n"
    assert (project.repo / "feat-a-8.txt").exists()


def test_main_copies_of_each_worktree_commit_give_way_to_one_squash(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a", "feat: a2")
    git(project.repo, "cherry-pick", "-x", "origin/main..feat/a")
    project.clock += 60
    (path / "feat-a-8.txt").write_text("amended\n", encoding="utf-8")
    git(
        path,
        "commit",
        "-qa",
        "--amend",
        "--no-edit",
        "--date",
        f"{project.clock} +0000",
    )
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "feat-a-8.txt").read_text(encoding="utf-8") == "amended\n"


def test_a_rewritten_worktree_replaces_main_copies_of_its_earlier_commits(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a", "feat: a2", "feat: a3")
    git(project.repo, "cherry-pick", "-x", "origin/main..feat/a")
    git(path, "reset", "-q", "--hard", "origin/main")
    project.commit(path, "feat-a-7.txt", "rewritten\n", "feat: a")
    project.commit(path, "feat-a-8.txt", "rewritten\n", "fix: a")
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "feat-a-7.txt").read_text(encoding="utf-8") == "rewritten\n"
    assert (project.repo / "feat-a-8.txt").read_text(encoding="utf-8") == "rewritten\n"


def test_an_unrelated_main_commit_titled_like_a_later_worktree_commit_is_kept(
    project: Project,
) -> None:
    project.commit(project.repo, "other.txt", "other\n", "feat: a2")
    project.worktree("feat/a", "feat: a", "feat: a2", start="origin/main")
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a2", "feat: a"]


@pytest.fixture
def hand_resolved(project: Project) -> main_sync.Squash:
    """A squash that conflicts with local main, after its hand resolution was recorded and reused once."""
    repo = project.repo
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "feat")
    tip = project.commit(repo, "base.txt", "feature\n", "feat: feature")
    git(repo, "checkout", "-q", "main")
    project.commit(repo, "base.txt", "main\n", "feat: main")
    squash = main_sync.Squash(tip=tip, floor=base, first=tip)
    skipped = main_sync.rebuild_local(repo, base, {}, (), {}, [squash]).skipped
    assert [copy.first for copy in skipped] == [tip]
    rerere = ("-c", "rerere.enabled=true")
    git(repo, "checkout", "-q", "--detach")
    with pytest.raises(subprocess.CalledProcessError):
        git(repo, *rerere, "cherry-pick", tip)
    (repo / "base.txt").write_text("resolved\n", encoding="utf-8")
    git(repo, "add", "base.txt")
    git(repo, *rerere, "commit", "-q", "--no-edit")
    git(repo, "checkout", "-q", "main")
    assert main_sync.rebuild_local(repo, base, {}, (), {}, [squash]).mode == "rebuilt"
    return squash


def test_a_recorded_hand_resolution_settles_the_next_rebuild(
    project: Project, hand_resolved: main_sync.Squash
) -> None:
    assert (project.repo / "base.txt").read_text(encoding="utf-8") == "resolved\n"
    assert project.main_subjects() == ["feat: main", "feat: feature"]


def test_a_hand_resolved_copy_is_current(
    project: Project, hand_resolved: main_sync.Squash
) -> None:
    assert main_sync.replays_to(project.repo, "main^", hand_resolved, "main")
    assert not main_sync.replays_to(project.repo, "main^", hand_resolved, "main^")


def test_a_clean_conflict_fallback_is_current(project: Project) -> None:
    repo = project.repo
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "feat")
    tip = project.commit(repo, "base.txt", "feature\n", "feat: feature")
    git(repo, "checkout", "-q", "main")
    (repo / ".gitattributes").write_text("base.txt merge=union\n", encoding="utf-8")
    git(repo, "add", ".gitattributes")
    parent = project.commit(repo, "base.txt", "main\n", "feat: main")
    git(repo, "cherry-pick", tip)
    result = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "--detach", base)

    assert main_sync.replays_to(
        repo, parent, main_sync.Squash(tip=tip, floor=base, first=tip), result
    )


def test_a_copy_that_follows_a_rename_on_main_is_current(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    body = "".join(f"line {n}\n" for n in range(10))
    project.commit(project.repo, "old.txt", body, "chore: add old")
    git(project.repo, "push", "-q", "origin", "main")
    git(project.repo, "mv", "old.txt", "new.txt")
    git(project.repo, "commit", "-qm", "chore: rename")
    path = project.worktree("feat/a", start="origin/main")
    project.commit(path, "old.txt", body.replace("line 3", "edited"), "feat: a")
    project.run(branch="feat/a")
    assert project.run(apply=True) == 0
    copied = git(project.repo, "rev-parse", "main")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "copied into main" not in capsys.readouterr().out
    assert git(project.repo, "rev-parse", "main") == copied


def test_a_local_main_commit_a_worktree_was_once_started_from_is_kept(
    project: Project,
) -> None:
    project.commit(project.repo, "local.txt", "local\n", "chore: local")
    path = project.worktree("feat/b", "feat: b", "feat: b2")
    git(path, "reset", "-q", "--hard", "origin/main")
    project.commit(path, "feat-b-7.txt", "rewritten\n", "feat: b")
    project.run(branch="feat/b")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["chore: local", "feat: b"]


def test_a_local_main_commit_stays_after_a_rebuild_rewrites_the_commit_a_worktree_started_from(
    project: Project,
) -> None:
    project.commit(project.repo, "local.txt", "local\n", "chore: local")
    path = project.worktree("feat/b", "feat: b", "feat: b2")
    git(path, "reset", "-q", "--hard", "origin/main")
    project.commit(path, "feat-b-7.txt", "rewritten\n", "feat: b")
    project.run(branch="feat/b")
    _land_upstream(project, "upstream.txt", pull=False)
    assert project.run(apply=True) == 0

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["chore: local", "feat: b"]


def test_a_local_main_commit_stays_after_the_reflog_of_main_expired(
    project: Project,
) -> None:
    project.commit(project.repo, "local.txt", "local\n", "chore: local")
    path = project.worktree("feat/b", "feat: b", "feat: b2")
    git(path, "reset", "-q", "--hard", "origin/main")
    project.commit(path, "feat-b-7.txt", "rewritten\n", "feat: b")
    project.run(branch="feat/b")
    _land_upstream(project, "upstream.txt", pull=False)
    assert project.run(apply=True) == 0
    git(
        project.repo,
        "reflog",
        "expire",
        "--expire=now",
        "--expire-unreachable=now",
        "refs/heads/main",
    )

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["chore: local", "feat: b"]


def test_a_worktree_started_in_the_same_second_as_a_copied_one_gets_its_own_main_commit(
    project: Project,
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    path = project.worktree("feat/b", start="origin/main")
    (path / "b.txt").write_text("b\n", encoding="utf-8")
    git(path, "add", "b.txt")
    git(path, "commit", "-q", "-m", "feat: b", "--date", f"{project.clock} +0000")
    project.run(branch="feat/b")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: b"]


def test_an_unrelated_main_commit_from_the_same_second_is_kept(
    project: Project,
) -> None:
    project.commit(project.repo, "stray.txt", "stray\n", "chore: stray")
    path = project.worktree("feat/a", start="origin/main")
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    git(path, "add", "a.txt")
    git(path, "commit", "-q", "-m", "feat: a", "--date", f"{project.clock} +0000")
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["chore: stray", "feat: a"]


def _commit_at(repo: Path, name: str, subject: str, at: str) -> None:
    (repo / name).write_text(f"{name}\n", encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", subject, "--date", f"{at} +0000")


def test_an_unrelated_main_commit_with_a_worktree_commits_time_and_subject_is_kept(
    project: Project,
) -> None:
    _commit_at(project.repo, "other.txt", "feat: a", str(project.clock + 60))
    path = project.worktree("feat/a", start="origin/main")
    _commit_at(path, "a.txt", "feat: a", str(project.clock + 60))
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: a"]
    assert (project.repo / "other.txt").exists()
    assert (project.repo / "a.txt").exists()


def test_an_unrelated_main_commit_with_a_later_worktree_commits_time_and_subject_is_kept(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a", "feat: a2")
    _commit_at(
        project.repo,
        "other.txt",
        "feat: a2",
        git(path, "log", "-1", "--format=%at"),
    )
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert (project.repo / "other.txt").exists()
    assert project.main_subjects() == ["feat: a2", "feat: a"]


def test_an_unrelated_main_commit_with_a_copys_time_and_subject_is_kept_beside_it(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    at = git(path, "log", "-1", "--format=%at")
    _commit_at(project.repo, "other.txt", "feat: a", at)

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: a"]
    assert (project.repo / "other.txt").exists()


def test_an_unrelated_main_commit_with_a_copys_saved_identity_is_kept_when_the_copy_was_reworded(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    at = git(path, "log", "-1", "--format=%at")
    git(project.repo, "commit", "-q", "--amend", "-m", "feat: reworded on main")
    _commit_at(project.repo, "other.txt", "feat: a", at)

    assert project.run(apply=True) == 0

    assert (project.repo / "other.txt").exists()
    assert (project.repo / "feat-a-7.txt").exists()


def _copied_worktree(project: Project) -> Path:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    return path


def _amend_extra(path: Path) -> None:
    (path / "extra.txt").write_text("more\n", encoding="utf-8")
    git(path, "add", "extra.txt")
    git(path, "commit", "-q", "--amend", "--no-edit")


def test_main_is_left_alone_when_two_commits_could_be_the_changed_worktrees_copy(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _copied_worktree(project)
    (project.repo / "hand.txt").write_text("edited\n", encoding="utf-8")
    git(project.repo, "add", "hand.txt")
    git(project.repo, "commit", "-q", "--amend", "--no-edit")
    _commit_at(
        project.repo, "other.txt", "feat: a", git(path, "log", "-1", "--format=%at")
    )
    _amend_extra(path)
    before = git(project.repo, "rev-parse", "main")

    assert project.run(apply=True) == 1

    assert "main not updated" in capsys.readouterr().out
    assert git(project.repo, "rev-parse", "main") == before


def test_the_copy_of_an_earlier_version_is_swapped_beside_an_unrelated_commit_with_its_identity(
    project: Project,
) -> None:
    path = _copied_worktree(project)
    _commit_at(
        project.repo, "other.txt", "feat: a", git(path, "log", "-1", "--format=%at")
    )
    _amend_extra(path)

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: a"]
    assert (project.repo / "other.txt").exists()
    assert (project.repo / "extra.txt").read_text(encoding="utf-8") == "more\n"


@pytest.mark.parametrize("rewrite", [["--no-edit"], ["-m", "feat: reworded"]])
def test_an_unrelated_main_commit_with_the_time_and_subject_of_a_rewritten_never_copied_commit_is_kept(
    project: Project, rewrite: list[str]
) -> None:
    path = project.worktree("feat/a", start="origin/main")
    _commit_at(path, "a.txt", "feat: a", str(project.clock + 60))
    _commit_at(
        project.repo, "other.txt", "feat: a", git(path, "log", "-1", "--format=%at")
    )
    (path / "a.txt").write_text("amended\n", encoding="utf-8")
    git(path, "add", "a.txt")
    git(path, "commit", "-q", "--amend", *rewrite)
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert (project.repo / "other.txt").exists()
    assert (project.repo / "a.txt").read_text(encoding="utf-8") == "amended\n"


def test_a_reworded_first_commit_replaces_its_old_copy_in_main(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a", "feat: a2")
    project.run(branch="feat/a")
    project.run(apply=True)
    git(path, "reset", "-q", "--soft", "origin/main")
    project.clock += 60
    git(
        path,
        "commit",
        "-q",
        "-m",
        "feat: reworded",
        "--date",
        f"{project.clock} +0000",
    )

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: reworded"]
    assert project.run(apply=True) == 0
    assert project.main_subjects() == ["feat: reworded"]


def test_a_ready_worktree_is_pushed_and_opens_a_draft_pr(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    assert project.run() == 0
    assert "feat/a: would push and open a draft PR" in capsys.readouterr().out
    assert project.remote_branches() == []
    assert project.gh_calls("pr", "create") == []

    assert project.run(apply=True) == 0

    tip = git(project.repo, "rev-parse", "feat/a")
    assert git(project.origin, "rev-parse", _remote("feat/a")) == tip
    [create] = project.gh_calls("pr", "create")
    assert create[:6] == ["pr", "create", "--draft", "--base", "main", "--head"]
    assert create[create.index("--title") + 1] == "feat: a"
    [entry] = project.entries()
    assert (entry.pr, entry.pr_state, entry.remote_head, entry.ready) == (
        100,
        "OPEN",
        tip,
        True,
    )


def test_a_recorded_why_fills_the_pr_body_sync_opens(project: Project) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.auto_why = False
    project.run(ready="feat/a")
    project.run(why=("feat/a", WHY))

    assert project.run(apply=True) == 0

    [create] = project.gh_calls("pr", "create")
    body = create[create.index("--body") + 1]
    assert f"## Why\n\n{WHY}\n" in body


def test_a_worktree_without_a_why_is_not_opened_and_the_others_still_sync(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.auto_why = False
    for branch in ("feat/a", "feat/b"):
        project.worktree(branch, f"feat: {branch[-1]}")
        project.run(branch=branch)
        project.run(ready=branch)
    project.run(why=("feat/b", WHY))

    assert project.run(apply=True) == 1

    assert project.remote_branches() == [_remote("feat/b")]
    [create] = project.gh_calls("pr", "create")
    assert create[create.index("--head") + 1] == _remote("feat/b")
    assert (
        "feat/a: not opened, PR section Why is empty. Set it with: "
        'llm-prompts contribute sync --tool tool --why feat/a "<why>"'
    ) in capsys.readouterr().out


def _amend(project: Project, path: Path, message: str) -> str:
    (path / "more.txt").write_text(message, encoding="utf-8")
    git(path, "add", "more.txt")
    git(path, "commit", "-q", "--amend", "-m", message)
    return git(path, "rev-parse", "HEAD")


@pytest.fixture
def pushed(project: Project) -> Path:
    """A ready worktree already pushed with its draft PR."""
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")
    project.run(apply=True)
    return path


def test_a_branch_is_pushed_and_drafted_under_the_login_contribute_prefix(
    project: Project, pushed: Path
) -> None:
    assert project.remote_branches() == ["tester/contribute/feat/a"]
    [pr] = project.load_state()["prs"].values()
    assert pr["headRefName"] == "tester/contribute/feat/a"
    assert git(pushed, "branch", "--show-current") == "feat/a"


def test_a_pr_headed_by_the_bare_branch_name_keeps_that_head(project: Project) -> None:
    path = project.worktree("feat/a", "feat: a")
    git(project.repo, "push", "-q", "origin", "feat/a")
    project.add_pr(7, "feat/a")
    project.run(rescan=True)
    project.run(ready="feat/a")
    tip = _amend(project, path, "fix: a")

    assert project.run(apply=True) == 0

    assert git(project.origin, "rev-parse", "feat/a") == tip
    assert project.remote_branches() == ["feat/a"]


def test_a_rewritten_commit_is_force_pushed_to_its_draft_pr_with_a_fresh_title(
    project: Project, pushed: Path
) -> None:
    tip = _amend(project, pushed, "fix: a")

    assert project.run(apply=True) == 0

    assert git(project.origin, "rev-parse", _remote("feat/a")) == tip
    [edit] = project.gh_calls("pr", "edit")
    assert edit[edit.index("--title") + 1] == "fix: a"
    assert [e.remote_head for e in project.entries()] == [tip]
    assert project.main_subjects() == ["fix: a"]


def test_an_open_pr_with_an_empty_why_is_filled_from_the_record_or_left_alone_and_named(
    project: Project, pushed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = "## What\n\n- feat: a\n\n## Why\n\n<!-- Why it changed. -->\n"
    _set_body(project, 100, empty)
    project.run(why=("feat/a", ""))
    _amend(project, pushed, "fix: a")
    capsys.readouterr()

    assert project.run(apply=True) == 1

    assert pr_body(project, 100) == empty
    assert (
        "feat/a: PR #100 body left as it is, PR section Why is empty. Set it with: "
        'llm-prompts contribute sync --tool tool --why feat/a "<why>"'
    ) in capsys.readouterr().out

    project.run(why=("feat/a", WHY))
    assert project.run(apply=True) == 0

    assert f"## Why\n\n{WHY}\n" in pr_body(project, 100)


def test_a_hand_written_why_is_kept_over_the_recorded_one(
    project: Project, pushed: Path
) -> None:
    _set_body(project, 100, "## What\n\n- feat: a\n\n## Why\n\nMy reason.\n")
    _amend(project, pushed, "fix: a")

    assert project.run(apply=True) == 0

    assert "## Why\n\nMy reason.\n" in pr_body(project, 100)
    assert WHY not in pr_body(project, 100)


def _set_title(project: Project, number: int, title: str) -> None:
    state = project.load_state()
    state["prs"][str(number)]["title"] = title
    project.state = state
    project.save_state()


def test_a_title_edited_by_hand_is_kept_but_one_sync_wrote_follows_the_commits(
    project: Project, pushed: Path
) -> None:
    _amend(project, pushed, "fix: a")
    assert project.run(apply=True) == 0
    assert project.load_state()["prs"]["100"]["title"] == "fix: a"

    _set_title(project, 100, "My own title")
    _amend(project, pushed, "fix: b")
    assert project.run(apply=True) == 0

    assert project.load_state()["prs"]["100"]["title"] == "My own title"
    assert "- fix: b" in pr_body(project, 100)


def _amend_remotely(project: Project, branch: str, message: str) -> str:
    other = project.root / "other"
    if not other.exists():
        subprocess.run(
            ["git", "clone", "-q", str(project.origin), str(other)], check=True
        )
    git(other, "fetch", "-q", "origin")
    git(other, "checkout", "-q", "-B", branch, f"origin/{_remote(branch)}")
    tip = _amend(project, other, message)
    git(other, "push", "-q", "--force", "origin", f"{branch}:{_remote(branch)}")
    return tip


def test_a_remote_rewrite_is_pulled_into_the_worktree_and_main(
    project: Project, pushed: Path
) -> None:
    tip = _amend_remotely(project, "feat/a", "fix: a")

    assert project.run(apply=True) == 0

    assert git(pushed, "rev-parse", "HEAD") == tip
    assert project.main_subjects() == ["fix: a"]
    assert [e.remote_head for e in project.entries()] == [tip]


def test_a_branch_changed_on_both_sides_is_left_alone(
    project: Project, pushed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    remote_tip = _amend_remotely(project, "feat/a", "fix: remote")
    local_tip = _amend(project, pushed, "fix: local")

    assert project.run(apply=True) == 0

    assert git(pushed, "rev-parse", "HEAD") == local_tip
    assert git(project.origin, "rev-parse", _remote("feat/a")) == remote_tip
    assert "feat/a: diverged from the remote branch" in capsys.readouterr().out


def test_rescan_keeps_a_diverged_branch_from_being_force_pushed(
    project: Project, pushed: Path
) -> None:
    remote_tip = _amend_remotely(project, "feat/a", "fix: remote")
    _amend(project, pushed, "fix: local")

    assert project.run(rescan=True) == 0
    assert project.run(apply=True) == 0

    assert git(project.origin, "rev-parse", _remote("feat/a")) == remote_tip


def test_a_rewrite_is_not_forced_onto_a_pr_that_is_no_longer_a_draft(
    project: Project, pushed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    remote_tip = git(project.origin, "rev-parse", _remote("feat/a"))
    project.add_pr(100, _remote("feat/a"), isDraft=False)
    _amend(project, pushed, "fix: a")

    assert project.run(apply=True) == 0

    assert git(project.origin, "rev-parse", _remote("feat/a")) == remote_tip
    assert "PR #100 is not a draft" in capsys.readouterr().out


def test_a_local_only_worktree_with_a_pr_is_never_pushed_or_edited(
    project: Project, pushed: Path
) -> None:
    project.run(local="feat/a")
    remote_tip = git(project.origin, "rev-parse", _remote("feat/a"))
    _amend(project, pushed, "fix: a")

    assert project.run(apply=True) == 0

    assert git(project.origin, "rev-parse", _remote("feat/a")) == remote_tip
    assert project.gh_calls("pr", "edit") == []
    assert len(project.gh_calls("pr", "create")) == 1
    assert project.main_subjects() == ["fix: a"]


def _merge(project: Project, number: int, oid: str) -> None:
    state = project.load_state()
    state["prs"][str(number)].update(state="MERGED", headRefOid=oid)
    project.state = state
    project.save_state()
    git(project.origin, "branch", "-D", _remote("feat/a"))


def test_a_merged_worktree_is_removed_with_its_branch_and_entry(
    project: Project, pushed: Path
) -> None:
    _merge(project, 100, git(pushed, "rev-parse", "HEAD"))

    assert project.run(apply=True) == 0

    assert not pushed.exists()
    assert git(project.repo, "branch", "--list", "feat/a") == ""
    assert project.entries() == []


def test_a_merged_worktree_with_uncommitted_work_is_kept(
    project: Project, pushed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _merge(project, 100, git(pushed, "rev-parse", "HEAD"))
    (pushed / "base.txt").write_text("changed\n", encoding="utf-8")

    assert project.run(apply=True) == 0

    assert pushed.exists()
    assert [e.branch for e in project.entries()] == ["feat/a"]
    assert (
        "feat/a: merged, but the worktree has uncommitted changes"
        in capsys.readouterr().out
    )


def test_all_recorded_prs_are_looked_up_in_one_query(project: Project) -> None:
    project.worktree("feat/a", "feat: a")
    project.worktree("feat/b", "feat: b")
    for branch, number in (("feat/a", 7), ("feat/b", 8)):
        project.add_pr(number, _remote(branch))
        git(project.repo, "push", "-q", "origin", f"{branch}:{_remote(branch)}")
        project.run(branch=branch)
    entries = [
        e._replace(pr=int(e.branch[-1] == "a") + 7, remote_head="x")
        for e in project.entries()
    ]
    worktrees.save_entries(project.record, entries)

    assert project.run() == 0

    [query] = project.gh_calls("api", "graphql")
    assert "pr7: pullRequest" in query[3] and "pr8: pullRequest" in query[3]


def test_rescan_records_open_prs_checked_out_in_worktrees_and_keeps_existing_flags(
    project: Project,
) -> None:
    project.worktree("feat/a", "feat: a")
    project.worktree("feat/b", "feat: b")
    project.worktree("feat/c", "feat: c")
    for branch, number in (("feat/a", 7), ("feat/b", 8)):
        git(project.repo, "push", "-q", "origin", f"{branch}:{_remote(branch)}")
        project.add_pr(number, _remote(branch))
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    assert project.run(rescan=True) == 0

    by_branch = {e.branch: e for e in project.entries()}
    assert sorted(by_branch) == ["feat/a", "feat/b"]
    assert (by_branch["feat/a"].pr, by_branch["feat/a"].ready) == (7, True)
    assert (
        by_branch["feat/b"].pr,
        by_branch["feat/b"].ready,
        by_branch["feat/b"].pr_state,
    ) == (8, False, "OPEN")
    assert by_branch["feat/b"].remote_head == git(project.repo, "rev-parse", "feat/b")


def test_rescan_keeps_the_recorded_why_and_reads_a_new_entrys_from_the_pr_body(
    project: Project,
) -> None:
    project.auto_why = False
    for branch, number, body in (
        ("feat/a", 7, "## Why\n\nIn the PR.\n"),
        ("feat/b", 8, "## What\n\n- b\n\n## Why\n\nIn the other PR.\n"),
    ):
        project.worktree(branch, f"feat: {branch}")
        git(project.repo, "push", "-q", "origin", branch)
        project.add_pr(number, branch, body=body)
    project.run(branch="feat/a")
    project.run(why=("feat/a", WHY))
    project.run(branch="feat/b")
    project.run(forget="feat/b")

    assert project.run(rescan=True) == 0

    assert {e.branch: e.why for e in project.entries()} == {
        "feat/a": WHY,
        "feat/b": "In the other PR.",
    }


def test_a_corrupt_record_stops_sync_and_rescan_rebuilds_it(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    git(project.repo, "push", "-q", "origin", "feat/a:" + _remote("feat/a"))
    project.add_pr(7, _remote("feat/a"))
    project.record.write_text("{not json", encoding="utf-8")

    assert project.run(apply=True) == 1
    out = capsys.readouterr().out
    assert "--rescan" in out
    assert not project.record.exists()

    assert project.run(rescan=True) == 0
    assert [e.pr for e in project.entries()] == [7]


def test_list_shows_each_entry_offline(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    project.worktree("feat/b", "feat: b", "feat: b2")
    project.worktree("feat/d", "feat: d", "feat: d2", lines=60)
    big = project.worktree("feat/c", "feat: c")
    project.commit(big, "big.txt", "x\n" * 100, "feat: c big")
    git(big, "reset", "-q", "--soft", "main")
    git(big, "commit", "-q", "-m", "feat: c")
    for branch in ("feat/a", "feat/b", "feat/c", "feat/d"):
        project.run(branch=branch)
    project.run(ready="feat/a")
    capsys.readouterr()
    project.state["calls"] = []
    project.save_state()

    assert contribute.list_targets(project.targets) == 0

    out = capsys.readouterr().out
    assert "feat/a  ready  no PR  1 lines" in out
    assert "feat/b  local only  no PR  2 commits, 2 lines" in out
    assert "lines (over the 100-line limit)" in out.splitlines()[2]
    assert (
        "feat/d  local only  no PR  2 commits, 120 lines (over the 100-line limit)"
        in out
    )
    assert project.gh_calls() == []


def test_list_skips_an_entry_whose_branch_was_deleted_outside_sync(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    gone = project.worktree("feat/b", "feat: b")
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    git(project.repo, "worktree", "remove", "--force", str(gone))
    git(project.repo, "branch", "-D", "feat/b")
    capsys.readouterr()

    assert contribute.list_targets(project.targets) == 0

    out = capsys.readouterr().out
    assert "feat/a  local only  no PR  1 lines" in out
    assert "feat/b  local only  no PR  skipped: branch is gone" in out


def test_a_merged_worktree_is_not_copied_into_main(project: Project) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.add_pr(
        7, "feat/a", state="MERGED", headRefOid=git(path, "rev-parse", "HEAD")
    )
    project.run(branch="feat/a")
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    (path / "base.txt").write_text("changed\n", encoding="utf-8")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == []


def test_the_main_copy_of_a_merged_worktree_is_dropped_once_its_squash_landed(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    project.add_pr(
        7, "feat/a", state="MERGED", headRefOid=git(path, "rev-parse", "HEAD")
    )
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "reviewed\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == []


def test_the_main_copy_of_a_merged_worktree_is_dropped_though_review_changed_its_tree(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    (path / "review.txt").write_text("review edit\n", encoding="utf-8")
    git(path, "add", "review.txt")
    git(path, "commit", "-q", "--amend", "--no-edit")
    project.add_pr(
        7, "feat/a", state="MERGED", headRefOid=git(path, "rev-parse", "HEAD")
    )
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "reviewed\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == []


def test_the_main_copy_of_a_merged_worktree_stays_when_review_changed_its_tree_and_another_commit_shares_its_identity(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    (path / "review.txt").write_text("review edit\n", encoding="utf-8")
    git(path, "add", "review.txt")
    git(path, "commit", "-q", "--amend", "--no-edit")
    _commit_at(
        project.repo, "other.txt", "feat: a", git(path, "log", "-1", "--format=%at")
    )
    project.add_pr(
        7, "feat/a", state="MERGED", headRefOid=git(path, "rev-parse", "HEAD")
    )
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "reviewed\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 1

    assert project.main_subjects() == ["feat: a", "feat: a"]
    assert "none is its copy" in capsys.readouterr().out


def test_an_unrelated_main_commit_with_the_time_and_subject_of_a_landed_copy_is_kept(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    _commit_at(
        project.repo, "other.txt", "feat: a", git(path, "log", "-1", "--format=%at")
    )
    project.add_pr(
        7, "feat/a", state="MERGED", headRefOid=git(path, "rev-parse", "HEAD")
    )
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "reviewed\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "other.txt").exists()


def test_a_newer_main_copy_of_a_merged_worktree_stays_when_an_older_version_of_its_pr_lands(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    published = git(path, "rev-parse", "HEAD")
    (path / "newer.txt").write_text("unpublished\n", encoding="utf-8")
    git(path, "add", "newer.txt")
    git(path, "commit", "-q", "--amend", "--no-edit")
    project.run(apply=True)
    project.add_pr(7, "feat/a", state="MERGED", headRefOid=published)
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "landed.txt", "reviewed\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]


def test_a_newer_main_copy_stays_when_its_branch_is_deleted_and_an_older_version_of_its_pr_lands(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    published = git(path, "rev-parse", "HEAD")
    (path / "newer.txt").write_text("unpublished\n", encoding="utf-8")
    git(path, "add", "newer.txt")
    git(path, "commit", "-q", "--amend", "--no-edit")
    project.run(apply=True)
    git(project.repo, "worktree", "remove", "--force", str(path))
    git(project.repo, "branch", "-D", "feat/a")
    project.add_pr(7, "feat/a", state="MERGED", headRefOid=published)
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "landed.txt", "reviewed\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]


def test_main_is_left_alone_unless_it_is_checked_out(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    git(project.repo, "switch", "-q", "-c", "elsewhere")

    assert project.run(apply=True) == 1

    assert git(project.repo, "log", "--format=%s", "origin/main..elsewhere") == ""
    assert "main not updated" in capsys.readouterr().out


def test_a_copy_that_cannot_replay_is_skipped_and_the_others_still_copy(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    project.worktree("feat/b", "feat: b")
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    project.commit(project.repo, "feat-a-7.txt", "other\n", "feat: other")

    assert project.run(apply=True) == 0

    out = capsys.readouterr().out
    assert "feat/a: not copied into main: " in out
    assert "(feat: a) conflicts with upstream in feat-a-7.txt" in out
    assert "feat/b: copied into main" in out
    assert project.main_subjects() == ["feat: other", "feat: b"]
    assert [(e.branch, e.copied is None) for e in project.entries()] == [
        ("feat/a", True),
        ("feat/b", False),
    ]


def test_an_upper_copy_that_conflicts_after_its_lower_is_amended_is_skipped_and_forgotten(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = [f"line {n}\n" for n in range(60)]

    def shared(middle: str) -> str:
        return "".join([*lines[:30], middle, *lines[31:]])

    lower = project.worktree("feat/a")
    project.commit(lower, "shared.txt", shared("lower\n"), "feat: lower")
    upper = project.worktree("feat/b", "feat: upper", start="feat/a", lines=60)
    project.commit(upper, "shared.txt", shared("upper\n"), "feat: upper edit")
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    assert project.run("tool", depends_on=("feat/b", "tool:feat/a")) == 0
    assert project.run(apply=True) == 0
    (lower / "shared.txt").write_text(shared("amended\n"), encoding="utf-8")
    git(lower, "commit", "-q", "-a", "--amend", "--no-edit")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "feat/b: not copied into main: " in capsys.readouterr().out
    assert project.main_subjects() == ["feat: lower"]
    assert [(e.branch, e.copied is None) for e in project.entries()] == [
        ("feat/a", False),
        ("feat/b", True),
    ]


def test_a_second_run_waits_for_nothing_and_stops(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    with worktrees.locked(project.record):
        assert project.run(apply=True) == 1

    assert "another contribute run is in progress" in capsys.readouterr().out


def test_an_entry_whose_worktree_is_gone_is_forgotten_and_a_merged_branch_deleted(
    project: Project, pushed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/b", "feat: b")
    project.run(branch="feat/b")
    _merge(project, 100, git(pushed, "rev-parse", "HEAD"))
    git(project.repo, "worktree", "remove", "--force", str(pushed))
    git(
        project.repo,
        "worktree",
        "remove",
        "--force",
        str(project.root / "wt" / "feat-b"),
    )

    assert project.run(apply=True) == 0

    assert project.entries() == []
    assert git(project.repo, "branch", "--list", "feat/a") == ""
    assert git(project.repo, "branch", "--list", "feat/b") != ""
    assert "feat/b: worktree is gone; forgotten" in capsys.readouterr().out


def test_an_existing_pr_for_the_branch_is_adopted(project: Project) -> None:
    project.worktree("feat/a", "feat: a")
    git(project.repo, "push", "-q", "origin", "feat/a:" + _remote("feat/a"))
    project.add_pr(7, _remote("feat/a"))
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    assert project.run(apply=True) == 0

    assert [e.pr for e in project.entries()] == [7]


def test_an_existing_pr_with_a_hand_written_why_is_adopted_without_a_recorded_why(
    project: Project,
) -> None:
    project.auto_why = False
    project.worktree("feat/a", "feat: a")
    git(project.repo, "push", "-q", "origin", "feat/a")
    body = "## What\n\n- my own summary\n\n## Why\n\nMy reason.\n"
    project.add_pr(7, "feat/a", body=body)
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    assert project.run(apply=True) == 0

    assert [e.pr for e in project.entries()] == [7]
    assert pr_body(project, 7) == body


def test_an_adopted_pr_gets_the_local_commits_ahead_of_it_pushed(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    git(project.repo, "push", "-q", "origin", "feat/a")
    project.add_pr(7, "feat/a", body="## What\n\n- mine\n\n## Why\n\nx\n")
    project.commit(path, "more.txt", "more\n", "fix: more")
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    assert project.run(apply=True) == 0

    assert git(project.origin, "rev-parse", "feat/a") == git(path, "rev-parse", "HEAD")


def test_a_closed_pr_on_a_reused_branch_is_not_adopted(project: Project) -> None:
    project.worktree("feat/a", "feat: a")
    git(project.repo, "push", "-q", "origin", "feat/a")
    project.add_pr(7, "feat/a", state="CLOSED", body="old")
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    assert project.run(apply=True) == 0

    assert [e.pr for e in project.entries()] == [100]
    assert pr_body(project, 7) == "old"


def test_a_worktree_with_no_commits_is_skipped_by_sync_and_list(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a")
    project.run(branch="feat/a")
    capsys.readouterr()

    assert project.run(apply=True) == 0
    assert contribute.list_targets(project.targets) == 0

    out = capsys.readouterr().out
    assert "feat/a: skipped: no commits" in out
    assert "feat/a  local only  no PR  skipped: no commits" in out
    assert project.main_subjects() == []


def test_a_remote_branch_with_no_commits_is_not_pulled(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    path = project.worktree("feat/a", "feat: a")
    tip = git(path, "rev-parse", "HEAD")
    _land_upstream(project, "upstream.txt")
    git(project.repo, "push", "-q", "origin", "main:" + _remote("feat/a"))
    project.add_pr(7, _remote("feat/a"))
    project.run(branch="feat/a")
    worktrees.save_entries(
        project.record, [e._replace(pr=7, remote_head=tip) for e in project.entries()]
    )
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "feat/a: skipped: the remote branch has no commits" in (
        capsys.readouterr().out
    )
    assert git(path, "rev-parse", "HEAD") == tip


def _key(repo: Path) -> str:
    return str(repo.resolve())


def test_depends_on_links_a_branch_to_another_tools_branch_without_gh(
    project: Project,
) -> None:
    other = project.add_tool("other")
    project.worktree("feat/a", "feat: a")
    project.worktree("feat/b", "feat: b", repo=other)
    project.run(branch="feat/a")
    project.run("other", branch="feat/b")

    assert project.run("other", depends_on=("feat/b", "tool:feat/a")) == 0

    [entry] = project.entries_of(other)
    assert entry.depends_on == (Link(_key(project.repo), "feat/a", ""),)
    assert project.gh_calls() == []


@pytest.fixture
def two_tools(project: Project) -> Path:
    """Branches feat/a in tool and feat/b in other, both recorded."""
    other = project.add_tool("other")
    project.worktree("feat/a", "feat: a")
    project.worktree("feat/b", "feat: b", repo=other)
    project.run(branch="feat/a")
    project.run("other", branch="feat/b")
    return other


def test_a_link_to_an_unknown_tool_or_unrecorded_branch_is_refused(
    project: Project, two_tools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("other", depends_on=("feat/b", "nope:feat/a")) == 1
    assert project.run("other", depends_on=("feat/b", "tool:feat/zzz")) == 1

    out = capsys.readouterr().out
    assert "nope:feat/a: not a TOOL:BRANCH of a locally cloned tool" in out
    assert "tool:feat/zzz: not recorded" in out
    assert project.entries_of(two_tools)[0].depends_on == ()


def test_a_link_that_would_make_a_cycle_is_refused(
    project: Project, two_tools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project.run("other", depends_on=("feat/b", "tool:feat/a"))

    assert project.run("tool", depends_on=("feat/a", "other:feat/b")) == 1

    assert "would make a cycle" in capsys.readouterr().out
    assert project.entries_of(project.repo)[0].depends_on == ()


def test_a_link_is_refused_once_the_dependent_has_a_pr(
    project: Project, two_tools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project.run("other", ready="feat/b")
    project.run(apply=True)

    assert project.run("other", depends_on=("feat/b", "tool:feat/a")) == 1

    assert (
        "feat/b already has PR #100; links must be added before sync opens it"
        in capsys.readouterr().out
    )


@pytest.fixture
def stack(project: Project) -> Path:
    """Recorded feat/a and feat/b, 60 lines each, feat/b one commit on feat/a; returns feat/b's worktree."""
    project.worktree("feat/a", "feat: a", lines=60)
    upper = project.worktree("feat/b", "feat: b", start="feat/a", lines=60)
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    return upper


def test_a_same_repo_link_records_the_lower_tip_as_the_upper_base(
    project: Project, stack: Path
) -> None:
    assert project.run("tool", depends_on=("feat/b", "tool:feat/a")) == 0

    upper = {e.branch: e for e in project.entries()}["feat/b"]
    assert upper.base == git(project.repo, "rev-parse", "feat/a")


def test_a_same_repo_link_is_refused_unless_the_upper_is_on_the_lower(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a", lines=60)
    project.worktree("feat/b", "feat: b", lines=60)
    project.run(branch="feat/a")
    project.run(branch="feat/b")

    assert project.run("tool", depends_on=("feat/b", "tool:feat/a")) == 1

    assert (
        "feat/b is not on feat/a; rebase it onto feat/a first"
        in capsys.readouterr().out
    )


def test_a_same_repo_link_takes_an_upper_of_several_commits(project: Project) -> None:
    project.worktree("feat/a", "feat: a", lines=60)
    project.worktree("feat/b", "feat: b", "feat: b2", start="feat/a", lines=60)
    project.run(branch="feat/a")
    project.run(branch="feat/b")

    assert project.run("tool", depends_on=("feat/b", "tool:feat/a")) == 0

    assert _entry_of(project, "feat/b").base == git(project.repo, "rev-parse", "feat/a")


def _stack_of(project: Project, upper_file: str, upper_content: str | bytes) -> None:
    project.worktree("feat/a", "feat: a", lines=60)
    path = project.worktree("feat/b", start="feat/a")
    target = path / upper_file
    target.parent.mkdir(exist_ok=True)
    if isinstance(upper_content, bytes):
        target.write_bytes(upper_content)
    else:
        target.write_text(upper_content, encoding="utf-8")
    git(path, "add", upper_file)
    git(path, "commit", "-q", "-m", "feat: b")
    project.run(branch="feat/a")
    project.run(branch="feat/b")


def test_a_small_same_repo_stack_is_refused(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    _stack_of(project, "b.txt", "x\n" * 30)

    assert project.run("tool", depends_on=("feat/b", "tool:feat/a")) == 1

    assert (
        "feat/a and feat/b change 90 lines together, within the slightly-yappy "
        "limit of 100. Combine them into one worktree." in capsys.readouterr().out
    )
    assert project.entries()[1].depends_on == ()


def test_a_stack_with_a_binary_file_is_never_refused(project: Project) -> None:
    _stack_of(project, "b.bin", b"\x00\x01\x02")

    assert project.run("tool", depends_on=("feat/b", "tool:feat/a")) == 0


def test_a_file_that_only_ends_like_a_lockfile_name_is_counted(
    project: Project,
) -> None:
    _stack_of(project, "not-uv.lock", "x\n" * 60)
    assert project.run("tool", depends_on=("feat/b", "tool:feat/a")) == 0


def test_a_lockfile_is_not_counted(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    _stack_of(project, "sub/uv.lock", "x\n" * 60)
    assert project.run("tool", depends_on=("feat/b", "tool:feat/a")) == 1
    assert "change 60 lines together" in capsys.readouterr().out


def test_no_depends_on_removes_the_link_and_the_base_so_the_upper_is_skipped_for_holding_the_lowers_commits(
    project: Project, stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))

    assert project.run("tool", no_depends_on=("feat/b", "tool:feat/a")) == 0

    upper = {e.branch: e for e in project.entries()}["feat/b"]
    assert (upper.depends_on, upper.base) == ((), None)
    capsys.readouterr()
    project.run()
    assert "feat/b: skipped: holds commits of feat/a" in capsys.readouterr().out
    assert contribute.list_targets(project.targets) == 0
    assert (
        "feat/b  local only  no PR  skipped: holds commits of feat/a"
        in capsys.readouterr().out
    )


def test_no_depends_on_for_a_link_that_is_not_there_fails(
    project: Project, stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("tool", no_depends_on=("feat/b", "tool:feat/a")) == 1

    assert "feat/b does not depend on tool:feat/a" in capsys.readouterr().out


def pr_body(project: Project, number: int) -> str:
    body: str = project.load_state()["prs"][str(number)]["body"]
    return body


@pytest.fixture
def chain(project: Project, two_tools: Path) -> Path:
    """feat/b in other depends on feat/a in tool; both ready; returns other."""
    project.run("other", depends_on=("feat/b", "tool:feat/a"))
    project.run("other", ready="feat/b")
    return two_tools


def test_a_dependent_waits_until_its_dependency_has_a_pr(
    project: Project, chain: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run(apply=True) == 0

    assert "feat/b: waiting: feat/a has no PR yet" in capsys.readouterr().out
    assert project.gh_calls("pr", "create") == []
    assert project.entries_of(chain)[0].pr is None


def test_a_dependent_opens_in_the_same_run_its_dependency_gets_a_pr_and_names_it(
    project: Project, chain: Path
) -> None:
    project.run("tool", ready="feat/a")

    assert project.run(apply=True) == 0

    [lower] = project.entries_of(project.repo)
    [upper] = project.entries_of(chain)
    assert (lower.pr, upper.pr) == (100, 101)
    assert upper.depends_on == (Link(lower.repo, "feat/a", "o/repo#100"),)
    assert "\nDepends on o/repo#100\n" in pr_body(project, 101)


def test_a_dependent_tool_listed_first_opens_after_its_dependency_in_one_run(
    project: Project, two_tools: Path
) -> None:
    project.run("tool", depends_on=("feat/a", "other:feat/b"))
    project.run("tool", ready="feat/a")
    project.run("other", ready="feat/b")

    assert project.run(apply=True) == 0

    [lower] = project.entries_of(two_tools)
    [upper] = project.entries_of(project.repo)
    assert (lower.pr, upper.pr) == (100, 101)


def test_a_same_repo_stack_opens_in_one_run_lower_first_both_on_main(
    project: Project, stack: Path
) -> None:
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))
    project.run("tool", ready="feat/a")
    project.run("tool", ready="feat/b")
    worktrees.save_entries(project.record, project.entries()[::-1])

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: b"]
    lower, upper = (
        e for b in ("feat/a", "feat/b") for e in project.entries() if e.branch == b
    )
    assert (lower.pr, upper.pr) == (100, 101)
    creates = project.gh_calls("pr", "create")
    assert [c[c.index("--base") + 1] for c in creates] == ["main", "main"]
    assert "Depends on o/repo#100" in pr_body(project, 101)
    assert "Depends on" not in pr_body(project, 100)


@pytest.fixture
def published_stack(project: Project, stack: Path) -> Path:
    """The stack with both branches ready, pushed and drafted; returns the lower's worktree."""
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))
    project.run("tool", ready="feat/a")
    project.run("tool", ready="feat/b")
    project.run(apply=True)
    return project.root / "wt" / "feat-a"


def _entry_of(project: Project, branch: str) -> WorktreeEntry:
    return next(e for e in project.entries() if e.branch == branch)


def test_an_amended_lower_restacks_the_upper_onto_its_new_tip(
    project: Project, published_stack: Path
) -> None:
    new_tip = _amend(project, published_stack, "feat: a amended")

    assert project.run(apply=True) == 0

    upper = _entry_of(project, "feat/b")
    assert git(project.repo, "rev-list", "--count", f"{new_tip}..feat/b") == "1"
    assert git(project.repo, "merge-base", "feat/b", new_tip) == new_tip
    assert upper.base == new_tip
    assert git(project.origin, "rev-parse", _remote("feat/b")) == git(
        project.repo, "rev-parse", "feat/b"
    )


def test_an_upper_whose_worktree_is_gone_is_forgotten_before_restacking(
    project: Project, published_stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _amend(project, published_stack, "feat: a amended")
    git(
        project.repo,
        "worktree",
        "remove",
        "--force",
        str(project.root / "wt" / "feat-b"),
    )

    assert project.run(apply=True) == 0

    assert [e.branch for e in project.entries()] == ["feat/a"]
    assert "feat/b: worktree is gone; forgotten" in capsys.readouterr().out


def test_an_upper_is_kept_when_its_lowers_branch_was_deleted_outside_sync(
    project: Project, published_stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git(project.repo, "worktree", "remove", "--force", str(published_stack))
    git(project.repo, "branch", "-D", "feat/a")

    assert project.run(apply=True) == 0

    assert [e.branch for e in project.entries()] == ["feat/b"]
    assert "feat/a: worktree is gone; forgotten" in capsys.readouterr().out


def _squash_merge_lower(
    project: Project, lower: Path, target: Path | None = None
) -> None:
    """Merge PR 100 on the fake gh and land the lower's change on ``target`` (origin) main as a new commit."""
    _merge(project, 100, git(lower, "rev-parse", "HEAD"))
    other = project.root / "squasher"
    subprocess.run(
        ["git", "clone", "-q", str(target or project.origin), str(other)], check=True
    )
    project.commit(other, "feat-a-7.txt", "feat: a\n" * 60, "feat: a (#100)")
    git(other, "push", "-q", "origin", "main")


def test_a_squash_merged_lower_restacks_the_upper_onto_main_and_is_removed(
    project: Project, published_stack: Path
) -> None:
    _squash_merge_lower(project, published_stack)

    assert project.run(apply=True) == 0

    upper = _entry_of(project, "feat/b")
    assert (upper.depends_on, upper.base) == ((), None)
    assert git(project.repo, "rev-list", "--count", "origin/main..feat/b") == "1"
    assert not published_stack.exists()
    assert [e.branch for e in project.entries()] == ["feat/b"]


def test_a_merged_lower_is_kept_while_a_held_upper_still_sits_on_it(
    project: Project, published_stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _squash_merge_lower(project, published_stack)
    project.add_pr(101, _remote("feat/b"), isDraft=False)
    capsys.readouterr()

    assert project.run(apply=True) == 0

    out = capsys.readouterr().out
    assert "feat/b: not restacked (PR #101 is not a draft)" in out
    assert "feat/a: merged, but feat/b sits on it; kept" in out
    assert published_stack.exists()


def test_a_non_draft_middle_leaves_it_and_everything_above_alone(
    project: Project, published_stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    top = project.worktree("feat/c", "feat: c", start="feat/b", lines=60)
    project.run(branch="feat/c")
    project.run("tool", depends_on=("feat/c", "tool:feat/b"))
    project.run("tool", ready="feat/c")
    project.run(apply=True)
    state = project.load_state()
    state["prs"]["101"]["isDraft"] = False
    project.state = state
    project.save_state()
    middle_tip = git(project.repo, "rev-parse", "feat/b")
    top_tip = git(top, "rev-parse", "HEAD")
    new_tip = _amend(project, published_stack, "feat: a amended")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    out = capsys.readouterr().out
    assert (
        "feat/b: not restacked (PR #101 is not a draft); feat/c left alone too" in out
    )
    assert git(project.repo, "rev-parse", "feat/b") == middle_tip
    assert git(top, "rev-parse", "HEAD") == top_tip
    assert git(project.origin, "rev-parse", _remote("feat/a")) == new_tip


def test_a_repo_with_an_upstream_remote_stacks_and_restacks_against_upstream_main(
    project: Project,
) -> None:
    upstream = project.root / "upstream.git"
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(project.origin), str(upstream)],
        check=True,
    )
    git(project.repo, "remote", "add", "upstream", str(upstream))
    git(project.repo, "fetch", "-q", "upstream")
    project.worktree("feat/a", "feat: a", lines=60)
    project.worktree("feat/b", "feat: b", start="feat/a", lines=60)
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    assert project.run("tool", depends_on=("feat/b", "tool:feat/a")) == 0
    project.run("tool", ready="feat/a")
    project.run("tool", ready="feat/b")
    project.run(apply=True)
    lower = project.root / "wt" / "feat-a"
    _squash_merge_lower(project, lower, upstream)

    assert project.run(apply=True) == 0

    assert git(project.repo, "rev-parse", "feat/b^") == git(
        project.repo, "rev-parse", "upstream/main"
    )
    assert _entry_of(project, "feat/b").base is None


def test_a_links_ref_is_kept_after_its_merged_dependency_is_removed(
    project: Project, chain: Path
) -> None:
    project.run("tool", ready="feat/a")
    lower = project.root / "wt" / "feat-a"
    project.run(apply=True)
    worktrees.save_entries(
        project.record,
        [
            e._replace(depends_on=tuple(l._replace(ref="") for l in e.depends_on))
            for e in project.entries()
        ],
    )
    _merge(project, 100, git(lower, "rev-parse", "HEAD"))

    assert project.run(apply=True) == 0

    assert [e.branch for e in project.entries()] == ["feat/b"]
    assert project.entries()[0].depends_on[0].ref == "o/repo#100"


def _set_body(project: Project, number: int, body: str) -> None:
    state = project.load_state()
    state["prs"][str(number)]["body"] = body
    project.state = state
    project.save_state()


def test_unlinking_removes_only_the_line_sync_wrote_on_the_next_draft_refresh(
    project: Project, chain: Path
) -> None:
    project.run("tool", ready="feat/a")
    project.run(apply=True)
    _set_body(project, 101, pr_body(project, 101) + "\nDepends on someone/else#5\n")

    project.run("other", no_depends_on=("feat/b", "tool:feat/a"))
    assert project.entries_of(chain)[0].dropped_refs == ("o/repo#100",)
    assert project.run(apply=True) == 0

    body = pr_body(project, 101)
    assert "Depends on o/repo#100" not in body
    assert "Depends on someone/else#5" in body
    assert project.entries_of(chain)[0].dropped_refs == ()


def test_an_unlink_waits_for_a_body_update_that_was_blocked(
    project: Project, chain: Path
) -> None:
    project.run("tool", ready="feat/a")
    project.run(apply=True)
    _set_body(project, 101, pr_body(project, 101).replace(WHY, ""))
    project.run("other", why=("feat/b", ""))
    project.run("other", no_depends_on=("feat/b", "tool:feat/a"))

    assert project.run(apply=True) == 1

    assert "Depends on o/repo#100" in pr_body(project, 101)
    assert project.entries_of(chain)[0].dropped_refs == ("o/repo#100",)

    project.run("other", why=("feat/b", WHY))
    assert project.run(apply=True) == 0

    assert "Depends on o/repo#100" not in pr_body(project, 101)


def test_an_adopted_draft_pr_gets_the_depends_on_lines(
    project: Project, chain: Path
) -> None:
    project.run("tool", ready="feat/a")
    git(chain, "push", "-q", "origin", "feat/b:" + _remote("feat/b"))
    project.add_pr(
        7,
        _remote("feat/b"),
        body="## What\n\n- feat: b\n\n## Why\n\nReason.\n\n## Dependencies\n",
    )

    assert project.run(apply=True) == 0

    assert project.entries_of(chain)[0].pr == 7
    assert pr_body(project, 7).endswith("## Dependencies\n\nDepends on o/repo#100\n")


def test_an_adopted_non_draft_pr_is_left_alone_and_named(
    project: Project, chain: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project.run("tool", ready="feat/a")
    git(chain, "push", "-q", "origin", "feat/b:" + _remote("feat/b"))
    project.add_pr(7, _remote("feat/b"), isDraft=False, body="## What\n\n- feat: b\n")

    assert project.run(apply=True) == 0

    assert "feat/b: PR #7 is not a draft; Depends on lines left as they are" in (
        capsys.readouterr().out
    )
    assert project.gh_calls("pr", "edit") == []


def test_rescan_keeps_an_existing_entrys_links_base_and_dropped_refs(
    project: Project, stack: Path
) -> None:
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))
    git(project.repo, "push", "-q", "origin", "feat/b:" + _remote("feat/b"))
    project.add_pr(7, _remote("feat/b"))
    before = _entry_of(project, "feat/b")
    worktrees.save_entries(
        project.record,
        [
            e._replace(dropped_refs=("o/repo#3",)) if e.branch == "feat/b" else e
            for e in project.entries()
        ],
    )

    assert project.run(rescan=True) == 0

    after = _entry_of(project, "feat/b")
    assert after.pr == 7
    assert (after.depends_on, after.base, after.dropped_refs) == (
        before.depends_on,
        before.base,
        ("o/repo#3",),
    )


def test_list_counts_a_stacked_upper_from_its_base(
    project: Project, stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))
    capsys.readouterr()

    assert contribute.list_targets(project.targets) == 0

    assert "feat/b  local only  no PR  60 lines" in capsys.readouterr().out


def test_a_second_same_repo_link_or_a_repeated_link_is_refused(
    project: Project, stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/c", "feat: c", start="feat/b", lines=60)
    project.run(branch="feat/c")
    assert project.run("tool", depends_on=("feat/c", "tool:feat/b")) == 0

    assert project.run("tool", depends_on=("feat/c", "tool:feat/b")) == 1
    assert project.run("tool", depends_on=("feat/c", "tool:feat/a")) == 1

    out = capsys.readouterr().out
    assert "feat/c already depends on tool:feat/b" in out
    assert "feat/c already depends on tool:feat/a" not in out
    assert "feat/c already stacks on another branch of this repo" in out


def test_a_cross_repo_link_keeps_the_stack_base(project: Project, stack: Path) -> None:
    other = project.add_tool("other")
    project.worktree("feat/x", "feat: x", repo=other)
    project.run("other", branch="feat/x")
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))
    base = _entry_of(project, "feat/b").base

    assert project.run("tool", depends_on=("feat/b", "other:feat/x")) == 0

    assert _entry_of(project, "feat/b").base == base is not None


def test_a_merged_lower_whose_worktree_is_gone_is_kept_while_a_held_upper_sits_on_it(
    project: Project, published_stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _squash_merge_lower(project, published_stack)
    project.add_pr(101, _remote("feat/b"), isDraft=False)
    git(project.repo, "worktree", "remove", "--force", str(published_stack))
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "feat/a: merged, but feat/b sits on it; kept" in capsys.readouterr().out
    assert sorted(e.branch for e in project.entries()) == ["feat/a", "feat/b"]
    assert git(project.repo, "branch", "--list", "feat/a") != ""


def test_a_merged_lower_whose_worktree_is_gone_restacks_a_draft_upper_then_goes(
    project: Project, published_stack: Path
) -> None:
    _squash_merge_lower(project, published_stack)
    git(project.repo, "worktree", "remove", "--force", str(published_stack))

    assert project.run(apply=True) == 0

    assert [e.branch for e in project.entries()] == ["feat/b"]
    assert git(project.repo, "rev-list", "--count", "origin/main..feat/b") == "1"
    assert git(project.repo, "branch", "--list", "feat/a") == ""


def test_a_merged_lower_whose_branch_was_deleted_restacks_the_upper_onto_main(
    project: Project, published_stack: Path
) -> None:
    _squash_merge_lower(project, published_stack)
    git(project.repo, "worktree", "remove", "--force", str(published_stack))
    git(project.repo, "branch", "-D", "feat/a")

    assert project.run(apply=True) == 0

    upper = _entry_of(project, "feat/b")
    assert (upper.depends_on, upper.base) == ((), None)
    assert git(project.repo, "rev-list", "--count", "origin/main..feat/b") == "1"


def test_an_unpublished_lower_whose_branch_was_deleted_restacks_the_upper_onto_main(
    project: Project, stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))
    git(
        project.repo,
        "worktree",
        "remove",
        "--force",
        str(project.root / "wt" / "feat-a"),
    )
    git(project.repo, "branch", "-D", "feat/a")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    upper = _entry_of(project, "feat/b")
    assert (upper.depends_on, upper.base) == ((), None)
    assert git(project.repo, "rev-list", "--count", "origin/main..feat/b") == "1"
    assert "feat/b: restacked onto main (feat/a was deleted)" in capsys.readouterr().out


def test_a_deleted_unpublished_lower_is_kept_until_a_dirty_upper_can_restack(
    project: Project, stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))
    git(
        project.repo,
        "worktree",
        "remove",
        "--force",
        str(project.root / "wt" / "feat-a"),
    )
    git(project.repo, "branch", "-D", "feat/a")
    dirty = project.root / "wt" / "feat-b" / "scratch.txt"
    dirty.write_text("wip\n")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "feat/b: not restacked (the worktree has uncommitted changes)" in (
        capsys.readouterr().out
    )
    dirty.unlink()

    assert project.run(apply=True) == 0

    upper = _entry_of(project, "feat/b")
    assert (upper.depends_on, upper.base) == ((), None)
    assert git(project.repo, "rev-list", "--count", "origin/main..feat/b") == "1"
    assert [e.branch for e in project.entries()] == ["feat/b"]


def test_a_stack_on_a_lower_of_several_commits_is_squashed_into_two_main_commits(
    project: Project,
) -> None:
    project.worktree("feat/a", "feat: a", "feat: a2", lines=40)
    project.worktree("feat/b", "feat: b", start="feat/a", lines=40)
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: b"]


def test_a_stacked_upper_is_replayed_after_its_lower_even_when_its_old_copy_sits_first(
    project: Project,
) -> None:
    project.commit(project.repo, "shared.txt", "L1\n-\n-\n-\nL2\n", "chore: shared")
    git(project.repo, "push", "-q", "origin", "main")
    for name, shared in (("b", "L1\n-\n-\n-\nB2\n"), ("a", "A1\n-\n-\n-\nL2\n")):
        path = project.worktree(f"feat/{name}", start="origin/main")
        (path / f"pad-{name}.txt").write_text("x\n" * 60, encoding="utf-8")
        git(path, "add", f"pad-{name}.txt")
        project.commit(path, "shared.txt", shared, f"feat: {name}")
        project.run(branch=f"feat/{name}")
        assert project.run(apply=True) == 0
    upper = project.root / "wt" / "feat-b"
    git(upper, "rebase", "feat/a")
    project.clock += 60
    (upper / "shared.txt").write_text("AB1\n-\n-\n-\nB2\n", encoding="utf-8")
    git(
        upper,
        "commit",
        "-qa",
        "--amend",
        "--no-edit",
        "--date",
        f"{project.clock} +0000",
    )
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: b"]
    assert (project.repo / "shared.txt").read_text(
        encoding="utf-8"
    ) == "AB1\n-\n-\n-\nB2\n"


def test_an_amended_upper_copy_in_an_ordered_stack_is_replaced_in_place(
    project: Project, published_stack: Path
) -> None:
    edited = project.root / "wt" / "feat-b" / "feat-b-7.txt"
    lines = edited.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[30] = "local edit\n"
    project.commit(project.repo, edited.name, "".join(lines), "chore: local edit")
    _amend(project, project.root / "wt" / "feat-b", "feat: b amended")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == [
        "feat: a",
        "feat: b amended",
        "chore: local edit",
    ]


def test_branches_stacked_above_a_moved_branch_move_with_it(
    project: Project,
) -> None:
    project.worktree("feat/a", "feat: a", lines=60)
    middle = project.worktree("feat/b", "feat: b", start="feat/a", lines=60)
    project.worktree("feat/c", "feat: c", start="feat/b", lines=60)
    for name in "abc":
        project.run(branch=f"feat/{name}")
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))
    project.run("tool", depends_on=("feat/c", "tool:feat/b"))
    assert project.run(apply=True) == 0
    _amend(project, middle, "feat: b amended")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: b amended", "feat: c"]


def test_restack_moves_an_upper_onto_an_amended_lower_of_several_commits(
    project: Project,
) -> None:
    lower = project.worktree("feat/a", "feat: a", "feat: a2", lines=40)
    upper = project.worktree("feat/b", "feat: b", start="feat/a", lines=40)
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    project.run("tool", depends_on=("feat/b", "tool:feat/a"))
    project.run(apply=True)
    new_tip = _amend(project, lower, "feat: a2 amended")

    assert project.run(apply=True) == 0

    assert git(upper, "rev-parse", "HEAD~1") == new_tip
    assert _entry_of(project, "feat/b").base == new_tip
    assert project.main_subjects() == ["feat: a", "feat: b"]


def test_restack_moves_an_upper_of_several_commits(
    project: Project, published_stack: Path
) -> None:
    upper = project.root / "wt" / "feat-b"
    project.commit(upper, "extra.txt", "x\n", "feat: extra")
    new_tip = _amend(project, published_stack, "feat: a amended")

    assert project.run(apply=True) == 0

    assert git(upper, "rev-parse", "HEAD~2") == new_tip
    assert git(upper, "log", "--format=%s", f"{new_tip}..HEAD") == (
        "feat: extra\nfeat: b"
    )
    assert _entry_of(project, "feat/b").base == new_tip


def test_restack_holds_an_upper_that_is_no_longer_on_its_base(
    project: Project, published_stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    upper = project.root / "wt" / "feat-b"
    git(upper, "rebase", "-q", "--onto", "origin/main", "feat/a")
    top_tip = git(upper, "rev-parse", "HEAD")
    _amend(project, published_stack, "feat: a amended")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "feat/b: not restacked (it is not on its base)" in capsys.readouterr().out
    assert git(upper, "rev-parse", "HEAD") == top_tip


def test_restack_holds_an_upper_paused_in_a_rebase_of_its_own(
    project: Project, published_stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    upper = project.root / "wt" / "feat-b"
    subprocess.run(
        ["git", "-C", str(upper), "rebase", "-q", "-i", "feat/a"],
        env={**os.environ, "GIT_SEQUENCE_EDITOR": "sed -i '1i break'"},
        check=True,
    )
    paused = git(upper, "rev-parse", "--git-path", "rebase-merge")
    _amend(project, published_stack, "feat: a amended")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "feat/b: not restacked (a rebase is in progress)" in capsys.readouterr().out
    assert (upper / paused).exists()


def test_restack_only_records_the_base_of_an_upper_already_rebased_by_hand(
    project: Project, published_stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    upper = project.root / "wt" / "feat-b"
    old_base = _entry_of(project, "feat/b").base
    new_tip = _amend(project, published_stack, "feat: a amended")
    git(upper, "rebase", "-q", "--onto", new_tip, old_base or "")
    tip = git(upper, "rev-parse", "HEAD")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "feat/b: restacked" not in capsys.readouterr().out
    assert _entry_of(project, "feat/b").base == new_tip
    assert git(upper, "rev-parse", "HEAD") == tip


def test_unlinking_a_non_draft_pr_keeps_its_line_and_the_record_and_says_so(
    project: Project, chain: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project.run("tool", ready="feat/a")
    project.run(apply=True)
    state = project.load_state()
    state["prs"]["101"]["isDraft"] = False
    project.state = state
    project.save_state()
    project.run("other", no_depends_on=("feat/b", "tool:feat/a"))
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "feat/b: PR #101 is not a draft; Depends on lines left as they are" in (
        capsys.readouterr().out
    )
    assert "Depends on o/repo#100" in pr_body(project, 101)
    assert project.entries_of(chain)[0].dropped_refs == ("o/repo#100",)
