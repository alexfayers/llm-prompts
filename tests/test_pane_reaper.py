"""Tests for the pane-reaper pi extension."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "extensions"
    / "pane-reaper.ts"
)
_HARNESS = Path(__file__).parent / "context_total_harness.mjs"
_NOW = 2_000_000_000_000
_MINUTE_MS = 60_000
_OLD = _NOW - 30 * _MINUTE_MS
_GRACE_SECONDS = 900
_LIVE_OWNER = "01a00000-0000-7000-8000-00000000000a"
_DEAD_OWNER = "01a00000-0000-7000-8000-00000000000d"
_SELF = "01a00000-0000-7000-8000-0000000000e5"
_REQUEST = "f42f4a53-9d3c-435b-95b4-509250f47ae5"
_AGED_DATE = "2020-01-01T00:00:00+00:00"
_AGED_SECONDS = 1_577_836_800
_HERDR_STUB = """#!/bin/sh
echo "$@" >> "$HERDR_LOG"
case "$1 $2" in
  "pane list") cat "$HERDR_PANES" ;;
  "tab close") [ -z "$HERDR_FAIL_CLOSE" ] || exit 1; echo '{"result":{"type":"ok"}}' ;;
  "workspace list") cat "$HERDR_WORKSPACES" ;;
  *) echo '{"result":{"type":"ok"}}' ;;
