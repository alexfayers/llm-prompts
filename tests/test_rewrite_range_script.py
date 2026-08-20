"""Tests for the git-tidy skill's declarative-plan rebase script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "shared"
    / "skills"
    / "git-tidy"
    / "rewrite_range.py"
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")


def _commit(repo: Path, filename: str, message: str) -> str:
    (repo / filename).write_text(message)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _set_fake_upstream(repo: Path) -> None:
    """Mark the current HEAD as a fake 'origin/main' upstream ref."""
    head = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "remote", "add", "origin", str(repo))
    _git(repo, "update-ref", "refs/remotes/origin/main", head)
    _git(repo, "branch", "--set-upstream-to=origin/main", "main")


def _log_subjects(repo: Path, rev_range: str) -> list[str]:
    output = _git(repo, "log", "--reverse", "--format=%s", rev_range)
    return [line for line in output.splitlines() if line]


def _run(
    repo: Path, plan: list[dict[str, str]], *extra_args: str
) -> subprocess.CompletedProcess[str]:
    plan_path = repo / "plan.json"
    plan_path.write_text(json.dumps(plan))
    return subprocess.run(
        [sys.executable, str(_SCRIPT), str(plan_path), *extra_args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


class TestMain:
    """Tests for the CLI entrypoint against real git repos."""

    def test_squash_with_custom_message_and_drop(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "init.txt", "chore: initial")
        _set_fake_upstream(tmp_path)
        base_sha = _commit(tmp_path, "a.txt", "feat: base feature")
        fixup_sha = _commit(tmp_path, "b.txt", "fix: fixup one")
        middle_sha = _commit(tmp_path, "c.txt", "unrelated: middle commit")
        drop_sha = _commit(tmp_path, "d.txt", "fix: fixup two")

        plan = [
            {"sha": base_sha, "verb": "pick"},
            {
                "sha": fixup_sha,
                "verb": "squash",
                "message": "feat: base feature with fixup",
            },
            {"sha": middle_sha, "verb": "pick"},
            {"sha": drop_sha, "verb": "drop"},
        ]
        completed = _run(tmp_path, plan)

        assert completed.returncode == 0, completed.stderr
        subjects = _log_subjects(tmp_path, "origin/main..HEAD")
        assert subjects == ["feat: base feature with fixup", "unrelated: middle commit"]

    def test_reorder_commits(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "init.txt", "chore: initial")
        _set_fake_upstream(tmp_path)
        a_sha = _commit(tmp_path, "a.txt", "feat: A")
        b_sha = _commit(tmp_path, "b.txt", "feat: B")
        c_sha = _commit(tmp_path, "c.txt", "feat: C")

        plan = [
            {"sha": b_sha, "verb": "pick"},
            {"sha": c_sha, "verb": "pick"},
            {"sha": a_sha, "verb": "pick"},
        ]
        completed = _run(tmp_path, plan)

        assert completed.returncode == 0, completed.stderr
        subjects = _log_subjects(tmp_path, "origin/main..HEAD")
        assert subjects == ["feat: B", "feat: C", "feat: A"]

    def test_squash_without_message_keeps_default(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "init.txt", "chore: initial")
        _set_fake_upstream(tmp_path)
        base_sha = _commit(tmp_path, "a.txt", "feat: base feature")
        fixup_sha = _commit(tmp_path, "b.txt", "fix: fixup one")

        plan = [
            {"sha": base_sha, "verb": "pick"},
            {"sha": fixup_sha, "verb": "squash"},
        ]
        completed = _run(tmp_path, plan)

        assert completed.returncode == 0, completed.stderr
        subjects = _log_subjects(tmp_path, "origin/main..HEAD")
        assert len(subjects) == 1
        assert subjects[0] == "feat: base feature"

    def test_invalid_verb_rejected(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "init.txt", "chore: initial")
        _set_fake_upstream(tmp_path)
        sha = _commit(tmp_path, "a.txt", "feat: base feature")

        plan = [{"sha": sha, "verb": "bogus"}]
        completed = _run(tmp_path, plan)

        assert completed.returncode != 0
        assert "invalid verb" in completed.stderr
