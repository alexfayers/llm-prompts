import subprocess
from pathlib import Path

import pytest

from benchmark.test_bench_checks import run
from benchmark.traces import make_trace
from llm_prompts.benchmark import saved
from llm_prompts.benchmark.scenarios.checks import evaluate
from llm_prompts.benchmark.scenarios.checks.context import CheckContext
from llm_prompts.benchmark.types import CheckArg, CheckSpec

pytestmark = pytest.mark.real_io


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with a start ref and a bare origin at the start commit."""
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "f.txt").write_text("one\n")
    (tmp_path / "g.txt").write_text("two\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "chore: start")
    git(tmp_path, "init", "-q", "--bare", ".git/remote.git")
    git(tmp_path, "remote", "add", "origin", ".git/remote.git")
    git(tmp_path, "push", "-q", "origin", "main")
    git(tmp_path, "update-ref", "refs/benchmark/start", "main")
    return tmp_path


def commit(repo: Path, message: str) -> None:
    (repo / "f.txt").write_text(f"{message}\n")
    git(repo, "commit", "-q", "-am", message)


GIT_STATE: dict[str, CheckArg] = {
    "branch": "main",
    "since": "refs/benchmark/start",
    "commits": 1,
    "message_regex": r"\A(feat|fix): [^\n]+\Z",
    "remote": "origin",
}


def test_git_state_passes_for_one_commit_with_the_right_message_and_an_untouched_remote(
    repo: Path,
) -> None:
    commit(repo, "feat: squashed")

    assert run("git_state", GIT_STATE, ws=repo).passed


@pytest.mark.parametrize(
    "message", ["feat: a\n\nbody", "wip"], ids=["body", "not-conventional"]
)
def test_git_state_fails_on_a_wrong_message(repo: Path, message: str) -> None:
    commit(repo, message)

    assert not run("git_state", GIT_STATE, ws=repo).passed


def test_git_state_fails_on_the_wrong_commit_count(repo: Path) -> None:
    commit(repo, "feat: a")
    commit(repo, "feat: b")

    assert not run("git_state", GIT_STATE, ws=repo).passed


def test_git_state_fails_when_the_remote_branch_moved(repo: Path) -> None:
    commit(repo, "feat: a")
    git(repo, "push", "-q", "origin", "main")

    outcome = run("git_state", GIT_STATE, ws=repo)

    assert not outcome.passed
    assert "remote" in outcome.detail


@pytest.mark.parametrize(("code", "passed"), [(0, True), (3, False)])
def test_command_exit_runs_the_command_in_the_workspace(
    tmp_path: Path, code: int, passed: bool
) -> None:
    (tmp_path / "gate.sh").write_text(f"test -f marker && exit {code}\n")
    (tmp_path / "marker").touch()

    outcome = run("command_exit", {"command": "sh gate.sh"}, ws=tmp_path)

    assert outcome.passed is passed
    assert f"exited {code}" in outcome.detail


def test_command_exit_expects_the_given_exit_code(tmp_path: Path) -> None:
    assert run("command_exit", {"command": "exit 2", "exit": 2}, ws=tmp_path).passed


def test_command_exit_puts_the_venv_bin_first_on_the_path(tmp_path: Path) -> None:
    tool = tmp_path / "venv" / "bin" / "demo-tool"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    ctx = CheckContext(make_trace(), tmp_path, (), (), venv=tmp_path / "venv")
    (outcome,) = evaluate([CheckSpec("command_exit", {"command": "demo-tool"})], ctx)

    assert outcome.passed


def test_files_changed_passes_only_when_a_path_differs_from_the_first_commit(
    repo: Path,
) -> None:
    assert not run("files_changed", {"path": "f.txt"}, ws=repo).passed

    commit(repo, "feat: changed")

    assert run("files_changed", {"path": "f.txt"}, ws=repo).passed


def test_files_unchanged_compares_the_paths_with_the_first_commit(repo: Path) -> None:
    commit(repo, "feat: changed")

    assert not run("files_unchanged", {"path": ("f.txt", "g.txt")}, ws=repo).passed
    assert run("files_unchanged", {"path": "g.txt"}, ws=repo).passed

    (repo / "g.txt").unlink()

    assert not run("files_unchanged", {"path": "g.txt"}, ws=repo).passed


@pytest.mark.parametrize(
    ("text", "passed"), [("on\n", True), ("one\n", True), ("one!\n", False)]
)
def test_byte_size_fails_a_file_larger_than_in_the_first_commit(
    repo: Path, text: str, passed: bool
) -> None:
    (repo / "f.txt").write_text(text)

    assert run("byte_size", {"path": "f.txt"}, ws=repo).passed is passed


def test_saved_workspace_keeps_the_repo_so_git_checks_can_run_again(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    cell_dir = tmp_path_factory.mktemp("cell")
    commit(repo, "feat: a")

    saved.write(cell_dir, repo, make_trace(), (), ())

    assert run("git_state", GIT_STATE, ws=saved.load(cell_dir).workspace).passed