esac
"""


def _git(cwd: Path, *args: str, date: str | None = _AGED_DATE) -> str:
    dates = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {}
    done = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        env={**os.environ, **dates},
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


def _can_strip_types() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run(
        [node, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not _can_strip_types(), reason="node with type stripping missing"
)


def _pane(
    pane_id: str,
    tab_id: str,
    *,
    status: str = "idle",
    managed: bool = True,
    started: int = _OLD,
    request: str = _REQUEST,
    session: str | None = None,
    cwd: Path | None = None,
    workspace_id: str = "w1",
) -> dict[str, Any]:
    tokens: dict[str, str] = {"request": request, "started": str(started)}
    if managed:
        tokens["managed"] = "1"
    pane: dict[str, Any] = {
        "pane_id": pane_id,
        "tab_id": tab_id,
        "agent_status": status,
        "workspace_id": workspace_id,
        "tokens": tokens,
    }
    if cwd is not None:
        pane["cwd"] = str(cwd)
    if session is not None:
        pane["agent_session"] = {
            "agent": "pi",
            "kind": "path",
            "value": f"/sessions/2026-10-10T20-11-24-885Z_{session}.jsonl",
        }
    return pane


class _Fixture:
    """A fake herdr on PATH plus a fake herdsman mailbox directory."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp_path = tmp_path
        self.agent_dir = tmp_path / "agent"
        self.mailboxes = self.agent_dir / "pi-herdsman" / "runtime" / "mailboxes-v5"
        self.mailboxes.mkdir(parents=True)
        self.log = tmp_path / "herdr.log"
        self.log.touch()
        self.panes_file = tmp_path / "panes.json"
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir()
        stub = stub_dir / "herdr"
        stub.write_text(_HERDR_STUB)
        stub.chmod(0o755)
        node_dir = Path(str(shutil.which("node"))).parent
        monkeypatch.setenv("PATH", f"{stub_dir}:{node_dir}:/usr/bin:/bin")
        monkeypatch.setenv("HERDR_LOG", str(self.log))
        monkeypatch.setenv("HERDR_PANES", str(self.panes_file))
        self.workspaces_file = tmp_path / "workspaces.json"
        monkeypatch.setenv("HERDR_WORKSPACES", str(self.workspaces_file))
        self.home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(self.home))
        self.set_panes([])
        self.set_workspaces([])
        monkeypatch.chdir(tmp_path)
        self.monkeypatch = monkeypatch

    def set_panes(self, panes: list[dict[str, Any]]) -> None:
        self.panes_file.write_text(json.dumps({"result": {"panes": panes}}))

    def set_workspaces(self, workspaces: list[dict[str, Any]]) -> None:
        self.workspaces_file.write_text(
            json.dumps({"result": {"workspaces": workspaces}})
        )

    def make_repo(self) -> Path:
        repo = self.tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        (repo / "base").write_text("base")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "initial")
        self.monkeypatch.chdir(repo)
        return repo

    def add_worktree(
        self,
        repo: Path,
        name: str,
        *,
        commits: int = 0,
        merged: bool = False,
        under: Path | None = None,
        date: str | None = _AGED_DATE,
        aged: bool = True,
    ) -> Path:
        path = (under or self.home / ".herdr" / "worktrees" / "repo") / name
        _git(repo, "worktree", "add", "-b", f"feat/{name}", str(path))
        for number in range(commits):
            (path / f"{name}-{number}").write_text("x")
            _git(path, "add", ".")
            _git(path, "commit", "-m", f"{name} {number}", date=date)
        if merged:
            _git(repo, "merge", "--ff-only", f"feat/{name}")
        if aged:
            os.utime(path, (_AGED_SECONDS, _AGED_SECONDS))
        return path

    def declare_workspace(self, workspace_id: str, path: Path) -> dict[str, Any]:
        return {
            "workspace_id": workspace_id,
            "worktree": {"checkout_path": str(path), "is_linked_worktree": True},
        }

    def add_state(
        self,
        pane_id: str,
        *,
        owner: str = _DEAD_OWNER,
        completed: bool = True,
        version: int = 5,
    ) -> None:
        directory = self.mailboxes / pane_id.replace(":", "_")
        directory.mkdir()
        state: dict[str, Any] = {
            "version": version,
            "ownerSessionId": owner,
            "paneId": pane_id,
        }
        if completed:
            state["completedRequestId"] = _REQUEST
            (directory / f"result-{_REQUEST}.json").write_text("{}")
        else:
            state["activeRequestId"] = _REQUEST
        (directory / "state.json").write_text(json.dumps(state))

    def install_gh(self, output: str, *, fail: bool = False) -> Path:
        log = self.tmp_path / "gh.log"
        stub = self.tmp_path / "bin" / "gh"
        stub.write_text(
            f'#!/bin/sh\necho "$@" >> "{log}"\n'
            + ("exit 1\n" if fail else f"echo '{output}'\n")
        )
        stub.chmod(0o755)
        return log

    def herdr_calls(self) -> list[str]:
        return self.log.read_text().splitlines()

    def run(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        config = self.tmp_path / "config.json"
        config.write_text(
            json.dumps(
                {
                    "script": str(_SCRIPT),
                    "agentDir": str(self.agent_dir),
                    "steps": steps,
                }
            )
        )
        done = subprocess.run(
            ["node", str(_HARNESS), str(config)],
            check=True,
            capture_output=True,
            text=True,
        )
        output: dict[str, Any] = json.loads(done.stdout)
        assert "error" not in output, output["error"]
        results: dict[str, Any] = output["results"]
        return results

    def sweep(self, **options: Any) -> dict[str, Any]:
        merged = {
            "now": _NOW,
            "graceSeconds": _GRACE_SECONDS,
            "selfSessionId": _SELF,
            **options,
        }
        result: dict[str, Any] = self.run(
            [{"fn": "sweep", "args": [merged], "as": "sweep"}]
        )["sweep"]
        return result


@pytest.fixture
def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Fixture:
    return _Fixture(tmp_path, monkeypatch)


class TestSweepClosesFinishedOrphans:
    """Tests for the safe class of panes the reaper closes on its own."""

    def test_idle_finished_managed_pane_of_a_dead_owner_past_grace_is_closed(
        self, fixture: _Fixture
    ) -> None:
        fixture.set_panes([_pane("w1:p2", "w1:t2")])
        fixture.add_state("w1:p2")
        result = fixture.sweep()
        assert [c["paneId"] for c in result["closed"]] == ["w1:p2"]
        assert result["asked"] == []
        assert fixture.herdr_calls() == ["pane list", "tab close w1:t2"]


class TestSweepWorktreesReportsMergedCleanWorktrees:
    """Tests for the leftover feature worktrees the reaper reports and never removes."""

    def test_merged_clean_worktree_is_reported_as_a_candidate_and_left_in_place(
        self, fixture: _Fixture
    ) -> None:
        repo = fixture.make_repo()
        path = fixture.add_worktree(repo, "done", commits=1, merged=True)
        fixture.set_workspaces([fixture.declare_workspace("w9", path)])
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert [(w["path"], w["branch"]) for w in result["candidates"]] == [
            (str(path), "feat/done")
        ]
        assert result["kept"] == []
        assert not any("worktree" in call for call in fixture.herdr_calls())
        assert path.exists()
        assert "feat/done" in _git(repo, "branch", "--list")


def _git_skip_cases() -> dict[str, Any]:
    def modify(path: Path) -> None:
        (path / "base").write_text("changed")

    def untracked(path: Path) -> None:
        (path / "new-file").write_text("x")

    def unmerged(path: Path) -> None:
        (path / "extra").write_text("x")
        _git(path, "add", ".")
        _git(path, "commit", "-m", "extra")

    def detached(path: Path) -> None:
        _git(path, "checkout", "--detach")

    return {
        "tracked file is modified": (modify, "uncommitted"),
        "untracked file is present": (untracked, "uncommitted"),
        "branch has an unmerged commit": (unmerged, "not merged"),
        "head is detached": (detached, "detached"),
    }


class TestSweepWorktreesKeepsWhatIsNotSafe:
    """Tests for worktrees the reaper reports and never removes."""

    @pytest.mark.parametrize("case", _git_skip_cases())
    def test_worktree_is_kept_with_a_reason_and_nothing_is_removed(
        self, fixture: _Fixture, case: str
    ) -> None:
        make_unsafe, expected_reason = _git_skip_cases()[case]
        repo = fixture.make_repo()
        path = fixture.add_worktree(repo, "wip", commits=1, merged=True)
        make_unsafe(path)
        fixture.set_workspaces([fixture.declare_workspace("w9", path)])
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert result["candidates"] == []
        assert [
            (w["path"], expected_reason in w["reason"]) for w in result["kept"]
        ] == [(str(path), True)]
        assert not any("worktree" in call for call in fixture.herdr_calls())
        assert path.exists()


class TestSweepWorktreesKeepsWorktreesItShouldNotTouch:
    """Tests for worktrees kept because they are not clearly finished or not Herdr's."""

    def test_worktree_outside_the_herdr_worktrees_directory_is_kept(
        self, fixture: _Fixture
    ) -> None:
        repo = fixture.make_repo()
        path = fixture.add_worktree(
            repo,
            "foreign",
            commits=1,
            merged=True,
            under=fixture.tmp_path / "elsewhere",
        )
        fixture.set_workspaces([fixture.declare_workspace("w9", path)])
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert result["candidates"] == []
        assert [(w["path"], w["reason"]) for w in result["kept"]] == [
            (str(path), "outside herdr worktrees")
        ]
        assert not any("worktree" in call for call in fixture.herdr_calls())
        assert path.exists()

    def test_branch_that_never_had_a_commit_of_its_own_is_kept(
        self, fixture: _Fixture
    ) -> None:
        repo = fixture.make_repo()
        path = fixture.add_worktree(repo, "empty")
        fixture.set_workspaces([fixture.declare_workspace("w9", path)])
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert result["candidates"] == []
        assert [(w["path"], w["reason"]) for w in result["kept"]] == [
            (str(path), "branch has no commits of its own")
        ]
        assert not any("worktree" in call for call in fixture.herdr_calls())
        assert path.exists()

    @pytest.mark.parametrize(
        "case", ["tip committed recently", "directory touched recently"]
    )
    def test_recently_changed_worktree_is_kept(
        self, fixture: _Fixture, case: str
    ) -> None:
        repo = fixture.make_repo()
        recent_tip = case == "tip committed recently"
        path = fixture.add_worktree(
            repo,
            "fresh",
            commits=1,
            merged=True,
            date=None if recent_tip else _AGED_DATE,
            aged=recent_tip,
        )
        fixture.set_workspaces([fixture.declare_workspace("w9", path)])
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert result["candidates"] == []
        assert [(w["path"], w["reason"]) for w in result["kept"]] == [
            (str(path), "changed in the last 24 hours")
        ]
        assert not any("worktree" in call for call in fixture.herdr_calls())
        assert path.exists()


class TestSweepWorktreesConfirmsSquashMergesOnGitHubOnly:
    """Tests for branches that GitHub merged without keeping their commits."""

    def _unmerged_worktree(
        self, fixture: _Fixture, remote: str | None
    ) -> tuple[Path, Path]:
        repo = fixture.make_repo()
        if remote:
            _git(repo, "remote", "add", "origin", remote)
        path = fixture.add_worktree(repo, "squashed", commits=1)
        fixture.set_workspaces([fixture.declare_workspace("w9", path)])
        return repo, path

    @pytest.mark.parametrize(
        "remote",
        [
            "https://github.com/owner/repo.git",
            "git@github.com:owner/repo.git",
            "ssh://git@github.com/owner/repo.git",
        ],
    )
    def test_github_remote_with_a_merged_pull_request_is_reported_as_a_candidate(
        self, fixture: _Fixture, remote: str
    ) -> None:
        repo, path = self._unmerged_worktree(fixture, remote)
        gh_log = fixture.install_gh('[{"number": 7}]')
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert [w["path"] for w in result["candidates"]] == [str(path)]
        assert result["kept"] == []
        assert gh_log.read_text().splitlines() == [
            "pr list --state merged --head feat/squashed --json number"
        ]
        assert path.exists()
        assert "feat/squashed" in _git(repo, "branch", "--list")

    @pytest.mark.parametrize(
        "remote",
        [
            None,
            "https://git.example.com/pkg/repo",
            "ssh://git.example.com/pkg/repo",
            "https://example.com/github.com/owner/repo",
            "https://notgithub.com/owner/repo",
        ],
    )
    def test_other_remotes_never_call_gh_and_the_branch_is_kept_unmerged(
        self, fixture: _Fixture, remote: str | None
    ) -> None:
        _, path = self._unmerged_worktree(fixture, remote)
        gh_log = fixture.install_gh('[{"number": 7}]')
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert result["candidates"] == []
        assert [("not merged" in w["reason"]) for w in result["kept"]] == [True]
        assert not gh_log.exists()
        assert path.exists()

    @pytest.mark.parametrize("case", ["no merged pull request", "gh fails"])
    def test_github_branch_without_a_confirmed_merge_is_kept(
        self, fixture: _Fixture, case: str
    ) -> None:
        _, path = self._unmerged_worktree(fixture, "https://github.com/owner/repo")
        fixture.install_gh("[]", fail=case == "gh fails")
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert result["candidates"] == []
        assert [("not merged" in w["reason"]) for w in result["kept"]] == [True]
        assert path.exists()

    def test_ancestor_merge_is_a_candidate_on_any_remote_without_gh(
        self, fixture: _Fixture
    ) -> None:
        repo = fixture.make_repo()
        _git(repo, "remote", "add", "origin", "https://git.example.com/pkg/repo")
        path = fixture.add_worktree(repo, "done", commits=1, merged=True)
        gh_log = fixture.install_gh("[]")
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert [w["path"] for w in result["candidates"]] == [str(path)]
        assert not gh_log.exists()


class TestSweepWorktreesKeepsWorktreesInUse:
    """Tests for worktrees a Herdr pane or workspace still uses."""

    @pytest.mark.parametrize(
        "case", ["agent cwd is in a subdirectory", "workspace has a pane elsewhere"]
    )
    def test_worktree_is_kept_and_nothing_is_opened_or_removed(
        self, fixture: _Fixture, case: str
    ) -> None:
        repo = fixture.make_repo()
        path = fixture.add_worktree(repo, "busy", commits=1, merged=True)
        workspace = fixture.declare_workspace("w9", path)
        if case == "agent cwd is in a subdirectory":
            fixture.set_panes([_pane("w1:p2", "w1:t2", cwd=path / "src")])
            fixture.set_workspaces([])
        else:
            fixture.set_panes([_pane("w9:p1", "w9:t1", workspace_id="w9", cwd=repo)])
            fixture.set_workspaces([workspace])
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert result["candidates"] == []
        assert [w["path"] for w in result["kept"]] == [str(path)]
        assert not any("worktree" in call for call in fixture.herdr_calls())
        assert path.exists()

    def test_workspace_without_panes_is_reported_without_opening_or_removing_anything(
        self, fixture: _Fixture
    ) -> None:
        repo = fixture.make_repo()
        path = fixture.add_worktree(repo, "orphan", commits=1, merged=True)
        fixture.set_workspaces([fixture.declare_workspace("w9", path)])
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert [w["path"] for w in result["candidates"]] == [str(path)]
        assert fixture.herdr_calls() == ["pane list", "workspace list"]
        assert path.exists()


class TestSweepWorktreesStopsWhenUncertain:
    """Tests for worktrees kept because a check says the main checkout is unsure."""

    def test_main_checkout_off_main_keeps_every_worktree(
        self, fixture: _Fixture
    ) -> None:
        repo = fixture.make_repo()
        path = fixture.add_worktree(repo, "done", commits=1, merged=True)
        _git(repo, "checkout", "-b", "other")
        fixture.set_workspaces([fixture.declare_workspace("w9", path)])
        result = fixture.run([{"fn": "sweepWorktrees", "as": "worktrees"}])["worktrees"]
        assert result["candidates"] == []
        assert [w["path"] for w in result["kept"]] == [str(path)]
        assert path.exists()


def _silent_cases() -> dict[str, tuple[list[dict[str, Any]], dict[str, Any]]]:
    orphan = _pane("w1:p2", "w1:t2")
    return {
        "owner pane is live": (
            [orphan, _pane("w1:p1", "w1:t1", managed=False, session=_LIVE_OWNER)],
            {"owner": _LIVE_OWNER},
        ),
        "owner is this session": ([orphan], {"owner": _SELF}),
        "pane is not managed": ([_pane("w1:p2", "w1:t2", managed=False)], {}),
        "pane is inside the grace period": (
            [_pane("w1:p2", "w1:t2", started=_NOW - 5 * _MINUTE_MS)],
            {},
        ),
    }


class TestSweepIgnoresPanesThatAreNotOrphans:
    """Tests for panes the reaper must neither close nor mention."""

    @pytest.mark.parametrize("case", _silent_cases())
    def test_pane_is_left_alone_without_a_notice(
        self, fixture: _Fixture, case: str
    ) -> None:
        panes, state_options = _silent_cases()[case]
        fixture.set_panes(panes)
        fixture.add_state("w1:p2", **state_options)
        result = fixture.sweep()
        assert result == {"closed": [], "asked": []}
        assert fixture.herdr_calls() == ["pane list"]


def _ask_cases() -> dict[str, tuple[dict[str, Any], dict[str, Any] | None]]:
    return {
        "pane is still working": (_pane("w1:p2", "w1:t2", status="working"), {}),
        "task has not finished": (_pane("w1:p2", "w1:t2"), {"completed": False}),
        "pane moved on to another request": (
            _pane("w1:p2", "w1:t2", request="another-request"),
            {},
        ),
        "launch time is unknown": (
            {**_pane("w1:p2", "w1:t2"), "tokens": {"managed": "1"}},
            {},
        ),
        "pane has no state file": (_pane("w1:p2", "w1:t2"), None),
    }


class TestSweepAsksAboutOtherFlaggedPanes:
    """Tests for orphans the reaper only reports."""

    @pytest.mark.parametrize("case", _ask_cases())
    def test_pane_is_reported_and_not_closed(
        self, fixture: _Fixture, case: str
    ) -> None:
        pane, state_options = _ask_cases()[case]
        fixture.set_panes([pane])
        if state_options is not None:
            fixture.add_state("w1:p2", **state_options)
        result = fixture.sweep()
        assert [(c["paneId"], bool(c["reason"])) for c in result["asked"]] == [
            ("w1:p2", True)
        ]
        assert result["closed"] == []
        assert fixture.herdr_calls() == ["pane list"]

    def test_done_pane_counts_as_idle(self, fixture: _Fixture) -> None:
        fixture.set_panes([_pane("w1:p2", "w1:t2", status="done")])
        fixture.add_state("w1:p2")
        assert [c["paneId"] for c in fixture.sweep()["closed"]] == ["w1:p2"]


class TestSweepStaysSilentOnUnknownHerdsmanState:
    """Tests for refusing to judge panes from state it cannot read."""

    def test_unknown_version_corrupt_file_or_missing_directory_does_nothing(
        self, fixture: _Fixture
    ) -> None:
        fixture.set_panes([_pane("w1:p2", "w1:t2"), _pane("w1:p3", "w1:t3")])
        fixture.add_state("w1:p2")
        fixture.add_state("w1:p3", version=6)
        assert fixture.sweep() == {"closed": [], "asked": []}
        (fixture.mailboxes / "w1_p3" / "state.json").write_text("{not json")
        assert fixture.sweep() == {"closed": [], "asked": []}
        shutil.rmtree(fixture.mailboxes)
        assert fixture.sweep() == {"closed": [], "asked": []}
        assert fixture.herdr_calls() == []


class TestSweepClosesOnlyWhatIsOrphaned:
    """Tests for the scope of a close."""

    def test_pane_sharing_its_tab_is_closed_alone_and_a_lone_pane_closes_its_tab(
        self, fixture: _Fixture
    ) -> None:
        fixture.set_panes(
            [
                _pane("w1:p2", "w1:t2"),
                _pane("w1:p3", "w1:t2", managed=False),
                _pane("w1:p4", "w1:t4"),
            ]
        )
        fixture.add_state("w1:p2")
        fixture.add_state("w1:p4")
        fixture.sweep()
        assert fixture.herdr_calls() == [
            "pane list",
            "pane close w1:p2",
            "tab close w1:t4",
        ]

    def test_failed_close_is_reported_and_the_sweep_goes_on(
        self, fixture: _Fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HERDR_FAIL_CLOSE", "1")
        fixture.set_panes([_pane("w1:p2", "w1:t2"), _pane("w1:p4", "w1:t4")])
        fixture.add_state("w1:p2")
        fixture.add_state("w1:p4")
        result = fixture.sweep()
        assert result["closed"] == []
        assert [(c["paneId"], c["reason"]) for c in result["asked"]] == [
            ("w1:p2", "closing it failed"),
            ("w1:p4", "closing it failed"),
        ]


_AGENT_ENV = ("PI_HERDSMAN_MAILBOX", "PI_SUBAGENT_CHILD", "HERDR_ENV", "PI_SESSION_ID")
_CTX = {"ui": {"$ui": "ui"}}
_SETTLE_MS = 700


def _recent() -> int:
    return int(time.time() * 1000) - 30 * _MINUTE_MS


class TestExtensionOnSessionStart:
    """Tests for the sweep that runs when a top-level lead starts."""

    @pytest.fixture(autouse=True)
    def _lead_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in _AGENT_ENV:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("HERDR_ENV", "1")
        monkeypatch.setenv("PI_SESSION_ID", _SELF)

    def _start(self, fixture: _Fixture) -> dict[str, Any]:
        steps: list[dict[str, Any]] = [
            {"fn": "default", "args": [{"$pi": "pi"}]},
            {"emit": "session_start", "pi": "pi", "ctx": _CTX},
            {"sleep": _SETTLE_MS},
            {"emit": "session_shutdown", "pi": "pi", "ctx": _CTX},
            {"notices": "ui", "as": "notices"},
        ]
        return fixture.run(steps)

    def test_closes_the_safe_orphan_and_shows_a_notice_for_it_and_for_the_others(
        self, fixture: _Fixture
    ) -> None:
        fixture.set_panes(
            [
                _pane("w1:p2", "w1:t2", started=_recent()),
                _pane("w1:p3", "w1:t3", started=_recent(), status="working"),
            ]
        )
        fixture.add_state("w1:p2")
        fixture.add_state("w1:p3")
        notices = self._start(fixture)["notices"]
        assert fixture.herdr_calls() == ["pane list", "tab close w1:t2"]
        assert [
            (level, "w1:p2" in text, "w1:p3" in text) for text, level in notices
        ] == [
            ("info", True, False),
            ("warning", False, True),
        ]

    def test_nothing_runs_in_a_delegated_agent_outside_herdr_or_when_disabled(
        self, fixture: _Fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fixture.set_panes([_pane("w1:p2", "w1:t2", started=_recent())])
        fixture.add_state("w1:p2")
        monkeypatch.setenv("PI_HERDSMAN_MAILBOX", "/mailbox")
        self._start(fixture)
        monkeypatch.delenv("PI_HERDSMAN_MAILBOX")
        monkeypatch.setenv("PI_SUBAGENT_CHILD", "1")
        self._start(fixture)
        monkeypatch.delenv("PI_SUBAGENT_CHILD")
        monkeypatch.delenv("HERDR_ENV")
        self._start(fixture)
        monkeypatch.setenv("HERDR_ENV", "1")
        (fixture.agent_dir / "pane-reaper.json").write_text('{"enabled": false}')
        self._start(fixture)
        assert fixture.herdr_calls() == []

    def test_outside_herdr_warns_once_and_does_not_sweep(
        self, fixture: _Fixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HERDR_ENV")
        fixture.set_panes([_pane("w1:p2", "w1:t2", started=_recent())])
        fixture.add_state("w1:p2")
        start: dict[str, Any] = {"emit": "session_start", "pi": "pi", "ctx": _CTX}
        steps: list[dict[str, Any]] = [
            {"fn": "default", "args": [{"$pi": "pi"}]},
            start,
            start,
            {"sleep": _SETTLE_MS},
            {"emit": "session_shutdown", "pi": "pi", "ctx": _CTX},
            {"notices": "ui", "as": "notices"},
        ]
        notices = fixture.run(steps)["notices"]
        assert [(level, "herdr" in text.lower()) for text, level in notices] == [
            ("warning", True)
        ]
        assert fixture.herdr_calls() == []

    def test_inside_herdr_shows_no_missing_herdr_warning(
        self, fixture: _Fixture
    ) -> None:
        assert self._start(fixture)["notices"] == []

    def test_a_flagged_pane_is_mentioned_once_across_sessions(
        self, fixture: _Fixture
    ) -> None:
        fixture.set_panes(
            [_pane("w1:p3", "w1:t3", started=_recent(), status="working")]
        )
        fixture.add_state("w1:p3")
        start: dict[str, Any] = {"emit": "session_start", "pi": "pi", "ctx": _CTX}
        steps: list[dict[str, Any]] = [
            {"fn": "default", "args": [{"$pi": "pi"}]},
            start,
            {"sleep": _SETTLE_MS},
            start,
            {"sleep": _SETTLE_MS},
            {"emit": "session_shutdown", "pi": "pi", "ctx": _CTX},
            {"notices": "ui", "as": "notices"},
        ]
        assert len(fixture.run(steps)["notices"]) == 1

    def test_candidates_are_reported_once_and_kept_worktrees_get_one_counted_line_when_the_kept_set_changes(
        self, fixture: _Fixture
    ) -> None:
        repo = fixture.make_repo()
        fixture.add_worktree(repo, "wip", commits=1)
        settling = fixture.add_worktree(
            repo, "settling", commits=1, merged=True, aged=False
        )
        fixture.set_workspaces([fixture.declare_workspace("w9", settling)])
        start: dict[str, Any] = {"emit": "session_start", "pi": "pi", "ctx": _CTX}
        steps: list[dict[str, Any]] = [
            {"fn": "default", "args": [{"$pi": "pi"}]},
            start,
            {"sleep": _SETTLE_MS},
            start,
            {"sleep": _SETTLE_MS},
            {"utime": str(settling), "seconds": _AGED_SECONDS},
            start,
            {"sleep": _SETTLE_MS},
            start,
            {"sleep": _SETTLE_MS},
            {"notices": "ui", "as": "notices"},
        ]
        notices = fixture.run(steps)["notices"]
        assert [text.split(" worktree")[0] for text, _ in notices] == [
            "pane-reaper kept 2",
            "pane-reaper:",
            "pane-reaper kept 1",
        ]
        assert notices[0][0] == "pane-reaper kept 2 worktrees (see /pane-reaper)"
        assert str(settling) in notices[1][0]
        assert notices[1][0].endswith("Safe to remove")
        assert settling.exists()
        assert notices[2][0] == "pane-reaper kept 1 worktree (see /pane-reaper)"


class TestCommand:
    """Tests for the /pane-reaper slash command."""

    @pytest.fixture(autouse=True)
    def _lead_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PI_SESSION_ID", _SELF)

    def _run_command(self, fixture: _Fixture, *arguments: str) -> list[list[str]]:
        steps: list[dict[str, Any]] = [{"fn": "default", "args": [{"$pi": "pi"}]}]
        steps += [
            {"command": "pane-reaper", "pi": "pi", "args": argument, "ctx": _CTX}
            for argument in arguments
        ]
        steps.append({"notices": "ui", "as": "notices"})
        notices: list[list[str]] = fixture.run(steps)["notices"]
        return notices

    def test_check_now_closes_the_safe_orphan_reports_the_rest_and_says_when_none(
        self, fixture: _Fixture
    ) -> None:
        fixture.set_panes(
            [_pane("w1:p3", "w1:t3", status="working", started=_recent())]
        )
        fixture.add_state("w1:p3")
        first = self._run_command(fixture, "", "")
        assert [level for _, level in first] == ["warning", "warning"]
        assert "/pane-reaper close w1:p3" in first[0][0]
        fixture.set_panes([])
        assert self._run_command(fixture, "") == [
            ["pane-reaper: no orphaned panes", "info"]
        ]
        fixture.set_panes([_pane("w1:p2", "w1:t2", started=_recent())])
        fixture.add_state("w1:p2")
        closed = self._run_command(fixture, "")
        assert [level for _, level in closed] == ["info"]
        assert fixture.herdr_calls()[-1] == "tab close w1:t2"

    def test_check_now_reports_candidate_and_kept_worktrees_and_removes_nothing(
        self, fixture: _Fixture
    ) -> None:
        repo = fixture.make_repo()
        done = fixture.add_worktree(repo, "done", commits=1, merged=True)
        wip = fixture.add_worktree(repo, "wip", commits=1)
        fixture.set_workspaces([fixture.declare_workspace("w9", done)])
        notices = self._run_command(fixture, "")
        assert [level for _, level in notices] == ["info", "info"]
        assert str(done) in notices[0][0]
        assert "Safe to remove" in notices[0][0]
        assert str(wip) in notices[1][0]
        assert "not merged" in notices[1][0]
        assert done.exists()

    def test_close_closes_a_flagged_pane_and_refuses_any_other(
        self, fixture: _Fixture
    ) -> None:
        fixture.set_panes(
            [
                _pane("w1:p3", "w1:t3", status="working", started=_recent()),
                _pane("w1:p4", "w1:t4", managed=False, started=_recent()),
                _pane(
                    "w1:p5",
                    "w1:t5",
                    status="working",
                    started=_recent() + 25 * _MINUTE_MS,
                ),
            ]
        )
        fixture.add_state("w1:p3")
        fixture.add_state("w1:p5")
        notices = self._run_command(
            fixture, "close w1:p4", "close w1:p5", "close w1:p3", "close", "bogus"
        )
        assert [level for _, level in notices] == [
            "warning",
            "warning",
            "info",
            "warning",
            "warning",
        ]
        assert [call for call in fixture.herdr_calls() if "close" in call] == [
            "tab close w1:t3"
        ]

    def test_on_and_off_rewrite_the_config_keeping_other_keys(
        self, fixture: _Fixture
    ) -> None:
        config = fixture.agent_dir / "pane-reaper.json"
        config.write_text('{"graceSeconds": 60}')
        self._run_command(fixture, "off")
        assert json.loads(config.read_text()) == {"graceSeconds": 60, "enabled": False}
        self._run_command(fixture, "on")
        assert json.loads(config.read_text()) == {"graceSeconds": 60, "enabled": True}


class TestConfig:
    """Tests for the settings file."""

    def test_enabled_by_default_with_the_fifteen_minute_grace_and_a_clamped_interval(
        self, fixture: _Fixture
    ) -> None:
        file = fixture.tmp_path / "pane-reaper.json"
        read = {"fn": "readConfig", "args": [str(file)]}
        custom = {"enabled": False, "graceSeconds": 30, "intervalSeconds": 1}
        steps: list[dict[str, Any]] = [
            {**read, "as": "missing"},
            {"truncate": str(file), "text": json.dumps(custom)},
            {**read, "as": "custom"},
        ]
        results = fixture.run(steps)
        assert results["missing"] == {
            "enabled": True,
            "graceSeconds": 900,
            "intervalSeconds": 60,
        }
        assert results["custom"] == {
            "enabled": False,
            "graceSeconds": 30,
            "intervalSeconds": 10,
        }
