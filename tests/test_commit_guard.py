"""Tests for the commit receipt guard."""

from __future__ import annotations

import json
import logging
import multiprocessing
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from cline_hooks.core.plugin import HookResult

from llm_prompts.guards.commit_guard import CommitGuard, PrimaryCheckoutGuard
from llm_prompts.guards.receipts import ReceiptStore, tree_fingerprint

LOGGER = logging.getLogger("test")
RunHook = Callable[..., HookResult | None]


@pytest.fixture
def guards_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the guards on."""
    monkeypatch.setenv("CLINE_HOOKS_FRONTEND", "pi")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a git repo whose test command is `just`."""
    path = tmp_path / "repo"
    path.mkdir()
    (path / "justfile").write_text("default:\n", encoding="utf-8")
    (path / "a.txt").write_text("one", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    monkeypatch.delenv("PI_CONTEXT_TEST_CMD", raising=False)
    return path


@pytest.fixture
def hook(repo: Path) -> RunHook:
    """Return a function that sends a hook event to the guard from the repo."""

    def run(hook_name: str, **kwargs: object) -> HookResult | None:
        return CommitGuard().on_hook(
            hook_name, logger=LOGGER, workspace_roots=[str(repo)], **kwargs
        )

    return run


def ran(hook: RunHook, command: str, success: bool = True, **extra: object) -> None:
    """Report a finished shell call."""
    hook(
        "PostToolUse",
        tool_name="execute_command",
        parameters={"command": command},
        success=success,
        **extra,
    )


@pytest.mark.real_io
@pytest.mark.usefixtures("guards_on")
class TestCommitGuard:
    def test_commit_needs_a_test_run_on_the_same_files(
        self, hook: RunHook, repo: Path
    ) -> None:
        blocked = hook("PreShell", command="git commit -m x")
        assert blocked is not None and "just" in (blocked.block or "")

        ran(hook, "just")
        assert hook("PreShell", command="git commit -m x") is None
        subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
        assert hook("PreShell", command="git commit -m x") is None

        (repo / "a.txt").write_text("two", encoding="utf-8")
        assert hook("PreShell", command="git commit -m x") is not None

    def test_a_mode_change_after_the_test_run_needs_a_new_run(
        self, hook: RunHook, repo: Path
    ) -> None:
        ran(hook, "just")
        (repo / "a.txt").chmod(0o755)
        assert hook("PreShell", command="git commit -m x") is not None

        ran(hook, "just")
        (repo / "a.txt").unlink()
        (repo / "a.txt").symlink_to("justfile")
        assert hook("PreShell", command="git commit -m x") is not None

    def test_a_submodule_moved_after_the_test_run_needs_a_new_run(
        self, hook: RunHook, repo: Path
    ) -> None:
        sub = repo / "sub"
        sub.mkdir()
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", str(sub)], check=True)
        subprocess.run(
            [*git, "-C", str(sub), "commit", "-q", "--allow-empty", "-m", "one"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "add", "sub"], check=True, capture_output=True
        )
        ran(hook, "just")
        assert hook("PreShell", command="git commit -m x") is None

        subprocess.run(
            [*git, "-C", str(sub), "commit", "-q", "--allow-empty", "-m", "two"],
            check=True,
        )
        assert hook("PreShell", command="git commit -m x") is not None

    def test_only_a_passing_run_of_the_test_command_by_itself_counts(
        self, hook: RunHook, repo: Path
    ) -> None:
        ran(hook, "just", success=False)
        ran(hook, "just | cat")
        ran(hook, "just lint")
        hook(
            "PostToolUse",
            tool_name="execute_command",
            parameters={"command": "just", "action": "start"},
            success=True,
        )
        assert hook("PreShell", command="git commit -m x") is not None

        ran(hook, f"cd {repo} && timeout 600 just", parent_tool_call_id="outer")
        assert hook("PreShell", command="git commit -m x") is None

    def test_a_run_chained_before_a_command_that_may_change_files_does_not_count(
        self, hook: RunHook, repo: Path
    ) -> None:
        ran(hook, "just && rm a.txt")
        assert hook("PreShell", command="git commit -m x") is not None
        ran(hook, "just && echo x > a.txt")
        ran(hook, "just && echo x >> a.txt")
        assert hook("PreShell", command="git commit -m x") is not None

        ran(hook, "just && echo done > /dev/null")
        assert hook("PreShell", command="git commit -m x") is None

    def test_a_redirected_or_chained_run_counts_when_its_result_decides_the_call(
        self, hook: RunHook
    ) -> None:
        ran(hook, "just; ls")
        ran(hook, "just || true")
        assert hook("PreShell", command="git commit -m x") is not None

        ran(hook, "ls -la; just > /tmp/just.log 2>&1")
        assert hook("PreShell", command="git commit -m x") is None

    @pytest.mark.parametrize(
        ("files", "command"),
        [
            ({"package.json": '{"scripts": {"test": "vitest"}}'}, "npm test"),
        ],
    )
    def test_the_gate_is_detected_from_the_repo_files(
        self, hook: RunHook, repo: Path, files: dict[str, str], command: str
    ) -> None:
        (repo / "justfile").unlink()
        for name, text in files.items():
            (repo / name).write_text(text, encoding="utf-8")
        assert hook("PreShell", command="git commit -m x") is not None

        ran(hook, f"{command} && echo done")
        assert hook("PreShell", command="git commit -m x") is None

    def test_a_passing_gate_counts_whatever_its_output_shows(
        self, hook: RunHook, repo: Path
    ) -> None:
        (repo / "justfile").unlink()
        (repo / "package.json").write_text(
            '{"scripts": {"test": "jest"}}', encoding="utf-8"
        )
        ran(
            hook,
            "npm test",
            result="[capped: 51291 chars, ref rc-1; result_fetch({ref})]",
        )
        assert hook("PreShell", command="git commit -m x") is None

    def test_push_also_needs_a_clean_tree(self, hook: RunHook, repo: Path) -> None:
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)
        ran(hook, "just")
        assert hook("PreShell", command="git push") is None

        (repo / "new.txt").write_text("x", encoding="utf-8")
        ran(hook, "just")
        blocked = hook("PreShell", command="git push")
        assert blocked is not None and "commit" in (blocked.block or "")

    def test_a_repo_without_a_test_command_is_left_alone(
        self, hook: RunHook, repo: Path
    ) -> None:
        (repo / "justfile").unlink()
        assert hook("PreShell", command="git commit -m x") is None

    def test_does_nothing_with_the_gate_off(
        self,
        hook: RunHook,
        monkeypatch: pytest.MonkeyPatch,
        isolated_config_dir: Path,
    ) -> None:
        monkeypatch.delenv("CLINE_HOOKS_FRONTEND")
        assert hook("PreShell", command="git commit -m x") is None
        ran(hook, "just")
        assert not (isolated_config_dir / "receipts.json").exists()

    def test_an_overlay_gate_wins_over_the_built_in_gate(
        self,
        hook: RunHook,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        gates = tmp_path / "overlay/shared/test-gates.json"
        gates.parent.mkdir(parents=True)
        gates.write_text(
            json.dumps({"gates": [{"all": ["a.txt"], "command": "make check"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "llm_prompts.install._discover_overlay_paths",
            lambda quiet: [tmp_path / "overlay"],
        )
        blocked = hook("PreShell", command="git commit -m x")
        assert blocked is not None and "make check" in (blocked.block or "")


def _record(args: tuple[Path, int]) -> None:
    path, index = args
    ReceiptStore(path).record(Path(f"/repo{index}"), str(index))


@pytest.mark.real_io
def test_receipts_from_parallel_sessions_are_all_kept(tmp_path: Path) -> None:
    path = tmp_path / "receipts.json"
    with multiprocessing.get_context("spawn").Pool(16) as pool:
        pool.map(_record, [(path, index) for index in range(64)])
    assert all(ReceiptStore(path).fresh(Path(f"/repo{i}"), str(i)) for i in range(64))


@pytest.mark.real_io
def test_a_failed_file_listing_never_matches_a_receipt(tmp_path: Path) -> None:
    assert tree_fingerprint(tmp_path) != tree_fingerprint(tmp_path)


@pytest.mark.real_io
class TestPrimaryCheckoutGuard:
    @pytest.fixture
    def primary(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> RunHook:
        """Return a hook runner for the primary checkout guard, with no frontend set."""
        monkeypatch.delenv("CLINE_HOOKS_FRONTEND", raising=False)

        def run(command: str, root: Path = repo) -> HookResult | None:
            return PrimaryCheckoutGuard().on_hook(
                "PreShell", logger=LOGGER, workspace_roots=[str(root)], command=command
            )

        return run

    def test_blocks_changes_to_the_primary_checkout(self, primary: RunHook) -> None:
        blocked = primary("git commit -m x")
        assert blocked is not None and "worktree" in (blocked.block or "")

    def test_allows_reads_fast_forwards_and_worktree_commands(
        self, primary: RunHook
    ) -> None:
        for command in [
            "git status",
            "git merge --ff-only b",
            "git pull --ff-only",
            "git worktree add ../w",
            "git branch -d b",
            "git stash list",
            "just",
        ]:
            assert primary(command) is None, command

    def test_blocks_gh_pr_create_and_stash_pop(self, primary: RunHook) -> None:
        assert primary("gh pr create --draft") is not None
        assert primary("git stash pop") is not None

    def test_blocks_a_forced_branch_move_but_not_a_branch_delete(
        self, primary: RunHook
    ) -> None:
        assert primary("git branch -f main HEAD~1") is not None
        assert primary("git branch --force main HEAD~1") is not None
        assert primary("git branch -fM old new") is not None
        assert primary("git branch -d done") is None

    def test_the_exact_same_command_again_proceeds_once(self, primary: RunHook) -> None:
        assert primary("git reset --hard") is not None
        assert primary("git commit -m y") is not None
        assert primary("git commit -m y") is None
        assert primary("git commit -m y") is not None

    def test_allows_everything_in_a_linked_worktree(
        self, primary: RunHook, repo: Path, tmp_path: Path
    ) -> None:
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(
            [*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True
        )
        subprocess.run(
            [*git, "worktree", "add", "-q", "-b", "w", str(tmp_path / "w")], check=True
        )
        assert primary("git commit -m x", tmp_path / "w") is None
        assert primary(f"cd {tmp_path / 'w'} && git rebase main") is None

    def test_blocks_a_git_dash_c_call_into_the_primary_checkout(
        self,
        primary: RunHook,
        repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(
            [*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True
        )
        subprocess.run(
            [*git, "worktree", "add", "-q", "-b", "w", str(tmp_path / "w")], check=True
        )
        assert primary(f"git -C {repo} commit -m x", tmp_path / "w") is not None
        assert primary(f"git -C{repo} commit -m x", tmp_path / "w") is not None
        assert (
            primary(f"git -C {repo.parent} -C {repo.name} commit -m x", tmp_path / "w")
            is not None
        )
        assert primary(f"git -C {repo} log -C", tmp_path / "w") is None
        monkeypatch.setenv("PRIMARY_REPO", str(repo))
        assert primary("git -C $PRIMARY_REPO commit -m y", tmp_path / "w") is not None
        monkeypatch.setenv("HOME", str(repo.parent))
        assert primary(f"git -C ~/{repo.name} commit -m z", tmp_path / "w") is not None
        assert (
            primary(f"git --work-tree={repo} commit -m w", tmp_path / "w") is not None
        )
        assert (
            primary(f"git --git-dir {repo}/.git commit -m v", tmp_path / "w")
            is not None
        )


@pytest.mark.real_io
def test_import_skips_the_shell_parser() -> None:
    check = (
        "import sys, llm_prompts.guards.commit_guard; "
        "print(sorted({'bashlex', 'jinja2'} & set(sys.modules)))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", check], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "[]"
