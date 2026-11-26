"""Tests that a snapshot answers history questions as git does, or declines them."""

from __future__ import annotations

import itertools
import os
import subprocess
from pathlib import Path

import pytest

from llm_prompts.git_snapshot import Snapshot, read_diffs, read_refs

pytestmark = pytest.mark.real_io

_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


class Repo:
    """A scratch repo with a ``floor`` branch standing in for origin/main."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.clock = 1_700_000_000
        subprocess.run(["git", "init", "-q", "-b", "floor", str(path)], check=True)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, **_ENV},
        ).stdout.strip()

    def commit(self, subject: str) -> str:
        self.clock += 60
        self.git(
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            subject,
            "--date",
            f"{self.clock} +0000",
        )
        return self.git("rev-parse", "HEAD")

    def merge(self, branch: str, subject: str) -> str:
        self.clock += 60
        self.git("merge", "-q", "--no-ff", "-m", subject, branch)
        return self.git("rev-parse", "HEAD")

    def snapshot(self, *heads: str) -> Snapshot:
        return Snapshot(self.path, read_refs(self.path), "floor", heads)


def _is_ancestor(repo: Repo, ancestor: str, sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo.path), "merge-base", "--is-ancestor", ancestor, sha],
            check=False,
        ).returncode
        == 0
    )


def _names(repo: Repo) -> list[str]:
    return repo.git("for-each-ref", "--format=%(refname:short)", "refs/heads").split()


def _agrees_with_git(repo: Repo, snapshot: Snapshot) -> None:
    """Every answer the snapshot gives is git's, for every pair of branches and commits."""
    names = _names(repo)
    shas = repo.git("rev-list", "--all").split()
    for a, b in itertools.product([*names, *shas], repeat=2):
        if (found := snapshot.is_ancestor(a, b)) is not None:
            assert found == _is_ancestor(repo, a, b), (a, b)
    for name in names:
        if (found_base := snapshot.merge_base("floor", name)) is not None:
            assert found_base == repo.git("merge-base", "floor", name), name
        if (listed := snapshot.shas("floor", name)) is not None:
            assert (
                listed
                == repo.git("rev-list", "--reverse", f"floor..{name}").splitlines()
            )
    for sha in shas:
        if (identity := snapshot.identity(sha)) is not None:
            assert identity == repo.git("log", "-1", "--format=%at%x09%s", sha)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    made = Repo(tmp_path)
    made.commit("chore: base")
    return made


def test_a_linear_branch_is_answered_without_asking_git(repo: Repo) -> None:
    floor = repo.git("rev-parse", "floor")
    repo.git("switch", "-q", "-c", "feat")
    first, second, third = (repo.commit(f"feat: {n}") for n in "abc")
    repo.git("switch", "-q", "floor")
    repo.commit("chore: floor moves on")
    repo.git("switch", "-q", "feat")
    snapshot = repo.snapshot("feat")

    assert snapshot.shas("floor", "feat") == [first, second, third]
    assert snapshot.is_ancestor(first, third) is True
    assert snapshot.is_ancestor(third, first) is False
    assert snapshot.is_ancestor("floor", "feat") is False
    assert snapshot.is_ancestor(first, "floor") is False
    assert snapshot.merge_base("floor", "feat") == floor
    assert snapshot.identity(second) is not None
    assert snapshot.identity(floor) is None
    _agrees_with_git(repo, snapshot)


def test_a_branch_holding_the_floor_is_answered(repo: Repo) -> None:
    repo.git("switch", "-q", "-c", "feat")
    tip = repo.commit("feat: a")
    snapshot = repo.snapshot("feat")

    assert snapshot.shas("floor", "feat") == [tip]
    assert snapshot.is_ancestor("floor", "feat") is True
    assert snapshot.shas("floor", "floor") == []
    _agrees_with_git(repo, snapshot)


def test_a_branch_with_a_merge_is_answered_only_where_the_order_is_settled(
    repo: Repo,
) -> None:
    repo.git("switch", "-q", "-c", "side")
    side = repo.commit("feat: side")
    repo.git("switch", "-q", "-c", "feat", "floor")
    repo.commit("feat: own")
    repo.merge("side", "merge side")
    snapshot = repo.snapshot("feat", "side")

    assert snapshot.shas("floor", "feat") is None
    assert snapshot.is_ancestor(side, "feat") is True
    assert snapshot.is_ancestor("feat", side) is False
    _agrees_with_git(repo, snapshot)


def test_a_criss_cross_has_no_single_merge_base_to_answer(repo: Repo) -> None:
    repo.git("switch", "-q", "-c", "left")
    repo.commit("left: a")
    repo.git("switch", "-q", "-c", "right", "floor")
    repo.commit("right: a")
    repo.git("switch", "-q", "left")
    repo.merge("right", "left takes right")
    repo.git("switch", "-q", "right")
    repo.merge("left~1", "right takes left")
    repo.git("branch", "-f", "floor", "left")
    snapshot = repo.snapshot("right")

    assert len(repo.git("merge-base", "--all", "floor", "right").split()) == 2
    assert snapshot.merge_base("floor", "right") is None
    _agrees_with_git(repo, snapshot)


