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
from unittest.mock import patch

import pytest

from llm_prompts import cli, contribute, github_api, main_sync, setup, worktrees
from llm_prompts.contribute import (
    Commit,
    SyncOptions,
    empty_sections_message,
    pr_title,
)
from llm_prompts.exit_reason import ExitReason
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

    def commit(
        self, repo: Path, name: str, content: str, message: str, encoding: str = "utf-8"
    ) -> str:
        (repo / name).write_text(content, encoding=encoding)
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
                "title",
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


def copy_recorded(project: Project) -> int:
    """Copy the recorded worktrees into main the way `update` does, and save the record."""
    status, updated = contribute.copy_recorded(
        project.repo, project.entries(), (), "tool"
    )
    worktrees.save_entries(project.record, updated)
    return status


def test_copying_recorded_worktrees_puts_the_ready_ones_in_main_and_sends_nothing_to_github(
    project: Project,
) -> None:
    project.worktree("feat/a", "feat: a")
    project.worktree("feat/b", "feat: b")
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    project.run(ready="feat/b")

    assert copy_recorded(project) == 0

    assert project.main_subjects() == ["feat: b"]
    assert project.remote_branches() == []
    assert project.gh_calls() == []

    copied = git(project.repo, "rev-parse", "main")

    assert copy_recorded(project) == 0

    assert git(project.repo, "rev-parse", "main") == copied


