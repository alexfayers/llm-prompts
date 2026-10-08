"""Shared pytest fixtures for the test suite."""

from __future__ import annotations

import io
import json
import subprocess
import threading
import urllib.error
from collections.abc import Callable, Sequence
from email.message import Message
from pathlib import Path
from typing import Any, Self, cast

import pytest

from llm_prompts import github_api
from llm_prompts.batching import batch_branch
from llm_prompts.contribute import Pr

SideEffectCall = Callable[
    [list[str], dict[str, Any]], subprocess.CompletedProcess[str] | None
]
SideEffect = BaseException | type[BaseException] | SideEffectCall


def _verb_tokens(argv: list[str]) -> list[str]:
    if not argv or argv[0] != "git":
        return list(argv)
    tokens = argv[1:]
    while len(tokens) >= 2 and tokens[0] == "-C":
        tokens = tokens[2:]
    return tokens


def _matches_repo(argv: list[str], repo: str | Path | None, cwd: Any = None) -> bool:
    if repo is None:
        return True
    repo_str = str(repo)
    return (cwd is not None and str(cwd) == repo_str) or any(
        tok == "-C" and argv[i + 1] == repo_str for i, tok in enumerate(argv[:-1])
    )


def _pick(value: Any, index: int) -> Any:
    return value[min(index, len(value) - 1)] if isinstance(value, list) else value


class _Route:
    def __init__(
        self,
        tokens: list[str] | None,
        predicate: Callable[[list[str]], bool] | None,
        stdout: str | list[str],
        returncode: int | list[int],
        stderr: str | list[str],
        repo: str | Path | None,
        side_effect: SideEffect | None,
    ) -> None:
        self.tokens, self.predicate, self.repo, self.side_effect = (
            tokens,
            predicate,
            repo,
            side_effect,
        )
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self._index = 0

    def next_values(self) -> tuple[str, int, str]:
        index = self._index
        self._index += 1
        return (
            _pick(self.stdout, index),
            _pick(self.returncode, index),
            _pick(self.stderr, index),
        )