def test_commits_outside_the_snapshot_are_declined(repo: Repo) -> None:
    repo.git("switch", "-q", "-c", "other")
    repo.commit("feat: other")
    repo.git("switch", "-q", "-c", "feat", "floor")
    repo.commit("feat: a")
    snapshot = repo.snapshot("feat")

    assert snapshot.is_ancestor("feat", "other") is None
    assert snapshot.shas("floor", "other") is None
    assert snapshot.merge_base("floor", "other") is None
    assert snapshot.is_commit(repo.git("rev-parse", "other")) is None
    assert snapshot.is_commit(repo.git("rev-parse", "feat")) is True


def test_a_floor_that_is_not_a_ref_declines_everything(repo: Repo) -> None:
    snapshot = Snapshot(repo.path, read_refs(repo.path), "origin/main", ["floor"])

    assert snapshot.shas("origin/main", "floor") is None
    assert snapshot.is_ancestor("floor", "floor") is True


def test_a_signed_commit_is_read_while_git_log_shows_signatures(
    repo: Repo,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gpg = tmp_path_factory.mktemp("gpg") / "gpg"
    gpg.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  *--verify*) echo 'gpg: Good signature' >&2\n"
        "    echo '[GNUPG:] GOODSIG 0123456789ABCDEF fake'\n"
        "    echo '[GNUPG:] VALIDSIG 0123456789ABCDEF 2020-01-01 1 0 0 0 0 0 0123456789ABCDEF' ;;\n"
        "  *) cat > /dev/null\n"
        "    echo '-----BEGIN PGP SIGNATURE-----'; echo ZmFrZQ==; echo '-----END PGP SIGNATURE-----'\n"
        "    echo '[GNUPG:] SIG_CREATED D 1 8 00 0 fake' >&2 ;;\n"
        "esac\n"
    )
    gpg.chmod(0o755)
    for index, (key, value) in enumerate(
        [("log.showSignature", "true"), ("gpg.program", str(gpg))]
    ):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{index}", key)
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{index}", value)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    repo.git("switch", "-q", "-c", "feat")
    repo.git(
        "-c",
        "user.signingkey=fake",
        "commit",
        "-q",
        "--allow-empty",
        "-S",
        "-m",
        "feat: signed",
    )
    signed = repo.git("rev-parse", "HEAD")

    assert "Good signature" in repo.git("log", "-1", "--format=%H", "feat")
    assert repo.snapshot("feat").shas("floor", "feat") == [signed]


def _patch_id_of(repo: Repo, *diff_args: str) -> str:
    shown = subprocess.run(
        ["git", "-C", str(repo.path), *diff_args],
        capture_output=True,
        check=True,
        env={**os.environ, **_ENV},
    ).stdout
    done = subprocess.run(
        ["git", "patch-id", "--stable"],
        cwd=repo.path,
        input=shown,
        capture_output=True,
        check=True,
    ).stdout.decode()
    return done.split()[0] if done else ""


def test_diffs_read_in_one_pass_match_what_show_and_diff_print(repo: Repo) -> None:
    floor = repo.git("rev-parse", "floor")
    repo.git("switch", "-q", "-c", "feat")
    changes = []
    for name, content in [
        ("a.txt", b"one\ntwo\n"),
        ("dir/b d.txt", "caf\xe9\n".encode("latin-1")),
        ("a.txt", b"one\nthree\n"),
    ]:
        (repo.path / name).parent.mkdir(exist_ok=True)
        (repo.path / name).write_bytes(content)
        repo.git("add", name)
        changes.append(repo.commit(f"feat: {name}"))
    empty = repo.commit("feat: empty")
    tip = repo.git("rev-parse", "HEAD")

    found = read_diffs(
        repo.path,
        [(floor, tip), (floor, changes[0]), *(("", sha) for sha in (*changes, empty))],
    )

    for sha in (*changes, empty):
        diff = found["", sha]
        assert diff.patch_id == _patch_id_of(repo, "show", "-U0", sha)
        assert diff.paths == set(
            repo.git("show", "--format=", "--name-only", sha).splitlines()
        )
    squash = found[floor, tip]
    assert squash.patch_id == _patch_id_of(repo, "diff", "-U0", floor, tip)
    assert squash.paths == {"a.txt", "dir/b d.txt"}
    assert found[floor, changes[0]].patch_id == found["", changes[0]].patch_id
    assert found["", empty].patch_id == ""
    assert found["", empty].paths == set()


def test_an_empty_root_commit_has_an_empty_diff(repo: Repo) -> None:
    root = repo.git("rev-list", "--max-parents=0", "floor")

    assert read_diffs(repo.path, [("", root)])["", root].patch_id == ""
    assert read_diffs(repo.path, []) == {}


def test_a_head_below_the_floor_is_answered_as_holding_no_commits(repo: Repo) -> None:
    old = repo.git("rev-parse", "HEAD")
    repo.commit("chore: floor moves on")
    repo.git("switch", "-q", "-c", "feat")
    tip = repo.commit("feat: a")
    repo.git("switch", "-q", "floor")
    snapshot = Snapshot(repo.path, read_refs(repo.path), "floor", ["feat"], [old])

    assert snapshot.shas("floor", old) == []
    assert snapshot.is_commit(old) is True
    assert snapshot.shas("floor", tip) == [tip]
    assert (
        Snapshot(repo.path, read_refs(repo.path), "floor", ["feat"]).shas("floor", old)
        is None
    )
