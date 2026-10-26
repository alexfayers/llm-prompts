"""End-to-end tests that run real git against temporary repositories."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from llm_prompts import cli, plugins, setup

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


pytestmark = pytest.mark.real_io

_IDENTITY = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_COUNT": "3",
    "GIT_CONFIG_KEY_0": "core.fsync",
    "GIT_CONFIG_VALUE_0": "none",
    "GIT_CONFIG_KEY_1": "maintenance.auto",
    "GIT_CONFIG_VALUE_1": "false",
    "GIT_CONFIG_KEY_2": "init.templateDir",
    "GIT_CONFIG_VALUE_2": "",
}


def git(repo: Path, *args: str) -> str:
    """Run real git in repo and return stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **_IDENTITY},
    ).stdout.strip()


def commit_file(repo: Path, name: str, content: str, message: str) -> None:
    """Write a file and commit it."""
    is_new = not (repo / name).exists()
    (repo / name).write_text(content)
    if is_new:
        git(repo, "add", name)
    git(repo, "commit", "-q", "-a", "-m", message)


def subjects(repo: Path) -> list[str]:
    """Return the commit subjects of HEAD, newest first."""
    return git(repo, "log", "--format=%s").splitlines()


def copy_repo(source: Path, dest: Path, old_url: Path, new_url: Path) -> Path:
    """Copy a repository without spawning git, repointing its origin."""
    shutil.copytree(source, dest)
    config = dest / ".git" / "config"
    config.write_text(config.read_text().replace(str(old_url), str(new_url)))
    return dest


@pytest.fixture(autouse=True)
def git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give real git a fixed identity and no user or system config."""
    for key, value in _IDENTITY.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(scope="session")
def template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Build once a bare upstream with one commit on main and a clone of it."""
    root = tmp_path_factory.mktemp("template")
    seed, bare, clone = root / "seed", root / "upstream.git", root / "clone"
    git(root, "init", "-q", "-b", "main", str(seed))
    commit_file(seed, "shared.txt", "base\n", "base")
    git(root, "clone", "-q", "--bare", str(seed), str(bare))
    git(root, "clone", "-q", str(bare), str(clone))
    return bare, clone


@pytest.fixture
def upstream(tmp_path: Path, template: tuple[Path, Path]) -> Path:
    """Return a per-test copy of the bare upstream."""
    return shutil.copytree(template[0], tmp_path / "upstream.git")


@pytest.fixture
def clone(tmp_path: Path, template: tuple[Path, Path], upstream: Path) -> Path:
    """Return a per-test clone tracking origin/main."""
    return copy_repo(template[1], tmp_path / "clone", template[0], upstream)


@pytest.fixture
def other(tmp_path: Path, template: tuple[Path, Path], upstream: Path) -> Path:
    """Return a second clone, used to push upstream changes."""
    return copy_repo(template[1], tmp_path / "other", template[0], upstream)


def push_commit(other: Path, name: str, content: str) -> None:
    """Push a new commit that rewrites shared.txt."""
    commit_file(other, "shared.txt", content, name)
    git(other, "push", "-q", "origin", "main")


def sync(clone: Path) -> list[str]:
    """Run the local-source pull on the clone and return its messages."""
    return cli._pull_one_local_source("core", str(clone)).messages


class TestRewriteRangeE2E:
    """e2e: rewrite_range.py drives a real `git rebase -i`."""

    @pytest.fixture
    def mod(self) -> ModuleType:
        """Load the rewrite_range script as a module."""
        spec = importlib.util.spec_from_file_location("rewrite_range", _SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_e2e_reorders_and_squashes_real_commits(
        self,
        mod: ModuleType,
        clone: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        base = git(clone, "rev-parse", "HEAD")
        for name in "bcd":
            commit_file(clone, f"{name}.txt", name, f"feat: {name.upper()}")
        shas = git(clone, "log", "--reverse", "--format=%H", f"{base}..HEAD").split()
        plan = [
            {"sha": shas[1], "verb": "pick"},
            {"sha": shas[0], "verb": "pick"},
            {"sha": shas[2], "verb": "squash", "message": "feat: B and D"},
        ]
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan))
        monkeypatch.chdir(clone)
        monkeypatch.setattr(sys, "argv", ["rewrite_range.py", str(plan_path), base])

        with pytest.raises(SystemExit) as exited:
            mod.main()

        assert exited.value.code == 0
        assert subjects(clone) == ["feat: B and D", "feat: C", "base"]
        assert git(clone, "status", "--porcelain") == ""


class TestPullLocalSourceE2E:
    """e2e: syncing a real clone against a real upstream."""

    def test_e2e_fast_forward_then_diverged_clone_syncs_onto_upstream(
        self, clone: Path, other: Path
    ) -> None:
        push_commit(other, "upstream change", "up\n")

        assert sync(clone) == ["[core] pulled 1 new commit(s)"]
        assert subjects(clone) == ["upstream change", "base"]

        commit_file(clone, "local.txt", "local\n", "local change")
        push_commit(other, "second upstream change", "up again\n")

        assert sync(clone) == ["[core] rebased local commits onto 1 new commit(s)"]
        assert subjects(clone) == [
            "local change",
            "second upstream change",
            "upstream change",
            "base",
        ]
        assert git(clone, "status", "--porcelain") == ""

    def test_e2e_conflicting_rebase_is_aborted_leaving_clean_tree(
        self, clone: Path, other: Path
    ) -> None:
        commit_file(clone, "shared.txt", "local\n", "local change")
        push_commit(other, "upstream change", "up\n")

        messages = sync(clone)

        assert messages[0] == "[core] 1 new commit(s) available but sync failed"
        assert list((clone / ".git").glob("rebase-*")) == []
        assert git(clone, "status", "--porcelain") == ""
        assert subjects(clone) == ["local change", "base"]


class TestPluginsE2E:
    """e2e: plugin checkouts cloned and refreshed with real git."""

    @pytest.fixture
    def plugin(self, upstream: Path) -> dict[str, str]:
        """Return a plugin entry sourced from the local bare upstream."""
        return {"name": "p", "source": f"git+file://{upstream}"}

    def test_e2e_clone_then_reset_hard_follows_force_updated_upstream(
        self,
        tmp_path: Path,
        other: Path,
        plugin: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        skill = other / "skills" / "demo" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: demo\ndescription: demo\n---\n")
        git(other, "add", ".")
        git(other, "commit", "-q", "-m", "add skill")
        git(other, "push", "-q", "origin", "main")
        config = tmp_path / "config.toml"
        config.write_text(f'[[plugins]]\nname = "p"\nsource = "{plugin["source"]}"\n')
        monkeypatch.setattr(setup, "config_path", lambda: config)

        dest = plugins.ensure_cloned(plugin)

        assert dest is not None
        assert (dest / ".git").is_dir()
        assert (dest / "skills" / "demo" / "SKILL.md").is_file()

        (other / "shared.txt").write_text("rewritten\n")
        git(other, "commit", "-q", "-a", "--amend", "-m", "rewritten skill")
        git(other, "push", "-q", "--force", "origin", "main")

        plugins.pull_plugin_sources()

        assert git(dest, "rev-parse", "HEAD") == git(other, "rev-parse", "HEAD")
        assert (dest / "shared.txt").read_text() == "rewritten\n"
        assert subjects(dest) == ["rewritten skill", "base"]
        assert "[p] updated to" in capsys.readouterr().out