class FakeSubprocess:
    """Fake replacement for subprocess.run, routed by command prefix."""

    def __init__(self) -> None:
        """Initialise empty routing tables and call records."""
        self.commands: list[list[str]] = []
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.strict = False
        self._routes: list[_Route] = []
        self._match_routes: list[_Route] = []
        self._lock = threading.RLock()

    @property
    def verbs(self) -> list[str]:
        """Return each recorded call's verb tokens, joined by spaces."""
        return [" ".join(_verb_tokens(argv)) for argv in self.commands]

    def on(
        self,
        *tokens: str,
        stdout: str | list[str] = "",
        returncode: int | list[int] = 0,
        stderr: str | list[str] = "",
        repo: str | Path | None = None,
        side_effect: SideEffect | None = None,
    ) -> None:
        """Register a canned response for commands whose verb tokens start with tokens."""
        self._routes.append(
            _Route(list(tokens), None, stdout, returncode, stderr, repo, side_effect)
        )

    def on_match(
        self,
        predicate: Callable[[list[str]], bool],
        *,
        stdout: str | list[str] = "",
        returncode: int | list[int] = 0,
        stderr: str | list[str] = "",
        repo: str | Path | None = None,
        side_effect: SideEffect | None = None,
    ) -> None:
        """Register a canned response for commands matching an arbitrary predicate."""
        self._match_routes.append(
            _Route(None, predicate, stdout, returncode, stderr, repo, side_effect)
        )

    def _resolve(self, argv: list[str], cwd: Any = None) -> _Route | None:
        for route in reversed(self._match_routes):
            if (
                route.predicate is not None
                and route.predicate(argv)
                and _matches_repo(argv, route.repo, cwd)
            ):
                return route
        verb = _verb_tokens(argv)
        best, best_len = None, -1
        for route in self._routes:
            tokens = route.tokens or []
            ok = (
                len(tokens) <= len(verb)
                and verb[: len(tokens)] == tokens
                and _matches_repo(argv, route.repo, cwd)
            )
            if ok and len(tokens) >= best_len:
                best, best_len = route, len(tokens)
        return best

    def run(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Replace subprocess.run: record the call and resolve a canned response."""
        with self._lock:
            self.commands.append(list(argv))
            self.calls.append((list(argv), dict(kwargs)))
            route = self._resolve(argv, kwargs.get("cwd"))
            if route is None:
                if self.strict:
                    raise AssertionError(f"fake_subprocess: unrouted command {argv!r}")
                return subprocess.CompletedProcess(argv, 0, "", "")
            if route.side_effect is not None:
                effect = route.side_effect
                if isinstance(effect, BaseException):
                    raise effect
                if isinstance(effect, type) and issubclass(effect, BaseException):
                    raise effect()
                # isinstance(effect, type) cannot separate an exception class from a
                # callable class, so mypy loses the callable member here.
                call = cast(SideEffectCall, effect)
                result = call(argv, kwargs)
                if result is not None:
                    return result
            stdout, returncode, stderr = route.next_values()
            if kwargs.get("check") and returncode != 0:
                raise subprocess.CalledProcessError(
                    returncode, argv, output=stdout, stderr=stderr
                )
            return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    def matching(self, *tokens: str) -> list[list[str]]:
        """Return recorded argvs whose verb tokens start with tokens."""
        wanted = list(tokens)
        return [
            argv
            for argv in self.commands
            if _verb_tokens(argv)[: len(wanted)] == wanted
        ]

    def assert_sequence(self, *expected: str) -> None:
        """Assert the recorded verbs match expected verb prefixes, in order."""
        verbs = self.verbs
        assert len(verbs) == len(expected), (
            f"expected {list(expected)!r}, got {verbs!r}"
        )
        for actual, prefix in zip(verbs, expected, strict=True):
            assert actual.startswith(prefix), (
                f"expected {list(expected)!r}, got {verbs!r}"
            )

    def log_lines(self, *messages: str) -> str:
        """Return git log --format=%s%n%b%x1e style output for the given commit messages."""
        return "\n".join(f"{message}\n\x1e" for message in messages)

    def sha_subjects(self, *pairs: tuple[str, str]) -> str:
        """Return git log --format=%h%x09%s style output for the given (sha, subject) pairs."""
        return "".join(f"{sha}\t{subject}\n" for sha, subject in pairs)

    def sha_dated_subjects(self, *triples: tuple[str, str, str]) -> str:
        """Return git log --format=%H%x09%aI%x09%s output for (sha, subject, date) triples."""
        return "".join(f"{sha}\t{date}\t{subject}\n" for sha, subject, date in triples)


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> FakeSubprocess:
    """Patch subprocess.run with a FakeSubprocess instance and return it."""
    fake = FakeSubprocess()
    monkeypatch.setattr(subprocess, "run", fake.run)
    return fake


def run_capturing_exit(func: Callable[[], int | None]) -> int | str | None:
    """Call `func`, returning its result or, on SystemExit, its exit code."""
    try:
        return func()
    except SystemExit as exc:
        return exc.code


_DEFAULT_AUTHORED_DATE = "2024-01-01T00:00:00+00:00"


def _log_predicate(
    range_suffix: str, field_count: int = 2
) -> Callable[[list[str]], bool]:
    fmt = "%H%x09%aI%x09%s" if field_count == 3 else "%H%x09%s"

    def predicate(argv: list[str]) -> bool:
        tokens = [t for t in _verb_tokens(argv) if t != "--no-merges"]
        return (
            len(tokens) == 4
            and tokens[:3] == ["log", f"--format={fmt}", "--reverse"]
            and tokens[3].endswith(range_suffix)
        )

    return predicate


def _dated(
    commits: Sequence[tuple[str, str]], dates: dict[str, str] | None
) -> list[tuple[str, str, str]]:
    dates = dates or {}
    return [
        (sha, subject, dates.get(sha, _DEFAULT_AUTHORED_DATE))
        for sha, subject in commits
    ]


def _commit_items(
    commits: Sequence[tuple[str, str]], dates: dict[str, str] | None
) -> list[dict[str, str]]:
    return [
        {
            "oid": sha,
            "messageHeadline": subject,
            "messageBody": "",
            "authoredDate": date,
        }
        for sha, subject, date in _dated(commits, dates)
    ]


class _ScopedFake:
    """Forwards route registration to a `FakeSubprocess`, pinned to one repo."""

    def __init__(self, fake: FakeSubprocess, repo: str | Path) -> None:
        self._fake = fake
        self._repo = repo

    def on(self, *tokens: str, **kwargs: Any) -> None:
        self._fake.on(*tokens, repo=self._repo, **kwargs)

    def on_match(self, predicate: Callable[[list[str]], bool], **kwargs: Any) -> None:
        self._fake.on_match(predicate, repo=self._repo, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._fake, name)


class ContributeRemote:
    """Fakes the git/gh commands `inventory()` issues, built on `FakeSubprocess`.

    `login` is fixed to `"tester"`. With `repo`, every route (including ones
    registered later through `fake`) matches only calls made for that repo, so
    several remotes can share one `FakeSubprocess`. Registers, and keeps live as more commits/PRs
    are added:

    - `git fetch --quiet --prune origin +refs/heads/tester/*:refs/remotes/origin/tester/*`
      - a no-op success, run before branches are read.
    - `git ls-remote --heads origin refs/heads/tester/*` - every registered branch.
    - `gh pr list --author @me --state all --json ...` - the same call `all_prs`
      makes, listing every registered PR.
    - `gh pr list --state open --author @me --json ...,isDraft,reviewDecision,body,commits` -
      every registered open PR, without its commits; `review` sets a PR's
      draft flag and review decision.
    - `gh pr view <number> --json commits` - one open PR's branch commits.
    - `gh pr list --state merged --author @me --json number,headRefName,title` -
      every merged PR, without its commits.
    - `gh pr view <number> --json commits` - one merged PR's own pre-merge
      commits, each carrying an `authoredDate`; `fail_pr_view` makes it error.
    - `git log --format=%H%x09%aI%x09%s --reverse <range>` for main (also
      carrying each commit's authored date) and `git log --format=%H%x09%s
      --reverse <range>` for each branch, matched by the range's `..main` or
      `..origin/<branch>` suffix so the caller's exact base ref does not matter.
    - `git show --pretty=format:%x00%H --name-only <sha>...` for every main
      commit's paths, in one call.
    - `git show -U0 <sha>...`, returning fake diff text containing the literal
      sha, for every registered commit - feed that text as `git patch-id
      --stable`'s `input` to get back `f"{ContributeRemote.patch_id(sha)} {sha}"`.
    """

    login = "tester"

    def __init__(self, fake: FakeSubprocess, repo: str | Path | None = None) -> None:
        """Wire fetch, ls-remote, `gh pr list/view` and `git patch-id` onto `fake`."""
        self.fake = (
            fake if repo is None else cast(FakeSubprocess, _ScopedFake(fake, repo))
        )
        self._heads: list[str] = []
        self._pr_items: list[dict[str, Any]] = []
        self._merged_items: list[dict[str, Any]] = []
        self._merged_commits: dict[int, list[dict[str, str]]] = {}
        self._failing_views: set[int] = set()
        self._known_shas: set[str] = set()
        self._branch_commits: dict[str, list[dict[str, str]]] = {}
        self._pr_extra_commits: dict[int, list[dict[str, str]]] = {}
        self._reviews: dict[int, tuple[bool, str]] = {}
        self._bodies: dict[int, str] = {}
        self._titles: dict[int, str] = {}
        self._pr_heads: dict[int, tuple[str, str]] = {}
        self._paths: dict[str, Sequence[str]] = {}
        self._register_fetch()
        self._register_ls_remote()
        self._register_pr_list()
        self._register_open_pr_list()
        self._register_merged_pr_list()
        self._register_merged_pr_view()
        self._register_patch_id()
        self._register_shows()

    @staticmethod
    def patch_id(sha: str) -> str:
        """Return the deterministic fake patch-id for a commit sha."""
        return f"patchid-{sha}"

    def main(
        self,
        *commits: tuple[str, str],
        dates: dict[str, str] | None = None,
        paths: dict[str, Sequence[str]] | None = None,
    ) -> None:
        """Register local main's (sha, subject) commits, oldest first.

        `dates` maps sha to its ``%aI`` authored date; unlisted shas default to
        `_DEFAULT_AUTHORED_DATE`. `paths` maps sha to the files it touches;
        unlisted shas touch an in-scope SKILL.md.
        """
        self._paths.update(paths or {})
        self._known_shas.update(sha for sha, _ in commits)
        self.fake.on_match(
            _log_predicate("..main", field_count=3),
            stdout=self.fake.sha_dated_subjects(*_dated(commits, dates)),
        )
        self._register_diffs(commits)

    def managed(
        self,
        slug: str,
        commits: Sequence[tuple[str, str]],
        pr: Pr | None = None,
    ) -> str:
        """Register an open (or no-PR) managed batch branch; return its branch name."""
        branch = batch_branch(self.login, slug)
        self._register_branch(branch, commits, pr)
        return branch

    def merged(
        self,
        slug: str,
        number: int,
        commits: Sequence[tuple[str, str]],
        dates: dict[str, str] | None = None,
    ) -> str:
        """Register a merged managed PR - its branch is gone (deleteBranchOnMerge)."""
        return self._register_merged_pr(
            batch_branch(self.login, slug), number, commits, dates
        )

    def merged_legacy(
        self,
        branch: str,
        number: int,
        commits: Sequence[tuple[str, str]],
        dates: dict[str, str] | None = None,
    ) -> str:
        """Register a merged legacy PR - its branch is gone (deleteBranchOnMerge)."""
        return self._register_merged_pr(branch, number, commits, dates)

    def _register_merged_pr(
        self,
        branch: str,
        number: int,
        commits: Sequence[tuple[str, str]],
        dates: dict[str, str] | None = None,
    ) -> str:
        pr = Pr(number, "MERGED", f"https://github.com/o/r/pull/{number}")
        self._known_shas.update(sha for sha, _ in commits)
        self._pr_items.append(self._pr_item(branch, pr))
        title = (
            commits[0][1]
            if len(commits) == 1
            else branch.rpartition("/")[2].replace("-", " ")
        )
        self._merged_items.append(
            {"number": number, "headRefName": branch, "title": title}
        )
        self._register_merged_commits(number, commits, dates)
        self._register_diffs(commits)
        return branch

    def closed(self, slug: str, number: int, commits: Sequence[tuple[str, str]]) -> str:
        """Register a closed (unmerged) managed PR; its branch is still on the remote."""
        branch = batch_branch(self.login, slug)
        pr = Pr(number, "CLOSED", f"https://github.com/o/r/pull/{number}")
        self._register_branch(branch, commits, pr)
        return branch

    def unmanaged_pr(
        self,
        branch: str,
        number: int,
        commits: Sequence[tuple[str, str]],
        dates: dict[str, str] | None = None,
    ) -> str:
        """Register an open PR on a branch outside the managed prefix."""
        pr = Pr(number, "OPEN", f"https://github.com/o/r/pull/{number}")
        self._register_branch(branch, commits, pr, dates)
        return branch

    def pr_extra_commits(
        self,
        number: int,
        commits: Sequence[tuple[str, str]],
        dates: dict[str, str] | None = None,
    ) -> None:
        """Add commits to an open PR's `gh pr view` that its branch log lacks."""
        self._pr_extra_commits[number] = _commit_items(commits, dates)

    def review(self, number: int, *, draft: bool = False, decision: str = "") -> None:
        """Set an open PR's draft flag and ``reviewDecision``."""
        self._reviews[number] = (draft, decision)

    def head(self, number: int, sha: str, base: str = "main") -> None:
        """Set an open PR's head commit and base branch."""
        self._pr_heads[number] = (sha, base)

    def body(self, number: int, text: str) -> None:
        """Set an open PR's body."""
        self._bodies[number] = text

    def title(self, number: int, text: str) -> None:
        """Set an open PR's title."""
        self._titles[number] = text

    def legacy(self, branch: str, pr: Pr | None = None) -> str:
        """Register a legacy `<login>/<slug>` branch (no commits) on the remote."""
        self._register_branch(branch, (), pr)
        return branch

    def _pr_item(self, branch: str, pr: Pr) -> dict[str, Any]:
        return {
            "number": pr.number,
            "state": pr.state,
            "url": pr.url,
            "headRefName": branch,
            "isDraft": pr.is_draft,
        }

    def _register_branch(
        self,
        branch: str,
        commits: Sequence[tuple[str, str]],
        pr: Pr | None,
        dates: dict[str, str] | None = None,
    ) -> None:
        self._heads.append(branch)
        self._branch_commits[branch] = _commit_items(commits, dates)
        self._known_shas.update(sha for sha, _ in commits)
        self.fake.on_match(
            _log_predicate(f"..origin/{branch}"),
            stdout=self.fake.sha_subjects(*commits),
        )
        self._register_diffs(commits)
        if pr is not None:
            self._pr_items.append(self._pr_item(branch, pr))

    def _register_diffs(self, commits: Sequence[tuple[str, str]]) -> None:
        for sha, _ in commits:
            self.fake.on(
                "log", "-1", "--format=%aI", sha, stdout="2020-01-01T00:00:00+00:00\n"
            )

    def _register_shows(self) -> None:
        def names(
            argv: list[str], kwargs: dict[str, Any]
        ) -> subprocess.CompletedProcess[str]:
            shas = argv[argv.index("--name-only") + 1 :]
            stdout = "".join(
                f"\x00{sha}\n"
                + "".join(
                    f"{path}\n"
                    for path in self._paths.get(
                        sha, ["src/llm_prompts/prompts/shared/skills/foo/SKILL.md"]
                    )
                )
                for sha in shas
            )
            return subprocess.CompletedProcess(argv, 0, stdout, "")

        def diffs(
            argv: list[str], kwargs: dict[str, Any]
        ) -> subprocess.CompletedProcess[str]:
            shas = argv[argv.index("-U0") + 1 :]
            stdout = "".join(f"commit {sha}\nfake diff {sha}\n" for sha in shas)
            return subprocess.CompletedProcess(argv, 0, stdout, "")

        self.fake.on("show", "--pretty=format:%x00%H", "--name-only", side_effect=names)
        self.fake.on("show", "-U0", side_effect=diffs)

    def _register_fetch(self) -> None:
        self.fake.on(
            "fetch",
            "--quiet",
            "--prune",
            "origin",
            f"+refs/heads/{self.login}/*:refs/remotes/origin/{self.login}/*",
        )

    def _register_merged_commits(
        self,
        number: int,
        commits: Sequence[tuple[str, str]],
        dates: dict[str, str] | None = None,
    ) -> None:
        self._merged_commits[number] = _commit_items(commits, dates)

    def fail_pr_view(self, number: int) -> None:
        """Make `gh pr view <number>` exit non-zero."""
        self._failing_views.add(number)

    def truncate_headline(
        self, number: int, sha: str, headline: str, body: str
    ) -> None:
        """Override a registered merged PR's single commit with a truncated headline.

        Simulates GitHub truncating `messageHeadline`, with the remainder of the
        subject moved to `messageBody`'s first line.
        """
        self._merged_commits[number] = [
            {
                "oid": sha,
                "messageHeadline": headline,
                "messageBody": body,
                "authoredDate": _DEFAULT_AUTHORED_DATE,
            }
        ]

    def _register_ls_remote(self) -> None:
        def side_effect(
            argv: list[str], kwargs: dict[str, Any]
        ) -> subprocess.CompletedProcess[str]:
            lines = [f"deadbeef\trefs/heads/{branch}" for branch in self._heads]
            return subprocess.CompletedProcess(argv, 0, "\n".join(lines), "")

        self.fake.on(
            "ls-remote",
            "--heads",
            "origin",
            f"refs/heads/{self.login}/*",
            side_effect=side_effect,
        )

    def _register_pr_list(self) -> None:
        def side_effect(
            argv: list[str], kwargs: dict[str, Any]
        ) -> subprocess.CompletedProcess[str]:
            items = [
                {**item, "isDraft": self._is_draft(item)} for item in self._pr_items
            ]
            return subprocess.CompletedProcess(argv, 0, json.dumps(items), "")

        self.fake.on(
            "gh",
            "pr",
            "list",
            "--author",
            "@me",
            "--state",
            "all",
            "--json",
            "number,state,url,headRefName,isDraft",
            side_effect=side_effect,
        )

    def _is_draft(self, item: dict[str, Any]) -> bool:
        return bool(self._reviews.get(item["number"], (item["isDraft"], ""))[0])

    def _register_open_pr_list(self) -> None:
        def side_effect(
            argv: list[str], kwargs: dict[str, Any]
        ) -> subprocess.CompletedProcess[str]:
            items = [
                {
                    **item,
                    "isDraft": self._is_draft(item),
                    "reviewDecision": self._reviews.get(item["number"], (False, ""))[1],
                    "body": self._bodies.get(item["number"], ""),
                    "title": self._titles.get(item["number"], ""),
                    **(
                        {
                            "headRefOid": self._pr_heads[item["number"]][0],
                            "baseRefName": self._pr_heads[item["number"]][1],
                        }
                        if item["number"] in self._pr_heads
                        else {}
                    ),
                }
                for item in self._pr_items
                if item["state"] == "OPEN"
            ]
            return subprocess.CompletedProcess(argv, 0, json.dumps(items), "")

        self.fake.on(
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--author",
            "@me",
            "--json",
            "number,state,url,headRefName,isDraft,reviewDecision,body,headRefOid,baseRefName,title",
            side_effect=side_effect,
        )

    def _register_merged_pr_list(self) -> None:
        def side_effect(
            argv: list[str], kwargs: dict[str, Any]
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                argv, 0, json.dumps(self._merged_items), ""
            )

        self.fake.on(
            "gh",
            "pr",
            "list",
            "--state",
            "merged",
            "--author",
            "@me",
            "--json",
            "number,headRefName,title",
            side_effect=side_effect,
        )

    def _open_pr_commits(self, number: int) -> list[dict[str, str]]:
        branch = next(
            item["headRefName"] for item in self._pr_items if item["number"] == number
        )
        return self._branch_commits[branch] + self._pr_extra_commits.get(number, [])

    def _register_merged_pr_view(self) -> None:
        def side_effect(
            argv: list[str], kwargs: dict[str, Any]
        ) -> subprocess.CompletedProcess[str]:
            number = int(argv[3])
            if number in self._failing_views:
                raise subprocess.CalledProcessError(1, argv, stderr="boom")
            commits = {
                "commits": self._merged_commits.get(number)
                or self._open_pr_commits(number)
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(commits), "")

        self.fake.on("gh", "pr", "view", side_effect=side_effect)

    def _register_patch_id(self) -> None:
        def side_effect(
            argv: list[str], kwargs: dict[str, Any]
        ) -> subprocess.CompletedProcess[str]:
            diff = kwargs.get("input") or ""
            lines = [
                f"{self.patch_id(sha)} {sha}" for sha in self._known_shas if sha in diff
            ]
            return subprocess.CompletedProcess(argv, 0, "\n".join(lines), "")

        self.fake.on("patch-id", "--stable", side_effect=side_effect)


@pytest.fixture
def contribute_remote(fake_subprocess: FakeSubprocess) -> ContributeRemote:
    """Return a `ContributeRemote` wired onto `fake_subprocess`."""
    return ContributeRemote(fake_subprocess)


@pytest.fixture(autouse=True)
def isolated_links_path(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point the persisted cross-repo links file at a per-test temporary path."""
    path = tmp_path_factory.mktemp("links") / "contribute-links.json"
    monkeypatch.setattr("llm_prompts.links.LINKS_PATH", path)
    return path


@pytest.fixture(autouse=True)
def isolated_config_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point every module-level path under the user's llm-prompts config dir at a per-test temporary dir."""
    config_dir = tmp_path_factory.mktemp("config")
    monkeypatch.setattr("llm_prompts.setup._CONFIG_DIR", config_dir)
    monkeypatch.setattr("llm_prompts.setup.CONFIG_PATH", config_dir / "config.toml")
    monkeypatch.setattr(
        "llm_prompts.manifest.MANIFEST_PATH", config_dir / "installed.json"
    )
    monkeypatch.setattr(
        "llm_prompts.manifest.RENDERED_RULES_DIR", config_dir / "rendered-rules"
    )
    monkeypatch.setattr(
        "llm_prompts.plugins._PLUGIN_DIR", config_dir / "plugin-sources"
    )
    return config_dir


class FakeGitHub:
    """Fake `github_api.urlopen`, routed by REST (method, path) or GraphQL query substring."""

    def __init__(self) -> None:
        """Start with no routes and no recorded requests."""
        self.requests: list[tuple[str, str, Any, dict[str, str]]] = []
        self._routes: list[tuple[str, str, list[Any]]] = []

    def on(self, method: str, path: str, *responses: Any) -> None:
        """Queue responses (bodies or exceptions) for a REST call; the last one repeats."""
        self._routes.append((method, path, list(responses)))

    def on_graphql(self, query_part: str, *responses: Any) -> None:
        """Queue responses for GraphQL calls whose query contains `query_part`."""
        self.on("POST", f"/graphql:{query_part}", *responses)

    def graphql_variables(self, query_part: str) -> list[dict[str, Any]]:
        """Return the variables of every recorded GraphQL call containing `query_part`."""
        return [
            body["variables"]
            for _, path, body, _ in self.requests
            if path == "/graphql" and query_part in body["query"]
        ]

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        """Replace `urlopen`: record the request and answer from the first matching route."""
        path = request.full_url.removeprefix("https://api.github.com")
        body = json.loads(request.data) if request.data else None
        headers = {key.lower(): value for key, value in request.header_items()}
        self.requests.append((request.get_method(), path, body, headers))
        key = path if body is None or "query" not in body else None
        for method, route, responses in self._routes:
            if method != request.get_method():
                continue
            if route.startswith("/graphql:") and body and "query" in body:
                matched = route.removeprefix("/graphql:") in body["query"]
            else:
                matched = route == key
            if matched:
                response = responses.pop(0) if len(responses) > 1 else responses[0]
                if isinstance(response, BaseException):
                    raise response
                return _FakeResponse(response)
        raise AssertionError(f"fake_github: unrouted {request.get_method()} {path}")


class _FakeResponse:
    def __init__(self, body: Any) -> None:
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._body).encode()


def http_error(code: int, message: str) -> urllib.error.HTTPError:
    """Build the HTTPError urlopen raises for a JSON error body."""
    body = io.BytesIO(json.dumps({"message": message}).encode())
    return urllib.error.HTTPError(
        "https://api.github.com", code, message, Message(), body
    )


@pytest.fixture
def fake_github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    """Patch github_api.urlopen with a FakeGitHub and provide a token."""
    fake = FakeGitHub()
    monkeypatch.setattr(github_api, "urlopen", fake)
    monkeypatch.setenv("GH_TOKEN", "test-token")
    return fake