def test_copying_stops_on_a_recorded_branch_that_is_gone(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.worktree("feat/b", "feat: b")
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    git(project.repo, "worktree", "remove", "--force", str(path))
    git(project.repo, "branch", "-D", "feat/a")

    assert copy_recorded(project) == 1

    assert "feat/a: the branch is gone" in capsys.readouterr().out
    assert project.main_subjects() == []
    assert [e.branch for e in project.entries()] == ["feat/a", "feat/b"]


def configure_sources(project: Project, test: str = "", ref: str = "") -> None:
    """Point the config at every cloned tool of ``project``, each with the test command ``test`` and the ref ``ref``."""
    test_line = f"test = {json.dumps(test)}\n" if test else ""
    ref_line = f"ref = {json.dumps(ref)}\n" if ref else ""
    setup.config_path().write_text(
        "".join(
            f'[[tools]]\nname = "{name}"\nsource = "{repo}"\n{test_line}{ref_line}'
            for name, repo, _ in project.targets
        ),
        encoding="utf-8",
    )


def recording_test_command(project: Project, returncode: int) -> tuple[str, Path]:
    """Return a test command that logs the directory it runs in, and the log it appends to."""
    log = project.root / "test-runs.log"
    script = project.root / "record_test.py"
    script.write_text(
        "import os, sys\n"
        f"open({str(log)!r}, 'a').write(os.getcwd() + '\\n')\n"
        f"sys.exit({returncode})\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {script}", log


def run_update(project: Project) -> Any:
    """Run ``llm-prompts update`` with only the copying of recorded worktrees real, and return the install mock."""
    with (
        patch("sys.argv", ["llm-prompts", "update"]),
        patch(
            "llm_prompts.manifest.read_manifest", return_value={"kiro": {"files": []}}
        ),
        patch("llm_prompts.setup.detect_stale_local_tools", return_value=set()),
        patch("llm_prompts.setup.run_setup", return_value=False),
        patch("llm_prompts.install.main", return_value=frozenset()) as install,
        patch("llm_prompts.plugins.pull_plugin_sources"),
    ):
        cli.main()
    return install


def test_update_copies_ready_worktrees_into_main_though_upstream_has_nothing_new(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_sources(project)
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")
    capsys.readouterr()

    assert cli._pull_local_sources() == {"tool"}

    assert project.main_subjects() == ["feat: a"]
    assert "[tool] feat/a: copied into main" in capsys.readouterr().out
    assert project.remote_branches() == []
    assert project.gh_calls() == []
    assert cli._pull_local_sources() == set()


def test_update_says_when_main_has_no_copy_code_to_add_the_recorded_copies_next_time(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    own = project.add_tool("llm-prompts")
    configure_sources(project)
    project.worktree("feat/a", "feat: a", repo=own)
    project.run("llm-prompts", branch="feat/a")

    cli._pull_local_sources()

    assert (
        "[llm-prompts] main has no copy-into-main code, so the next update cannot add "
        "recorded copies: feat/a" in capsys.readouterr().out
    )
    (own / "src/llm_prompts").mkdir(parents=True)
    project.commit(
        own, "src/llm_prompts/contribute.py", "def copy_recorded(): ...\n", "feat: copy"
    )

    cli._pull_local_sources()

    assert "no copy-into-main code" not in capsys.readouterr().out


def test_list_stops_on_a_held_lock(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    capsys.readouterr()

    with worktrees.locked(project.record):
        assert contribute.list_targets(project.targets) == 1

    assert "another contribute run is in progress" in capsys.readouterr().out


def test_update_stops_on_a_held_lock_without_touching_any_source(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_sources(project)
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")

    with worktrees.locked(project.record), pytest.raises(ExitReason) as stopped:
        cli._pull_local_sources()

    assert stopped.value.reason == "record_locked"
    assert "another contribute run is in progress" in capsys.readouterr().out
    assert project.main_subjects() == []


def test_update_still_reinstalls_when_a_copy_conflicts_and_names_the_worktree(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_sources(project)
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")
    (path / "base.txt").write_text("worktree\n", encoding="utf-8")
    git(path, "commit", "-q", "-am", "feat: a edits base")
    project.commit(project.repo, "base.txt", "main\n", "feat: main edits base")
    before = git(project.repo, "rev-parse", "main")

    with (
        patch("sys.argv", ["llm-prompts", "update"]),
        patch(
            "llm_prompts.manifest.read_manifest", return_value={"kiro": {"files": []}}
        ),
        patch("llm_prompts.setup.detect_stale_local_tools", return_value=set()),
        patch("llm_prompts.setup.run_setup", return_value=False),
        patch("llm_prompts.install.main", return_value=frozenset()) as install,
        patch("llm_prompts.plugins.pull_plugin_sources"),
    ):
        cli.main()

    install.assert_called_once()
    assert git(project.repo, "rev-parse", "main") == before
    out = capsys.readouterr().out
    work = main_sync.resolve_worktree(project.repo)
    assert "[tool] main not updated: " in out
    assert f"left in {work}: resolve the files there, git add them, then rerun" in out
    assert git(work, "diff", "--name-only", "--diff-filter=U") == "base.txt"


def test_update_stops_when_a_copy_fails_with_its_own_reason(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_sources(project)
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")

    with (
        patch(
            "llm_prompts.contribute.copy_recorded",
            side_effect=subprocess.CalledProcessError(1, "git", stderr="boom"),
        ),
        pytest.raises(ExitReason) as stopped,
    ):
        run_update(project)

    assert stopped.value.reason == "copy_failed"
    assert "Update stopped: tool" in capsys.readouterr().out


def test_update_warns_about_a_failing_test_after_a_copy_and_still_reinstalls(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    command, log = recording_test_command(project, returncode=1)
    configure_sources(project, command)
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    install = run_update(project)

    install.assert_called_once()
    assert project.main_subjects() == ["feat: a"]
    assert f"[tool] warning: `{command}` failed on the synced main" in (
        capsys.readouterr().out
    )
    assert [Path(line) for line in log.read_text().splitlines()] == [
        project.repo.resolve()
    ]


def test_update_stops_before_pulling_when_a_source_is_not_on_main(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_sources(project)
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    git(project.repo, "switch", "-q", "-c", "elsewhere")

    with pytest.raises(ExitReason) as stopped:
        cli._pull_local_sources()

    assert stopped.value.reason == "copy_blocked"
    assert "[tool] elsewhere is checked out, not main" in capsys.readouterr().out
    assert project.main_subjects() == []


def _publish_release(project: Project) -> None:
    """Tag base as v0.1.0, then publish a v0.2.0 release and an unreleased commit to origin main from another clone."""
    git(project.repo, "tag", "v0.1.0")
    git(project.repo, "push", "-q", "origin", "v0.1.0")
    other = project.root / "upstream-clone"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "pyproject.toml", "two\n", "feat: two")
    project.commit(
        other,
        "CHANGELOG.md",
        "## [0.2.0](https://x) (2026-02-01)\n\n* two\n",
        "chore: release 0.2.0",
    )
    git(other, "tag", "v0.2.0")
    project.commit(other, "later.txt", "later\n", "feat: unreleased")
    git(other, "push", "-q", "--tags", "origin", "main")


def test_update_moves_main_to_the_latest_release_with_copies_on_top(
    project: Project,
) -> None:
    configure_sources(project)
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")
    _publish_release(project)

    run_update(project)

    assert git(project.repo, "log", "--format=%s", "main").splitlines() == [
        "feat: a",
        "chore: release 0.2.0",
        "feat: two",
        "chore: base",
    ]


def test_update_moves_a_main_ahead_of_the_release_back_onto_it_keeping_local_commits(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_sources(project)
    _publish_release(project)
    git(project.repo, "pull", "-q", "--ff-only")
    project.commit(project.repo, "local.txt", "local\n", "feat: local")

    run_update(project)

    assert git(project.repo, "log", "--format=%s", "main").splitlines() == [
        "feat: local",
        "chore: release 0.2.0",
        "feat: two",
        "chore: base",
    ]
    assert "[tool] moved to release v0.2.0" in capsys.readouterr().out


def test_a_worktree_on_the_release_is_copied_when_origin_main_is_ahead_of_it(
    project: Project,
) -> None:
    configure_sources(project)
    _publish_release(project)
    run_update(project)
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    assert project.run(apply=True) == 0

    assert git(project.repo, "log", "--format=%s", "main").splitlines()[0] == "feat: a"


def test_sync_rebuilds_main_on_a_release_published_since_the_last_update(
    project: Project,
) -> None:
    _publish_release(project)
    git(project.repo, "fetch", "-q", "origin", "refs/tags/v0.1.0:refs/tags/v0.1.0")
    main_sync.point_upstream(project.repo)
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert git(project.repo, "log", "--format=%s", "main").splitlines()[:2] == [
        "feat: a",
        "chore: release 0.2.0",
    ]


def test_update_runs_the_source_test_after_moving_main_back_onto_the_release(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_sources(project, test="false")
    _publish_release(project)
    git(project.repo, "pull", "-q", "--ff-only")
    project.commit(project.repo, "local.txt", "local\n", "feat: local")

    run_update(project)

    assert "[tool] warning: `false`" in capsys.readouterr().out


def test_first_sync_of_a_configured_source_rebuilds_main_on_the_latest_release(
    project: Project,
) -> None:
    configure_sources(project)
    _publish_release(project)
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert git(project.repo, "log", "--format=%s", "main").splitlines()[:2] == [
        "feat: a",
        "chore: release 0.2.0",
    ]


def test_update_shows_the_release_change_with_its_changelog(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_sources(project)
    _publish_release(project)

    run_update(project)

    assert (
        "[tool] update available (v0.1.0 -> v0.2.0):\n"
        "- ## [0.2.0](https://x) (2026-02-01)\n  * two\n"
    ) in capsys.readouterr().out


def test_update_with_a_ref_follows_that_branch_instead_of_releases(
    project: Project,
) -> None:
    configure_sources(project, ref="main")
    _publish_release(project)

    run_update(project)

    assert git(project.repo, "rev-parse", "main") == git(
        project.repo, "rev-parse", "origin/main"
    )


def test_update_with_a_ref_keeps_commits_that_are_only_on_the_tracked_branch(
    project: Project,
) -> None:
    git(project.repo, "push", "-q", "origin", "main:dev")
    configure_sources(project, ref="dev")
    _land_upstream(project, "main-only.txt")

    run_update(project)

    assert (
        git(project.repo, "log", "-1", "--format=%s", "main") == "chore: main-only.txt"
    )


def test_update_without_release_tags_follows_the_upstream_branch(
    project: Project,
) -> None:
    configure_sources(project)
    _land_upstream(project, "upstream.txt", pull=False)

    run_update(project)

    assert git(project.repo, "rev-parse", "main") == git(
        project.repo, "rev-parse", "origin/main"
    )


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


def _main_with_empty_commits(project: Project) -> None:
    """Land ``feat: a (#5)`` and ``feat: b (#6)`` upstream, then put an empty recorded copy of ``feat: a``, a real commit and a deliberate empty ``feat: b`` on local main."""
    other = project.root / "upstream-clone"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "a.txt", "a\n", "feat: a (#5)")
    project.commit(other, "b.txt", "b\n", "feat: b (#6)")
    git(other, "push", "-q", "origin", "main")
    git(project.repo, "pull", "-q", "--ff-only")
    for subject in ("feat: a", "feat: b"):
        project.clock += 60
        git(
            project.repo,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            subject,
            "--date",
            f"{project.clock} +0000",
        )
        if subject == "feat: a":
            copy = git(project.repo, "log", "-1", "--format=%at%x09%s")
            project.commit(project.repo, "keep.txt", "keep\n", "feat: keep")
    worktrees.save_entries(
        worktrees.record_path(),
        [
            WorktreeEntry(
                str(project.repo),
                "feat/a",
                str(project.root / "gone"),
                5,
                "MERGED",
                None,
                copied=copy,
            )
        ],
    )


def test_update_drops_a_recorded_empty_copy_of_a_merged_pr_and_keeps_a_deliberate_empty_commit(
    project: Project,
) -> None:
    _main_with_empty_commits(project)

    outcome = cli._pull_one_local_source("tool", str(project.repo))

    assert outcome.changed
    assert project.main_subjects() == ["feat: keep", "feat: b"]
    assert git(project.repo, "rev-parse", main_sync.PRE_SYNC_REF)


def _main_ahead_of_a_release(project: Project) -> None:
    _publish_release(project)
    git(project.repo, "pull", "-q", "--ff-only")
    project.commit(project.repo, "local.txt", "local\n", "feat: local")


@pytest.mark.parametrize("setup", [_main_ahead_of_a_release, _main_with_empty_commits])
def test_update_reports_a_waiting_conflict_and_leaves_main(
    project: Project, setup: Any
) -> None:
    setup(project)
    work = main_sync.resolve_worktree(project.repo)
    git(project.repo, "worktree", "add", "-q", "--detach", str(work), "HEAD")
    one = project.commit(work, "base.txt", "one\n", "feat: one")
    git(work, "checkout", "-q", "HEAD~1")
    project.commit(work, "base.txt", "two\n", "feat: two")
    with pytest.raises(subprocess.CalledProcessError):
        git(work, "cherry-pick", "--no-commit", one)
    main = git(project.repo, "rev-parse", "main")

    outcome = cli._pull_one_local_source("tool", str(project.repo))

    assert not outcome.changed
    assert (
        "[tool] main not updated: main left untouched: conflicts in"
        in (outcome.messages[0])
    )
    assert git(project.repo, "rev-parse", "main") == main


def test_sync_keeps_a_deliberate_empty_commit_sharing_a_merged_prs_subject(
    project: Project,
) -> None:
    _main_with_empty_commits(project)
    worktrees.save_entries(worktrees.record_path(), [])

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: keep", "feat: b"]


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


@pytest.mark.parametrize("record", ["saved", "upgraded", "rebased"])
def test_a_file_removed_from_a_worktree_since_its_copy_leaves_main(
    project: Project, record: str
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.commit(path, "extra.txt", "more\n", "feat: extra")
    project.run(branch="feat/a")
    project.run(apply=True)
    if record != "saved":
        worktrees.save_entries(
            project.record, [e._replace(copied_tip=None) for e in project.entries()]
        )
    if record == "rebased":
        _land_upstream(project, "upstream.txt", pull=False)
        git(project.repo, "fetch", "-q")
        git(path, "rebase", "-q", "origin/main")
    git(path, "rm", "-q", "extra.txt")
    git(path, "commit", "-q", "-m", "fix: drop extra")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert not (project.repo / "extra.txt").exists()


@pytest.mark.parametrize(
    ("name", "content"), [("f.txt", "1\n2\n3\nupstream\n"), ("g.txt", "1\n2\n3\n4\n")]
)
def test_an_edit_reverted_in_a_worktree_since_its_copy_leaves_main_though_upstream_edited_or_renamed_the_file(
    project: Project, name: str, content: str
) -> None:
    project.commit(project.repo, "f.txt", "1\n2\n3\n4\n", "chore: f")
    git(project.repo, "push", "-q", "origin", "main")
    path = project.worktree("feat/a", "feat: a")
    project.commit(path, "f.txt", "1\nlocal\n3\n4\n", "feat: f")
    project.run(branch="feat/a")
    project.run(apply=True)
    other = project.root / "upstream-clone"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    if name != "f.txt":
        git(other, "mv", "f.txt", name)
    project.commit(other, name, content, "chore: upstream")
    git(other, "push", "-q", "origin", "main")
    project.run(apply=True)
    project.commit(path, "f.txt", "1\n2\n3\n4\n", "fix: revert f")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / name).read_text(encoding="utf-8") == content


@pytest.mark.parametrize("shared", ["main", "record", "skipped"])
def test_main_is_left_unchanged_when_a_file_removed_from_a_worktree_was_in_a_copy_it_shares(
    project: Project, shared: str
) -> None:
    at = str(project.clock + 60)
    if shared == "main":
        _commit_at(project.repo, "other.txt", "feat: a", at)
    path = project.worktree("feat/a", start="origin/main")
    _commit_at(path, "a.txt", "feat: a", at)
    project.commit(path, "extra.txt", "more\n", "feat: extra")
    project.run(branch="feat/a")
    project.run(apply=True)
    if shared != "main":
        project.worktree(
            "feat/b",
            "feat: b",
            "feat: b2",
            "feat: b33",
            start="main" if shared == "skipped" else "origin/main",
        )
        project.run(branch="feat/b")
        [copied] = [e.copied for e in project.entries() if e.branch == "feat/a"]
        worktrees.save_entries(
            project.record,
            [
                e._replace(copied=copied) if e.branch == "feat/b" else e
                for e in project.entries()
            ],
        )
    git(path, "rm", "-q", "extra.txt")
    git(path, "commit", "-q", "-m", "fix: drop extra")
    main = git(project.repo, "rev-parse", "main")

    assert project.run(apply=True) == 1

    assert git(project.repo, "rev-parse", "main") == main


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


def test_update_copies_the_recorded_remote_head_that_merged_a_newer_main_over_a_stale_local_branch(
    project: Project,
) -> None:
    path = project.worktree("feat/a")
    project.commit(path, "base.txt", "branch\n", "feat: a")
    stale = git(path, "rev-parse", "HEAD")
    project.run(branch="feat/a")
    worktrees.save_entries(
        project.record, [e._replace(ready=True) for e in project.entries()]
    )
    other = project.root / "other"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "base.txt", "main\n", "feat: upstream")
    git(other, "push", "-q", "origin", "main")
    git(project.repo, "fetch", "-q", "origin")
    git(path, "merge", "-q", "-s", "ours", "--no-edit", "origin/main")
    project.commit(path, "base.txt", "both\n", "fix: a")
    head = git(path, "rev-parse", "HEAD")
    git(path, "reset", "-q", "--hard", stale)
    worktrees.save_entries(
        project.record, [e._replace(remote_head=head) for e in project.entries()]
    )

    assert copy_recorded(project) == 0

    assert not main_sync.resolve_worktree(project.repo).exists()
    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "base.txt").read_text(encoding="utf-8") == "both\n"


def test_update_skips_a_worktree_whose_recorded_remote_head_cannot_be_fetched(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    missing = "0" * 40
    worktrees.save_entries(
        project.record,
        [e._replace(ready=True, remote_head=missing) for e in project.entries()],
    )

    copy_recorded(project)

    assert project.main_subjects() == []
    assert f"its remote head {missing} could not be fetched" in capsys.readouterr().out


def test_an_unrelated_main_commit_titled_like_a_later_worktree_commit_is_kept(
    project: Project,
) -> None:
    project.commit(project.repo, "other.txt", "other\n", "feat: a2")
    project.worktree("feat/a", "feat: a", "feat: a2", start="origin/main")
    project.run(branch="feat/a")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a2", "feat: a"]


def stopped_copy(project: Project) -> main_sync.Squash:
    """A squash that conflicts with local main, left in the resolve worktree."""
    repo = project.repo
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "feat")
    tip = project.commit(repo, "base.txt", "feature\n", "feat: feature")
    git(repo, "checkout", "-q", "main")
    project.commit(repo, "base.txt", "main\n", "feat: main")
    squash = main_sync.Squash(tip=tip, floor=base, first=tip)
    assert main_sync.rebuild_local(repo, base, {}, (), {}, [squash]).mode == "stopped"
    return squash


@pytest.fixture
def hand_staged(project: Project) -> main_sync.Squash:
    """A squash that conflicts with local main, with its hand resolution staged in the resolve worktree."""
    squash = stopped_copy(project)
    work = main_sync.resolve_worktree(project.repo)
    (work / "base.txt").write_text("resolved\n", encoding="utf-8")
    (work / "related.txt").write_text("fix\n", encoding="utf-8")
    git(work, "add", "base.txt", "related.txt")
    return squash


@pytest.fixture
def hand_resolved(project: Project, hand_staged: main_sync.Squash) -> main_sync.Squash:
    """A squash that conflicts with local main, after its hand resolution was recorded and reused once."""
    rebuilt = main_sync.rebuild_local(
        project.repo, hand_staged.floor, {}, (), {}, [hand_staged]
    )
    assert rebuilt.mode == "rebuilt"
    assert not main_sync.resolve_worktree(project.repo).exists()
    return hand_staged


def test_a_recorded_hand_resolution_settles_the_next_rebuild(
    project: Project, hand_resolved: main_sync.Squash
) -> None:
    assert (project.repo / "base.txt").read_text(encoding="utf-8") == "resolved\n"
    assert (project.repo / "related.txt").read_text(encoding="utf-8") == "fix\n"
    assert project.main_subjects() == ["feat: main", "feat: feature"]


@pytest.mark.parametrize(
    ("name", "hidden"),
    [
        ("base.txt", ""),
        ("note.txt", ""),
        ("note.txt", "ignored"),
        ("note.txt", "status.showUntrackedFiles"),
    ],
)
def test_a_hand_resolution_with_unstaged_work_stays_in_its_worktree(
    project: Project, hand_staged: main_sync.Squash, name: str, hidden: str
) -> None:
    work = main_sync.resolve_worktree(project.repo)
    if hidden == "ignored":
        exclude = Path(git(work, "rev-parse", "--git-path", "info/exclude"))
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text(f"{name}\n", encoding="utf-8")
    elif hidden:
        git(project.repo, "config", hidden, "no")
    (work / name).write_text("unstaged\n", encoding="utf-8")
    main = git(project.repo, "rev-parse", "main")

    rebuilt = main_sync.rebuild_local(
        project.repo, hand_staged.floor, {}, (), {}, [hand_staged]
    )

    assert rebuilt.mode == "stopped"
    assert git(project.repo, "rev-parse", "main") == main
    assert (work / name).read_text(encoding="utf-8") == "unstaged\n"


def test_a_second_conflict_takes_the_resolve_worktree_after_the_first_is_resolved(
    project: Project,
) -> None:
    repo = project.repo
    base = git(repo, "rev-parse", "HEAD")
    squashes = []
    for name in ("a.txt", "b.txt"):
        git(repo, "checkout", "-q", "-b", name, base)
        tip = project.commit(repo, name, f"feature {name}\n", f"feat: {name}")
        squashes.append(main_sync.Squash(tip=tip, floor=base, first=tip))
    git(repo, "checkout", "-q", "main")
    project.commit(repo, "a.txt", "main\n", "feat: main a")
    project.commit(repo, "b.txt", "main\n", "feat: main b")
    work = main_sync.resolve_worktree(repo)
    for name in ("a.txt", "b.txt"):
        assert (
            main_sync.rebuild_local(repo, base, {}, (), {}, squashes).mode == "stopped"
        )
        (work / name).write_text("resolved\n", encoding="utf-8")
        git(work, "add", name)

    assert main_sync.rebuild_local(repo, base, {}, (), {}, squashes).mode == "rebuilt"

    assert (repo / "a.txt").read_text(encoding="utf-8") == "resolved\n"
    assert (repo / "b.txt").read_text(encoding="utf-8") == "resolved\n"
    assert not work.exists()


def test_a_resolve_worktree_without_its_merge_named_stays(
    project: Project, hand_staged: main_sync.Squash
) -> None:
    work = main_sync.resolve_worktree(project.repo)
    Path(git(work, "rev-parse", "--git-path", "llm-prompts-resolution")).unlink()
    main = git(project.repo, "rev-parse", "main")

    rebuilt = main_sync.rebuild_local(
        project.repo, hand_staged.floor, {}, (), {}, [hand_staged]
    )

    assert rebuilt.mode == "stopped"
    assert git(project.repo, "rev-parse", "main") == main
    assert (work / "related.txt").read_text(encoding="utf-8") == "fix\n"


def test_a_hand_resolution_stays_in_its_worktree_until_its_merge_comes_up(
    project: Project, hand_staged: main_sync.Squash
) -> None:
    repo = project.repo
    project.commit(repo, "base.txt", "moved\n", "feat: main moves")
    main = git(repo, "rev-parse", "main")

    rebuilt = main_sync.rebuild_local(
        repo, hand_staged.floor, {}, (), {}, [hand_staged]
    )

    assert rebuilt.mode == "stopped"
    assert git(repo, "rev-parse", "main") == main
    work = main_sync.resolve_worktree(repo)
    assert (work / "base.txt").read_text(encoding="utf-8") == "resolved\n"


def test_a_hand_resolution_that_keeps_main_leaves_main_as_it_is(
    project: Project,
) -> None:
    squash = stopped_copy(project)
    work = main_sync.resolve_worktree(project.repo)
    (work / "base.txt").write_text("main\n", encoding="utf-8")
    git(work, "add", "base.txt")
    main = git(project.repo, "rev-parse", "main")

    rebuilt = main_sync.rebuild_local(project.repo, squash.floor, {}, (), {}, [squash])

    assert rebuilt.mode == "rebuilt"
    assert git(project.repo, "rev-parse", "main") == main
    assert not work.exists()


def test_a_hand_resolution_that_keeps_main_replays_onto_an_unrelated_main_change(
    project: Project,
) -> None:
    squash = stopped_copy(project)
    work = main_sync.resolve_worktree(project.repo)
    (work / "base.txt").write_text("main\n", encoding="utf-8")
    git(work, "add", "base.txt")
    assert (
        main_sync.rebuild_local(project.repo, squash.floor, {}, (), {}, [squash]).mode
        == "rebuilt"
    )
    project.commit(project.repo, "other.txt", "other\n", "feat: main other")

    rebuilt = main_sync.rebuild_local(project.repo, squash.floor, {}, (), {}, [squash])

    assert rebuilt.mode == "rebuilt"
    assert project.main_subjects() == ["feat: main", "feat: main other"]


def test_a_hand_resolution_that_keeps_main_stays_when_main_changes_its_conflict(
    project: Project,
) -> None:
    squash = stopped_copy(project)
    work = main_sync.resolve_worktree(project.repo)
    (work / "base.txt").write_text("main\n", encoding="utf-8")
    git(work, "add", "base.txt")
    project.commit(project.repo, "base.txt", "moved\n", "feat: main moves")
    main = git(project.repo, "rev-parse", "main")

    rebuilt = main_sync.rebuild_local(project.repo, squash.floor, {}, (), {}, [squash])

    assert rebuilt.mode == "stopped"
    assert git(project.repo, "rev-parse", "main") == main
    assert work.exists()


@pytest.mark.parametrize("resolved", ["feature\n", "resolved\n"])
def test_a_staged_hand_resolution_reaches_main_or_stays_when_the_branch_merges_cleanly(
    project: Project, resolved: str
) -> None:
    squash = stopped_copy(project)
    work = main_sync.resolve_worktree(project.repo)
    (work / "base.txt").write_text(resolved, encoding="utf-8")
    (work / "related.txt").write_text("fix\n", encoding="utf-8")
    git(work, "add", "base.txt", "related.txt")
    project.commit(project.repo, "base.txt", "feature\n", "feat: main takes it")

    rebuilt = main_sync.rebuild_local(project.repo, squash.floor, {}, (), {}, [squash])

    assert rebuilt.mode == "rebuilt"
    applied = resolved == "feature\n"
    assert (project.repo / "related.txt").exists() == applied
    assert work.exists() != applied


def test_a_hand_resolution_that_keeps_main_in_one_file_stays_when_main_changes_it(
    project: Project,
) -> None:
    repo = project.repo
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "feat")
    project.commit(repo, "a.txt", "feature\n", "feat: feature a")
    tip = project.commit(repo, "b.txt", "feature\n", "feat: feature b")
    git(repo, "checkout", "-q", "main")
    project.commit(repo, "a.txt", "main\n", "feat: main a")
    project.commit(repo, "b.txt", "main\n", "feat: main b")
    squash = main_sync.Squash(tip=tip, floor=base, first=tip)
    assert main_sync.rebuild_local(repo, base, {}, (), {}, [squash]).mode == "stopped"
    work = main_sync.resolve_worktree(repo)
    (work / "a.txt").write_text("main\n", encoding="utf-8")
    (work / "b.txt").write_text("resolved\n", encoding="utf-8")
    git(work, "add", "a.txt", "b.txt")
    assert main_sync.rebuild_local(repo, base, {}, (), {}, [squash]).mode == "rebuilt"
    project.commit(repo, "a.txt", "moved\n", "feat: main moves a")
    main = git(repo, "rev-parse", "main")

    rebuilt = main_sync.rebuild_local(repo, base, {}, (), {}, [squash])

    assert rebuilt.mode == "stopped"
    assert git(repo, "rev-parse", "main") == main
    assert work.exists()


def test_a_staged_hand_resolution_replays_onto_an_unrelated_main_change(
    project: Project, hand_staged: main_sync.Squash
) -> None:
    project.commit(project.repo, "other.txt", "other\n", "feat: main other")

    rebuilt = main_sync.rebuild_local(
        project.repo, hand_staged.floor, {}, (), {}, [hand_staged]
    )

    assert rebuilt.mode == "rebuilt"
    assert (project.repo / "related.txt").read_text(encoding="utf-8") == "fix\n"
    assert not main_sync.resolve_worktree(project.repo).exists()


def test_a_hand_resolved_copy_is_current(
    project: Project, hand_resolved: main_sync.Squash
) -> None:
    assert main_sync.replays_to(project.repo, "main^", hand_resolved, "main")
    assert not main_sync.replays_to(project.repo, "main^", hand_resolved, "main^")


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
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    assert project.run() == 0
    assert "feat/a: would push and open a draft PR" in capsys.readouterr().out
    assert project.remote_branches() == []
    assert project.gh_calls("pr", "create") == []

    assert project.run(apply=True) == 0

    tip = git(project.repo, "rev-parse", "feat/a")
    assert git(project.origin, "rev-parse", _remote("feat/a")) == tip
    assert project.remote_branches() == ["tester/contribute/feat/a"]
    assert git(path, "branch", "--show-current") == "feat/a"
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
    [pr] = project.load_state()["prs"].values()
    assert pr["headRefName"] == "tester/contribute/feat/a"


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


def test_a_recorded_title_names_the_pr_sync_opens(project: Project) -> None:
    project.worktree("feat/a", "feat: a", "fix: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")
    project.run(title=("feat/a", "feat: add a"))

    assert project.run(apply=True) == 0

    [create] = project.gh_calls("pr", "create")
    assert create[create.index("--title") + 1] == "feat: add a"


def test_the_pr_what_leaves_merge_commits_out(project: Project) -> None:
    path = project.worktree("feat/a", "feat: a")
    git(path, "checkout", "-q", "-b", "side", "main")
    project.commit(path, "other.txt", "x\n", "chore: side")
    git(path, "checkout", "-q", "feat/a")
    git(path, "merge", "-q", "--no-ff", "-m", "Merge side into feat/a", "side")
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    assert project.run(apply=True) == 0

    [create] = project.gh_calls("pr", "create")
    body = create[create.index("--body") + 1]
    assert "- feat: a" in body
    assert "- chore: side" in body
    assert "Merge side" not in body


def test_a_root_commit_has_its_subject_and_is_no_merge(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    git(
        tmp_path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "root",
    )

    commit = contribute._commit_of(tmp_path, "HEAD")

    assert (commit.subject, commit.is_merge) == ("root", False)


def test_a_pr_of_only_merge_commits_still_lists_them_in_what() -> None:
    commits = [Commit("a", "Merge side into feat/a", (), is_merge=True)]

    assert pr_title(commits) == "Merge side into feat/a"
    assert "- Merge side into feat/a" in contribute.pr_body("## What\n", commits)


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
        "feat/a: not opened, PR section Why is empty. Set Why with: "
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
        "feat/a: PR #100 body left as it is, PR section Why is empty. Set Why with: "
        'llm-prompts contribute sync --tool tool --why feat/a "<why>"'
    ) in capsys.readouterr().out

    project.run(why=("feat/a", WHY))
    assert project.run(apply=True) == 0

    assert f"## Why\n\n{WHY}\n" in pr_body(project, 100)


def test_empty_sections_message_suggests_only_the_relevant_flag() -> None:
    assert empty_sections_message(["What", "Why"], "tool", "feat/a") == (
        "PR sections What and Why are empty. Set Why with: "
        'llm-prompts contribute sync --tool tool --why feat/a "<why>"'
    )


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


def test_a_recorded_title_replaces_one_sync_wrote_but_not_one_edited_by_hand(
    project: Project, pushed: Path
) -> None:
    project.run(title=("feat/a", "feat: add a"))
    assert project.run(apply=True) == 0
    assert project.load_state()["prs"]["100"]["title"] == "feat: add a"

    _set_title(project, 100, "My own title")
    project.run(title=("feat/a", "feat: add a better a"))
    assert project.run(apply=True) == 0

    assert project.load_state()["prs"]["100"]["title"] == "My own title"


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


def _merge(project: Project, number: int, oid: str, land: bool = False) -> None:
    """Merge PR ``number`` at ``oid``, landing its squash on origin main when ``land``."""
    state = project.load_state()
    state["prs"][str(number)].update(state="MERGED", headRefOid=oid)
    project.state = state
    project.save_state()
    git(project.origin, "branch", "-D", _remote("feat/a"))
    if land:
        squash = git(
            project.origin,
            "commit-tree",
            f"{oid}^{{tree}}",
            "-p",
            "main",
            "-m",
            f"feat: a (#{number})",
        )
        git(project.origin, "update-ref", "refs/heads/main", squash)


def test_a_merged_worktree_is_removed_with_its_branch_and_entry(
    project: Project, pushed: Path
) -> None:
    _merge(project, 100, git(pushed, "rev-parse", "HEAD"), land=True)

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
    assert "lines (over the 100-line guideline)" in out.splitlines()[2]
    assert (
        "feat/d  local only  no PR  2 commits, 120 lines (over the 100-line guideline)"
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


def test_the_main_copy_of_a_merged_worktree_stays_when_it_restores_a_file_an_earlier_local_commit_deletes(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    copy = git(project.repo, "rev-parse", "main")
    git(project.repo, "reset", "-q", "--hard", "origin/main")
    git(project.repo, "rm", "-q", "base.txt")
    git(project.repo, "commit", "-qm", "chore: drop base")
    git(project.repo, "cherry-pick", "-n", copy)
    git(project.repo, "checkout", "origin/main", "--", "base.txt")
    git(project.repo, "commit", "-q", "-C", copy)
    project.add_pr(
        7, "feat/a", state="MERGED", headRefOid=git(path, "rev-parse", "HEAD")
    )
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "feat: a\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["chore: drop base", "feat: a"]
    assert (project.repo / "base.txt").read_text(encoding="utf-8") == "base\n"


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
    project.commit(other, "feat-a-7.txt", "feat: a\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == []


def test_the_main_copy_of_a_merged_worktree_stays_until_a_release_holds_its_squash(
    project: Project,
) -> None:
    git(project.repo, "tag", "v0.1.0")
    main_sync.point_upstream(project.repo)
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

    assert project.main_subjects() == ["feat: a"]


def test_sync_does_not_call_main_stale_for_a_copy_merged_after_the_release_it_follows(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    git(project.repo, "tag", "v0.1.0")
    main_sync.point_upstream(project.repo)
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "feat: a\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")
    capsys.readouterr()

    assert project.run(apply=True) == 0

    assert "already merged upstream" not in capsys.readouterr().out


def test_a_merged_worktree_is_kept_until_the_main_rebuild_that_drops_its_copy_succeeds(
    project: Project, monkeypatch: pytest.MonkeyPatch
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
    project.commit(other, "feat-a-7.txt", "feat: a\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")
    real_run_git = main_sync.run_git
    with monkeypatch.context() as broken:
        broken.setattr(
            main_sync,
            "run_git",
            lambda repo, *args, **kwargs: (
                subprocess.CompletedProcess(args, 1, "", "no")
                if args[0] == "update-ref"
                else real_run_git(repo, *args, **kwargs)
            ),
        )
        assert project.run(apply=True) == 1

    assert project.main_subjects() == ["feat: a"]
    assert git(project.repo, "branch", "--list", "feat/a") != ""

    assert project.run(apply=True) == 0

    assert project.main_subjects() == []
    assert git(project.repo, "branch", "--list", "feat/a") == ""
    assert project.entries() == []


def test_the_main_copy_of_a_merged_worktree_is_dropped_though_review_changed_its_tree_and_the_record_lacks_its_copied_tip(
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
        project.record,
        [e._replace(pr=7, copied_tip=None) for e in project.entries()],
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "feat: a\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == []


def test_the_main_copy_of_a_merged_worktree_stays_when_its_pr_reverted_it(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    git(path, "revert", "--no-edit", "HEAD")
    head = project.commit(path, "review.txt", "review\n", "fix: review")
    project.add_pr(7, "feat/a", state="MERGED", headRefOid=head)
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "review.txt", "review\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "feat-a-7.txt").exists()


def test_the_main_copy_of_a_merged_worktree_stays_when_an_open_worktree_shares_its_first_commit_and_reverts_it(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    first = git(path, "rev-parse", "HEAD")
    project.run(branch="feat/a")
    project.run(apply=True)
    git(path, "revert", "--no-edit", "HEAD")
    head = project.commit(path, "review.txt", "review\n", "fix: review")
    project.add_pr(7, "feat/a", state="MERGED", headRefOid=head)
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    upper = project.worktree("feat/b", start="origin/main")
    git(upper, "cherry-pick", "-x", first)
    project.commit(upper, "feat-b-7.txt", "feat: b\n", "feat: b")
    git(upper, "revert", "--no-edit", "HEAD~1")
    project.run(branch="feat/b")
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "review.txt", "review\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: a"]
    assert (project.repo / "feat-a-7.txt").exists()
    assert (project.repo / "feat-b-7.txt").exists()


def test_the_main_copy_of_a_merged_worktree_stays_when_an_open_worktree_copied_with_its_identity_reverts_it(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    upper = project.worktree("feat/b", start="origin/main")
    git(upper, "cherry-pick", "-x", git(path, "rev-parse", "HEAD"))
    project.commit(upper, "feat-b-7.txt", "feat: b\n", "feat: b")
    project.run(branch="feat/b")
    project.run(apply=True)
    project.run(branch="feat/a")
    project.run(apply=True)
    git(path, "revert", "--no-edit", "HEAD")
    head = project.commit(path, "review.txt", "review\n", "fix: review")
    project.add_pr(7, "feat/a", state="MERGED", headRefOid=head)
    worktrees.save_entries(
        project.record,
        [e._replace(pr=7) if e.branch == "feat/a" else e for e in project.entries()],
    )
    git(upper, "revert", "--no-edit", "HEAD~1")
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "review.txt", "review\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")
    copied = [e for e in project.entries() if e.branch == "feat/b"]

    assert project.run(apply=True) == 1

    assert (project.repo / "feat-a-7.txt").exists()
    assert (project.repo / "feat-b-7.txt").exists()
    assert [e for e in project.entries() if e.branch == "feat/b"] == copied


def test_main_is_left_unchanged_when_a_main_copy_holds_changes_of_a_merged_and_an_open_worktree_that_moved_on(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    path = project.worktree("feat/a", "feat: a")
    upper = project.worktree("feat/b", start="origin/main")
    git(upper, "cherry-pick", "-x", git(path, "rev-parse", "HEAD"))
    project.commit(upper, "b.txt", "b\n", "feat: b")
    project.run(branch="feat/b")
    project.run(apply=True)
    project.run(branch="feat/a")
    project.run(apply=True)
    project.add_pr(
        7, "feat/a", state="MERGED", headRefOid=git(path, "rev-parse", "HEAD")
    )
    worktrees.save_entries(
        project.record,
        [e._replace(pr=7) if e.branch == "feat/a" else e for e in project.entries()],
    )
    git(upper, "revert", "--no-edit", "HEAD")
    project.commit(upper, "c.txt", "c\n", "feat: c")
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "feat: a\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")
    main = git(project.repo, "rev-parse", "main")
    copies = [(e.branch, e.copied, e.copied_tip) for e in project.entries()]
    capsys.readouterr()

    assert project.run(apply=True) == 1

    out = capsys.readouterr().out
    assert "feat/b" in out
    assert "feat/a" in out
    assert git(project.repo, "rev-parse", "main") == main
    assert [(e.branch, e.copied, e.copied_tip) for e in project.entries()] == copies


@pytest.mark.parametrize("reverted", [False, True])
def test_the_main_copy_of_a_merged_worktree_held_upstream_is_dropped_and_an_open_worktree_with_its_identity_refreshes_its_own_copy_unless_that_loses_changes(
    project: Project, reverted: bool
) -> None:
    path = project.worktree("feat/a", "feat: a", "feat: a2")
    project.run(branch="feat/a")
    project.run(apply=True)
    upper = project.worktree("feat/b", start="origin/main")
    git(upper, "cherry-pick", "-x", git(path, "rev-parse", "HEAD~1"))
    git(upper, "rm", "-q", "feat-a-7.txt")
    (upper / "a2.txt").write_text("a2\n", encoding="utf-8")
    git(upper, "add", "a2.txt")
    git(upper, "commit", "-q", "--amend", "--no-edit")
    project.commit(upper, "b.txt", "b\n", "feat: b")
    project.run(branch="feat/b")
    project.run(apply=True)
    project.add_pr(
        7, "feat/a", state="MERGED", headRefOid=git(path, "rev-parse", "HEAD")
    )
    worktrees.save_entries(
        project.record,
        [e._replace(pr=7) if e.branch == "feat/a" else e for e in project.entries()],
    )
    if reverted:
        git(upper, "revert", "--no-edit", "HEAD~1")
    project.commit(upper, "b2.txt", "b2\n", "feat: b2")
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    for name in ("feat-a-7.txt", "feat-a-8.txt"):
        (other / name).write_text(
            (path / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
        git(other, "add", name)
    git(other, "commit", "-qm", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")
    main = git(project.repo, "rev-parse", "main")

    assert project.run(apply=True) == reverted

    assert (project.repo / "a2.txt").exists()
    if reverted:
        assert git(project.repo, "rev-parse", "main") == main
    else:
        assert project.main_subjects() == ["feat: a"]
        assert (project.repo / "b2.txt").exists()


def test_main_is_left_unchanged_when_a_merged_copy_holds_an_unpublished_edit_next_to_a_line_its_replacement_changes(
    project: Project,
) -> None:
    project.commit(project.repo, "f.txt", "1\n2\n3\n4\n", "chore: f")
    git(project.repo, "push", "-q", "origin", "main")
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    upper = project.worktree("feat/b", start="origin/main")
    git(upper, "cherry-pick", "-x", git(path, "rev-parse", "HEAD"))
    git(upper, "rm", "-q", "feat-a-7.txt")
    (upper / "f.txt").write_text("1\nlocal\n3\n4\n", encoding="utf-8")
    git(upper, "commit", "-qa", "--amend", "--no-edit")
    project.run(branch="feat/b")
    project.run(apply=True)
    project.add_pr(
        7, "feat/a", state="MERGED", headRefOid=git(path, "rev-parse", "HEAD")
    )
    worktrees.save_entries(
        project.record,
        [e._replace(pr=7) if e.branch == "feat/a" else e for e in project.entries()],
    )
    (upper / "f.txt").write_text("1\n2\nupper\n4\n", encoding="utf-8")
    git(upper, "commit", "-qa", "--amend", "--no-edit")
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "feat: a\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")
    main = git(project.repo, "rev-parse", "main")

    assert project.run(apply=True) == 1

    assert git(project.repo, "rev-parse", "main") == main


def test_main_is_left_unchanged_when_an_open_worktree_that_claimed_a_merged_copy_conflicts_with_its_landed_squash_though_a_resolution_keeps_upstream(
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
    upper = project.worktree("feat/b", start="origin/main")
    git(upper, "cherry-pick", "-x", git(path, "rev-parse", "HEAD"))
    project.commit(upper, "feat-b-7.txt", "feat: b\n", "feat: b")
    project.run(branch="feat/b")
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "landed\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")
    git(project.repo, "fetch", "-q", "origin")
    rerere = ("-c", "rerere.enabled=true")
    git(upper, "checkout", "-q", "--detach", "origin/main")
    with pytest.raises(subprocess.CalledProcessError):
        git(upper, *rerere, "cherry-pick", git(path, "rev-parse", "HEAD"))
    (upper / "feat-a-7.txt").write_text("landed\n", encoding="utf-8")
    git(upper, "add", "feat-a-7.txt")
    git(upper, *rerere, "rerere")
    git(upper, "cherry-pick", "--abort")
    git(upper, "checkout", "-q", "feat/b")
    main = git(project.repo, "rev-parse", "main")

    assert project.run(apply=True) == 1

    assert git(project.repo, "rev-parse", "main") == main
    assert (upper / "feat-b-7.txt").exists()


@pytest.mark.parametrize(
    ("gone", "recorded"), [(False, True), (True, True), (True, False)]
)
def test_the_main_copy_of_a_merged_worktree_stays_when_it_conflicts_with_its_pr_though_a_resolution_was_recorded(
    project: Project, gone: bool, recorded: bool
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    copy = git(path, "rev-parse", "HEAD")
    git(path, "reset", "-q", "--hard", "HEAD~1")
    head = project.commit(path, "feat-a-7.txt", "reviewed\n", "feat: a")
    rerere = ("-c", "rerere.enabled=true")
    with pytest.raises(subprocess.CalledProcessError):
        git(path, *rerere, "cherry-pick", copy)
    (path / "feat-a-7.txt").write_text("reviewed\n", encoding="utf-8")
    git(path, "add", "feat-a-7.txt")
    git(path, *rerere, "rerere")
    git(path, "cherry-pick", "--abort")
    if gone:
        git(project.repo, "worktree", "remove", "--force", str(path))
        git(project.repo, "branch", "-D", "feat/a")
    project.add_pr(7, "feat/a", state="MERGED", headRefOid=head)
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries() if recorded]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "reviewed\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    for _ in range(2):
        assert project.run(apply=True) == 1

        assert project.main_subjects() == ["feat: a"]
        assert (project.repo / "feat-a-7.txt").read_text(
            encoding="utf-8"
        ) == "feat: a\n"
    assert [e.branch for e in project.entries()] == ["feat/a"] * recorded


def test_a_deleted_merged_worktree_keeps_its_record_and_main_copy_across_the_release_that_holds_its_squash(
    project: Project,
) -> None:
    git(project.repo, "tag", "v0.1.0")
    main_sync.point_upstream(project.repo)
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    copy = git(path, "rev-parse", "HEAD")
    git(path, "reset", "-q", "--hard", "HEAD~1")
    head = project.commit(path, "feat-a-7.txt", "reviewed\n", "feat: a")
    rerere = ("-c", "rerere.enabled=true")
    with pytest.raises(subprocess.CalledProcessError):
        git(path, *rerere, "cherry-pick", copy)
    (path / "feat-a-7.txt").write_text("reviewed\n", encoding="utf-8")
    git(path, "add", "feat-a-7.txt")
    git(path, *rerere, "rerere")
    git(path, "cherry-pick", "--abort")
    git(project.repo, "worktree", "remove", "--force", str(path))
    git(project.repo, "branch", "-D", "feat/a")
    project.add_pr(7, "feat/a", state="MERGED", headRefOid=head)
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "reviewed\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert [e.branch for e in project.entries()] == ["feat/a"]
    git(other, "tag", "v0.2.0")
    git(other, "push", "-q", "origin", "v0.2.0")
    git(project.repo, "fetch", "-q", "--tags", "origin")
    main_sync.point_upstream(project.repo)

    assert project.run(apply=True) == 1

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "feat-a-7.txt").read_text(encoding="utf-8") == "feat: a\n"
    assert [e.branch for e in project.entries()] == ["feat/a"]


def test_a_merged_copy_whose_squash_is_not_released_yet_replays_without_a_recorded_resolution(
    project: Project,
) -> None:
    git(project.repo, "tag", "v0.1.0")
    main_sync.point_upstream(project.repo)
    path = project.worktree("feat/a", "feat: a")
    project.commit(path, "b.txt", "b\n", "feat: b")
    project.run(branch="feat/a")
    project.run(apply=True)
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "feat-a-7.txt", "upstream\n", "feat: other")
    git(other, "tag", "v0.2.0")
    project.commit(other, "landed.txt", "landed\n", "feat: a (#7)")
    git(other, "push", "-q", "--tags", "origin", "main")
    git(project.repo, "fetch", "-q", "--tags", "origin")
    main_sync.point_upstream(project.repo)
    rerere = ("-c", "rerere.enabled=true")
    git(path, "checkout", "-q", "--detach", "v0.2.0")
    with pytest.raises(subprocess.CalledProcessError):
        git(path, *rerere, "cherry-pick", git(project.repo, "rev-parse", "main"))
    (path / "feat-a-7.txt").write_text("upstream\n", encoding="utf-8")
    git(path, "add", "feat-a-7.txt")
    git(path, *rerere, "rerere")
    git(path, "cherry-pick", "--abort")
    git(path, "checkout", "-q", "feat/a")
    project.add_pr(
        7, "feat/a", state="MERGED", headRefOid=git(path, "rev-parse", "HEAD")
    )
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )

    assert project.run(apply=True) == 1

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "feat-a-7.txt").read_text(encoding="utf-8") == "feat: a\n"


def test_the_main_copy_of_a_merged_worktree_stays_when_it_holds_a_commit_its_pr_lacks_and_the_branch_moved_on(
    project: Project,
) -> None:
    path = project.worktree("feat/a", "feat: a")
    copied = project.commit(path, "b.txt", "b\n", "feat: b")
    project.run(branch="feat/a")
    project.run(apply=True)
    git(path, "reset", "-q", "--hard", "HEAD~1")
    head = project.commit(path, "review.txt", "review\n", "fix: review")
    git(path, "reset", "-q", "--hard", copied)
    project.commit(path, "c.txt", "c\n", "feat: c")
    project.add_pr(7, "feat/a", state="MERGED", headRefOid=head)
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "landed.txt", "reviewed\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "b.txt").exists()


@pytest.mark.parametrize(("held", "subjects"), [(True, []), (False, ["feat: a"])])
def test_the_main_copy_of_a_merged_worktree_whose_branch_moved_on_is_dropped_only_when_the_landed_squash_holds_it(
    project: Project, held: bool, subjects: list[str]
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    head = project.commit(path, "review.txt", "review\n", "fix: review")
    git(path, "reset", "-q", "--hard", "HEAD~1")
    project.commit(path, "b.txt", "b\n", "feat: b")
    project.add_pr(7, "feat/a", state="MERGED", headRefOid=head)
    worktrees.save_entries(
        project.record, [e._replace(pr=7) for e in project.entries()]
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    if held:
        (other / "feat-a-7.txt").write_text("feat: a\n", encoding="utf-8")
        git(other, "add", "feat-a-7.txt")
    project.commit(other, "review.txt", "review\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == subjects
    assert (project.repo / "feat-a-7.txt").read_text(encoding="utf-8") == "feat: a\n"


def test_the_main_copy_of_a_merged_worktree_behind_its_pr_is_dropped_though_a_changed_open_worktree_shares_its_first_commit(
    project: Project,
) -> None:
    lower = project.worktree("feat/a", "feat: a", "feat: a2")
    upper = project.worktree(
        "feat/b", "feat: b", start=git(lower, "rev-parse", "HEAD~1")
    )
    project.run(branch="feat/a")
    project.run(branch="feat/b")
    project.run(apply=True)
    _commit_at(
        project.repo,
        "other.txt",
        "feat: a",
        git(lower, "log", "-1", "--format=%at", "HEAD~1"),
    )
    head = project.commit(lower, "review.txt", "review\n", "fix: review")
    git(lower, "reset", "-q", "--hard", "HEAD~1")
    project.add_pr(7, "feat/a", state="MERGED", headRefOid=head)
    worktrees.save_entries(
        project.record,
        [e._replace(pr=7) if e.branch == "feat/a" else e for e in project.entries()],
    )
    other = project.root / "squasher"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    for name in ("feat-a-7.txt", "feat-a-8.txt"):
        (other / name).write_text(
            (lower / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
        git(other, "add", name)
    project.commit(other, "review.txt", "review\n", "feat: a (#7)")
    git(other, "push", "-q", "origin", "main")
    project.commit(upper, "b2.txt", "b2\n", "feat: b2")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "feat: a"]
    assert (project.repo / "b2.txt").exists()
    assert (project.repo / "other.txt").exists()


def test_the_main_copy_of_a_merged_worktree_stays_when_review_changed_its_tree_and_another_commit_shares_its_identity(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    path = project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    (path / "feat-a-7.txt").write_text("reviewed\n", encoding="utf-8")
    git(path, "add", "feat-a-7.txt")
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
    project.commit(other, "feat-a-7.txt", "feat: a\n", "feat: a (#7)")
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


@pytest.fixture
def swapped(project: Project) -> Path:
    """Main holds copies of feat/x, feat/y and feat/z, then feat/x is rewritten so feat/y's copy conflicts; returns the resolve worktree path."""
    lines = [f"line {n}\n" for n in range(40)]

    def shared(edits: dict[int, str]) -> str:
        return "".join(edits.get(n, line) for n, line in enumerate(lines))

    project.commit(project.repo, "shared.txt", shared({}), "chore: shared")
    git(project.repo, "push", "-q", "origin", "main")
    x = project.worktree("feat/x")
    project.commit(x, "shared.txt", shared({10: "x\n"}), "feat: x")
    y = project.worktree("feat/y")
    project.commit(y, "shared.txt", shared({20: "y\n"}), "feat: y")
    project.worktree("feat/z", "feat: z")
    for branch in ("feat/x", "feat/y", "feat/z"):
        project.run(branch=branch)
    assert project.run(apply=True) == 0
    (x / "shared.txt").write_text(
        shared({n: "x\n" for n in range(10, 21)}), encoding="utf-8"
    )
    git(x, "commit", "-q", "-a", "--amend", "--no-edit")
    return main_sync.resolve_worktree(project.repo)


def test_a_conflicting_copy_stops_sync_in_a_kept_worktree(
    project: Project, swapped: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = git(project.repo, "rev-parse", "main")
    capsys.readouterr()

    assert project.run(apply=True) == 1

    out = capsys.readouterr().out
    assert "(feat: y) conflicts with main in shared.txt" in out
    assert str(swapped) in out
    assert git(project.repo, "rev-parse", "main") == before
    assert git(swapped, "diff", "--name-only", "--diff-filter=U") == "shared.txt"


def test_a_rerun_records_the_hand_resolution_and_finishes_the_rebuild(
    project: Project, swapped: Path
) -> None:
    project.run(apply=True)
    resolved = (swapped / "shared.txt").read_text(encoding="utf-8")
    resolved = (
        resolved.split("<<<<<<<")[0]
        + "resolved\n"
        + resolved.split(">>>>>>>")[1].split("\n", 1)[1]
    )
    (swapped / "shared.txt").write_text(resolved, encoding="utf-8")
    git(swapped, "add", "shared.txt")

    assert project.run(apply=True) == 0

    assert not swapped.exists()
    assert project.main_subjects() == ["feat: x", "feat: y", "feat: z"]
    assert (project.repo / "shared.txt").read_text(encoding="utf-8") == resolved


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
    _merge(project, 100, git(pushed, "rev-parse", "HEAD"), land=True)
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


_OWN_BODY = "## What\n\n- my own summary\n\n## Why\n\nMy reason.\n"


@pytest.mark.parametrize(
    ("head", "body"),
    [(_remote("feat/a"), ""), (_remote("feat/a"), _OWN_BODY), ("feat/a", _OWN_BODY)],
)
def test_an_existing_pr_for_the_branch_is_adopted_with_or_without_a_recorded_why(
    project: Project, head: str, body: str
) -> None:
    project.auto_why = not body
    project.worktree("feat/a", "feat: a")
    git(project.repo, "push", "-q", "origin", f"feat/a:{head}")
    project.add_pr(7, head, body=body)
    project.run(branch="feat/a")
    project.run(ready="feat/a")

    assert project.run(apply=True) == 0

    assert [e.pr for e in project.entries()] == [7]
    if head == "feat/a":
        assert pr_body(project, 7) == body


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


def test_a_same_repo_link_is_refused(
    project: Project, stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("tool", depends_on=("feat/b", "tool:feat/a")) == 1

    assert (
        "tool:feat/a is in the same repo: put feat/b's change in feat/a's worktree"
        in capsys.readouterr().out
    )
    assert _entry_of(project, "feat/b").depends_on == ()


def test_a_forced_same_repo_link_is_recorded_with_a_warning(
    project: Project, stack: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert project.run("tool", depends_on=("feat/b", "tool:feat/a"), force=True) == 0

    assert (
        "warning: tool:feat/a is in the same repo, recorded as a stacked PR"
        in capsys.readouterr().out
    )
    assert [link.branch for link in _entry_of(project, "feat/b").depends_on] == [
        "feat/a"
    ]


def test_depends_on_a_pr_of_an_unmanaged_repo_writes_its_line_and_no_depends_on_removes_it(
    project: Project,
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")

    assert project.run(depends_on=("feat/a", "o/ci#23")) == 0
    project.run(ready="feat/a")
    assert project.run(apply=True) == 0

    [entry] = project.entries()
    assert entry.depends_on == (Link("", "", "o/ci#23"),)
    assert "\nDepends on o/ci#23\n" in pr_body(project, entry.pr or 0)
    assert project.run(no_depends_on=("feat/a", "o/ci#23")) == 0
    assert project.entries()[0].depends_on == ()


def test_a_pr_reference_link_reaches_a_branch_that_already_has_a_draft_pr(
    project: Project,
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")
    project.run(apply=True)

    assert project.run(depends_on=("feat/a", "o/ci#23")) == 0
    assert project.run(apply=True) == 0

    [entry] = project.entries()
    assert "\nDepends on o/ci#23\n" in pr_body(project, entry.pr or 0)


def test_a_pr_reference_link_is_refused_once_the_pr_is_ready(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")
    project.run(apply=True)
    [entry] = project.entries()
    state = project.load_state()
    state["prs"][str(entry.pr)]["isDraft"] = False
    project.state = state
    project.save_state()
    capsys.readouterr()

    assert project.run(depends_on=("feat/a", "o/ci#23")) == 1

    assert f"PR #{entry.pr} is not a draft" in capsys.readouterr().out
    assert project.entries()[0].depends_on == ()


@pytest.mark.parametrize(
    ("states", "reason"),
    [
        (subprocess.CalledProcessError(1, "gh", stderr="boom"), "boom"),
        ({}, "GitHub did not return it"),
    ],
)
def test_a_pr_reference_link_is_refused_when_the_draft_check_fails(
    project: Project,
    capsys: pytest.CaptureFixture[str],
    states: Any,
    reason: str,
) -> None:
    project.worktree("feat/a", "feat: a")
    project.run(branch="feat/a")
    project.run(ready="feat/a")
    project.run(apply=True)
    [entry] = project.entries()
    capsys.readouterr()

    with patch.object(contribute, "pr_states", side_effect=[states]):
        assert project.run(depends_on=("feat/a", "o/ci#23")) == 1

    out = capsys.readouterr().out
    assert f"PR #{entry.pr} draft state not checked ({reason})" in out
    assert project.entries()[0].depends_on == ()


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


def test_a_pr_link_to_a_branch_dependency_writes_its_depends_on_line_once(
    project: Project, chain: Path
) -> None:
    project.run("tool", ready="feat/a")
    project.run(apply=True)

    assert project.run("other", depends_on=("feat/b", "o/repo#100")) == 0
    assert project.run(apply=True) == 0

    assert pr_body(project, 101).count("Depends on o/repo#100") == 1


def _entry_of(project: Project, branch: str) -> WorktreeEntry:
    return next(e for e in project.entries() if e.branch == branch)


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
    _merge(project, 100, git(lower, "rev-parse", "HEAD"), land=True)

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


def test_rescan_keeps_an_existing_entrys_links_and_dropped_refs(
    project: Project, stack: Path
) -> None:
    git(project.repo, "push", "-q", "origin", "feat/b:" + _remote("feat/b"))
    project.add_pr(7, _remote("feat/b"))
    worktrees.save_entries(
        project.record,
        [
            e._replace(
                depends_on=(Link("/elsewhere", "feat/x", "o/else#2"),),
                dropped_refs=("o/repo#3",),
            )
            if e.branch == "feat/b"
            else e
            for e in project.entries()
        ],
    )

    assert project.run(rescan=True) == 0

    after = _entry_of(project, "feat/b")
    assert after.pr == 7
    assert (after.depends_on, after.dropped_refs) == (
        (Link("/elsewhere", "feat/x", "o/else#2"),),
        ("o/repo#3",),
    )


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


def test_a_changed_branch_replaces_its_hand_resolved_copy_on_main(
    project: Project,
) -> None:
    body = "".join(f"line {n}\n" for n in range(9))
    project.commit(project.repo, "s.txt", body, "chore: add s")
    git(project.repo, "push", "-q", "origin", "main")
    project.commit(
        project.repo, "s.txt", body.replace("line 1", "local"), "chore: local"
    )
    path = project.worktree("feat/a", start="origin/main")
    project.commit(path, "s.txt", body.replace("line 1", "a"), "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    work = main_sync.resolve_worktree(project.repo)
    resolved = body.replace("line 1", "local a")
    (work / "s.txt").write_text(resolved, encoding="utf-8")
    git(work, "add", "s.txt")
    assert project.run(apply=True) == 0
    project.commit(
        path, "s.txt", body.replace("line 1", "a").replace("line 7", "b"), "fix: a"
    )

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["chore: local", "feat: a"]
    assert (project.repo / "s.txt").read_text(encoding="utf-8") == resolved.replace(
        "line 7", "b"
    )


def test_a_changed_branch_replaces_every_top_up_copy_on_main(
    project: Project,
) -> None:
    body = "".join(f"line {n}\n" for n in range(9))
    project.commit(project.repo, "s.txt", body, "chore: add s")
    git(project.repo, "push", "-q", "origin", "main")
    path = project.worktree("feat/a", start="origin/main")
    project.commit(path, "s.txt", body.replace("line 1", "a"), "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    date = git(project.repo, "log", "-1", "--format=%ad", "--date=raw", "main")
    (project.repo / "s.txt").write_text(
        body.replace("line 1", "a").replace("line 3", "top"), encoding="utf-8"
    )
    git(project.repo, "commit", "-q", "-am", "feat: a", "--date", date)
    fixed = body.replace("line 1", "a").replace("line 3", "top").replace("line 7", "b")
    project.commit(path, "s.txt", fixed, "fix: a")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a"]
    assert (project.repo / "s.txt").read_text(encoding="utf-8") == fixed


def test_a_same_identity_main_commit_whose_changes_the_branch_lacks_is_kept(
    project: Project,
) -> None:
    body = "".join(f"line {n}\n" for n in range(9))
    project.commit(project.repo, "s.txt", body, "chore: add s")
    git(project.repo, "push", "-q", "origin", "main")
    path = project.worktree("feat/a", start="origin/main")
    project.commit(path, "s.txt", body.replace("line 1", "a"), "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    date = git(project.repo, "log", "-1", "--format=%ad", "--date=raw", "main")
    (project.repo / "s.txt").write_text(
        body.replace("line 1", "mine"), encoding="utf-8"
    )
    git(project.repo, "commit", "-q", "-am", "feat: a", "--date", date)
    project.commit(path, "s.txt", body.replace("line 1", "a2"), "fix: a")
    main = git(project.repo, "rev-parse", "main")

    assert project.run(apply=True) == 1

    assert git(project.repo, "rev-parse", "main") == main


def test_a_branch_that_merged_main_replaces_its_hand_resolved_copy_below_a_local_commit_that_removes_part_of_it(
    project: Project,
) -> None:
    body = "".join(f"line {n}\n" for n in range(9))
    project.commit(project.repo, "s.txt", body, "chore: add s")
    git(project.repo, "push", "-q", "origin", "main")
    path = project.worktree("feat/a", start="origin/main")
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    git(path, "add", "a.txt")
    project.commit(path, "s.txt", body.replace("line 1", "a"), "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    other = project.root / "other"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, "s.txt", body.replace("line 1", "up"), "chore: up")
    git(other, "push", "-q", "origin", "main")
    project.run(apply=True)
    resolved = body.replace("line 1", "up a")
    work = main_sync.resolve_worktree(project.repo)
    (work / "s.txt").write_text(resolved, encoding="utf-8")
    git(work, "add", "s.txt")
    assert project.run(apply=True) == 0
    git(project.repo, "rm", "-q", "a.txt")
    git(project.repo, "commit", "-qm", "chore: drop a")
    subprocess.run(["git", "-C", str(path), "merge", "-q", "origin/main"], check=False)
    (path / "s.txt").write_text(resolved, encoding="utf-8")
    git(path, "commit", "-qam", "Merge origin/main into feat/a")
    project.commit(path, "b.txt", "b\n", "feat: b")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["feat: a", "chore: drop a"]
    assert (project.repo / "b.txt").read_text(encoding="utf-8") == "b\n"
    assert not (project.repo / "a.txt").exists()


def test_a_changed_branch_replaces_its_hand_resolved_copy_with_a_change_its_history_reverts(
    project: Project,
) -> None:
    body = "".join(f"line {n}\n" for n in range(9))
    project.commit(project.repo, "s.txt", body, "chore: add s")
    project.commit(project.repo, "r.txt", body, "chore: add r")
    git(project.repo, "push", "-q", "origin", "main")
    project.commit(
        project.repo, "s.txt", body.replace("line 1", "local"), "chore: local"
    )
    path = project.worktree("feat/a", start="origin/main")
    (path / "s.txt").write_text(body.replace("line 1", "a"), encoding="utf-8")
    git(path, "add", "s.txt")
    wrapped = body.replace("line 1", "a").replace("line 7", "a")
    project.commit(path, "r.txt", wrapped, "feat: a")
    project.run(branch="feat/a")
    project.run(apply=True)
    resolved = body.replace("line 1", "local a")
    work = main_sync.resolve_worktree(project.repo)
    (work / "s.txt").write_text(resolved, encoding="utf-8")
    git(work, "add", "s.txt")
    assert project.run(apply=True) == 0
    project.commit(path, "r.txt", body.replace("line 1", "a"), "fix: a")

    assert project.run(apply=True) == 0

    assert project.main_subjects() == ["chore: local", "feat: a"]
    assert (project.repo / "r.txt").read_text(encoding="utf-8") == body.replace(
        "line 1", "a"
    )
    assert (project.repo / "s.txt").read_text(encoding="utf-8") == resolved


@pytest.mark.parametrize("encoding", ["utf-8", "latin-1"])
def test_main_is_left_unchanged_when_a_changed_branch_drops_a_hand_resolved_line_beside_one_main_reverted(
    project: Project, encoding: str
) -> None:
    body = "".join(f"line {n} \u00e9\n" for n in range(9))
    project.commit(project.repo, "g.txt", body, "chore: add g")
    project.commit(project.repo, "s.txt", body, "chore: add s", encoding)
    git(project.repo, "push", "-q", "origin", "main")
    project.commit(
        project.repo, "g.txt", body.replace("line 1", "local"), "chore: local"
    )
    path = project.worktree("feat/a", start="origin/main")
    (path / "g.txt").write_text(body.replace("line 1", "a"), encoding="utf-8")
    git(path, "add", "g.txt")
    project.commit(path, "s.txt", body.replace("line 1", "a"), "feat: a", encoding)
    project.run(branch="feat/a")
    project.run(apply=True)
    work = main_sync.resolve_worktree(project.repo)
    (work / "g.txt").write_text(body.replace("line 1", "local a"), encoding="utf-8")
    (work / "s.txt").write_text(
        body.replace("line 1", "a").replace("line 7", "hand"), encoding=encoding
    )
    git(work, "add", "g.txt", "s.txt")
    assert project.run(apply=True) == 0
    project.commit(
        project.repo,
        "s.txt",
        body.replace("line 7", "hand"),
        "chore: undo a",
        encoding,
    )
    project.commit(path, "b.txt", "b\n", "fix: a")
    main = git(project.repo, "rev-parse", "main")

    assert project.run(apply=True) == 1

    assert git(project.repo, "rev-parse", "main") == main


SYNC_GIT_SPAWN_BUDGET = 15


@pytest.fixture
def git_spawns(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Return the list that collects each git command the test spawns."""
    spawned: list[str] = []
    start = subprocess.Popen.__init__

    def counting(self: subprocess.Popen[Any], args: Any, *rest: Any, **kw: Any) -> None:
        if args[0] == "git":
            spawned.append(" ".join(args))
        start(self, args, *rest, **kw)

    monkeypatch.setattr(subprocess.Popen, "__init__", counting)
    return spawned


def add_synced_worktrees(project: Project, *names: str) -> list[Path]:
    paths = [
        project.worktree(
            name, f"feat: {name}-1", f"feat: {name}-2", start="origin/main"
        )
        for name in names
    ]
    for name in names:
        project.run(branch=name)
    assert project.run(apply=True) == 0
    return paths


def start_fresh_process() -> None:
    """Forget every git read the module kept, as a new process has none."""
    contribute._refs_moved()
    contribute._diffs.clear()
    contribute._logged_identity.cache_clear()


def count_noop_sync_spawns(project: Project, git_spawns: list[str]) -> int:
    start_fresh_process()
    git_spawns.clear()
    assert project.run(apply=True) == 0
    return len(git_spawns)


def test_a_sync_pass_over_three_worktrees_stays_within_the_git_spawn_budget(
    project: Project, git_spawns: list[str]
) -> None:
    add_synced_worktrees(project, "feat/a", "feat/b", "feat/c")

    assert count_noop_sync_spawns(project, git_spawns) <= SYNC_GIT_SPAWN_BUDGET, (
        git_spawns
    )


def test_a_fresh_sync_pass_makes_as_many_git_spawns_over_six_worktrees_as_over_three(
    project: Project, git_spawns: list[str]
) -> None:
    add_synced_worktrees(project, "feat/a", "feat/b", "feat/c")
    three = count_noop_sync_spawns(project, git_spawns)
    add_synced_worktrees(project, "feat/d", "feat/e", "feat/f")

    assert count_noop_sync_spawns(project, git_spawns) == three, git_spawns


def test_a_fresh_sync_pass_over_amended_worktrees_makes_as_many_git_spawns_as_over_untouched_ones(
    project: Project, git_spawns: list[str]
) -> None:
    paths = add_synced_worktrees(project, "feat/a", "feat/b", "feat/c")
    untouched = count_noop_sync_spawns(project, git_spawns)
    for path in paths:
        for round_ in ("amended", "amended again"):
            (path / f"{path.name}-more.txt").write_text(round_, encoding="utf-8")
            git(path, "add", ".")
            git(path, "commit", "-q", "--amend", "--no-edit")
            assert project.run(apply=True) == 0

    assert count_noop_sync_spawns(project, git_spawns) == untouched, git_spawns


def advance_origin_main(project: Project, name: str) -> None:
    other = project.root / f"other-{name}"
    subprocess.run(["git", "clone", "-q", str(project.origin), str(other)], check=True)
    project.commit(other, f"{name}.txt", "upstream\n", f"chore: {name}")
    git(other, "push", "-q", "origin", "main")
    git(project.repo, "fetch", "-q", "origin")


def add_worktrees_on_staggered_bases(project: Project, *names: str) -> None:
    for name in names:
        project.worktree(name, f"feat: {name}-1", start="origin/main")
        project.run(branch=name)
        assert project.run(apply=True) == 0
        advance_origin_main(project, name.replace("/", "-"))
    assert project.run(apply=True) == 0


def test_a_fresh_sync_pass_over_worktrees_on_older_upstream_bases_makes_as_many_git_spawns_as_over_fewer(
    project: Project, git_spawns: list[str]
) -> None:
    add_worktrees_on_staggered_bases(project, "feat/a", "feat/b", "feat/c")
    three = count_noop_sync_spawns(project, git_spawns)
    add_worktrees_on_staggered_bases(project, "feat/d", "feat/e", "feat/f")

    assert count_noop_sync_spawns(project, git_spawns) == three, git_spawns


def test_a_branch_whose_recorded_head_is_ahead_of_its_local_branch_has_no_earlier_version_copy(
    project: Project,
) -> None:
    path = add_synced_worktrees(project, "feat/a")[0]
    local = git(path, "rev-parse", "HEAD")
    head = git(path, "commit-tree", f"{local}^{{tree}}", "-p", local, "-m", "ahead")
    entries = [e._replace(remote_head=head) for e in project.entries()]
    base = contribute.base_ref(project.repo)
    start_fresh_process()
    contribute._track(project.repo, entries, (base,))

    tips = contribute._tips(project.repo, base, entries)

    assert tips[0].commits[-1] == head
    assert contribute._held_by_earlier_versions(project.repo, base, tips) == {
        "feat/a": set()
    }
    assert contribute._rewritten_copies(project.repo, base, tips, ()) == set()


def test_an_open_pr_body_with_a_leftover_comment_is_left_alone_and_named(
    project: Project, pushed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = f"## What\n\n- feat: a\n\n## Why\n\n{WHY}\n\n<!-- left over -->\n"
    _set_body(project, 100, body)
    _amend(project, pushed, "fix: a")
    capsys.readouterr()

    assert project.run(apply=True) == 1

    assert pr_body(project, 100) == body
    assert "body left as it is, it has a leftover placeholder comment" in (
        capsys.readouterr().out
    )
