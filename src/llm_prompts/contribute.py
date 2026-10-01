"""Manage derived PR branches for a repo's rule/skill-source commits.

``main`` is the single source of truth. A PR branch is a disposable export
built by cherry-picking specific ``main`` commits onto a fresh branch off the
upstream base - never by moving a branch pointer onto a ``main`` commit
directly, which would drag every earlier unmerged commit along too.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import cache, partial
from pathlib import Path
from typing import Any, Literal, NamedTuple, TextIO

from . import links
from .batching import (
    Batch,
    BatchPlan,
    SelectionError,
    append_groups,
    is_managed,
    match_commits,
    pending_plans,
    regression_warning,
    select_groups,
)
from .listing import Entry, classify, pr_only_warning, render
from .size_guard import check

_COMPRESSION_PREFIX = "chore: compress "
_CONVENTIONAL_PREFIX = re.compile(r"^[a-z]+(\([^)]*\))?!?: ", re.IGNORECASE)
_CONVENTIONAL_SUBJECT = re.compile(r"^[a-z]+(\([^)]*\))?!?: .+", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SLUG_MAX_LEN = 50
_TRANSIENT_FAILURE = re.compile(
    r"could not resolve host|unable to access|failed to connect|connection reset"
    r"|connection refused|connection timed out|operation timed out|timeout|early eof"
    r"|rpc failed|tls handshake|http 5|502|503|504",
    re.IGNORECASE,
)
_NETWORK_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1.0


class Commit(NamedTuple):
    """A single in-scope commit."""

    sha: str
    subject: str
    paths: tuple[str, ...]
    patch_id: str = ""
    authored_date: str = ""


class Group(NamedTuple):
    """One or two commits destined for a single PR branch."""

    commits: tuple[Commit, ...]
    slug: str
    branch: str
    problems: tuple[str, ...]


class Pr(NamedTuple):
    """A GitHub pull request associated with a branch."""

    number: int
    state: str
    url: str


class OpenPr(NamedTuple):
    """An open GitHub pull request with its review state and commits."""

    pr: Pr
    branch: str
    is_draft: bool
    review_decision: str
    commits: tuple[Commit, ...]
    body: str = ""


class Inventory(NamedTuple):
    """Remote batch and PR state needed to plan and report on pending commits."""

    batches: tuple[Batch, ...]
    done: frozenset[str]
    merged_prs: dict[str, tuple[int, str]]
    unmanaged: dict[str, Pr]
    legacy_orphans: tuple[str, ...]
    legacy_regressed: tuple[Batch, ...] = ()
    past_slugs: frozenset[str] = frozenset()
    skipped_prs: frozenset[int] = frozenset()
    commits: tuple[Commit, ...] = ()


class ApplyResult(NamedTuple):
    """Outcome of applying one batch plan to its branch."""

    outcome: Literal["picked", "conflict", "oversize"]
    mode: Literal["append", "rebuild", "new"]
    paths: tuple[str, ...]
    message: str


def _git(*args: str, repo: Path) -> str:
    """Run a git command against ``repo`` and return its stripped stdout."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _run_with_retries(argv: list[str], cwd: Path) -> str:
    """Run a network command in ``cwd`` and return its stdout, retrying transient failures with backoff."""
    run = partial(
        subprocess.run, argv, cwd=cwd, capture_output=True, text=True, check=True
    )
    for attempt in range(1, _NETWORK_ATTEMPTS):
        try:
            return run().stdout
        except subprocess.CalledProcessError as error:
            if not _TRANSIENT_FAILURE.search(error.stderr or ""):
                raise
            time.sleep(_RETRY_DELAY_SECONDS * attempt)
    return run().stdout


def _git_network(*args: str, repo: Path) -> str:
    """Run a git command that contacts a remote against ``repo`` and return its stripped stdout."""
    return _run_with_retries(["git", "-C", str(repo), *args], repo).strip()


def _gh_json(*args: str, repo: Path) -> Any:
    """Run a ``gh`` command against ``repo`` and parse its stdout as JSON, if any."""
    stdout = _run_with_retries(["gh", *args], repo)
    return json.loads(stdout) if stdout.strip() else None


def slug_for(subject: str) -> str:
    """Derive a branch-safe slug from a commit subject."""
    body = _CONVENTIONAL_PREFIX.sub("", subject, count=1)
    slug = _NON_ALNUM.sub("-", body.lower()).strip("-")
    if len(slug) <= _SLUG_MAX_LEN:
        return slug
    truncated = slug[:_SLUG_MAX_LEN]
    cut = truncated.rfind("-")
    return truncated[:cut] if cut > 0 else truncated


def branch_name(login: str, slug: str) -> str:
    """Build the ``<login>/<slug>`` branch name for a slug."""
    return f"{login}/{slug}"


def is_conventional(subject: str) -> bool:
    """Return whether a commit subject matches the conventional-commit format."""
    return bool(_CONVENTIONAL_SUBJECT.match(subject))


def _is_in_scope_candidate(commit: Commit, prefix: str) -> bool:
    return any(path.startswith(prefix) for path in commit.paths)


def _is_mixed_scope(commit: Commit, prefix: str) -> bool:
    in_scope = any(path.startswith(prefix) for path in commit.paths)
    out_of_scope = any(not path.startswith(prefix) for path in commit.paths)
    return in_scope and out_of_scope


def _manual_shas(commits: Sequence[Commit], prefix: str) -> frozenset[str]:
    """Return the shas of commits whose PR is opened by hand: code-only or mixed-scope."""
    return frozenset(
        commit.sha
        for commit in commits
        if not _is_in_scope_candidate(commit, prefix) or _is_mixed_scope(commit, prefix)
    )


def _make_group(
    commits: tuple[Commit, ...], login: str, problems: tuple[str, ...]
) -> Group:
    slug = slug_for(commits[-1].subject)
    if any(not is_conventional(commit.subject) for commit in commits):
        problems = (*problems, "non-conventional-subject")
    return Group(
        commits=commits, slug=slug, branch=branch_name(login, slug), problems=problems
    )


def _flag_slug_collisions(groups: list[Group]) -> list[Group]:
    counts: dict[str, int] = {}
    for group in groups:
        counts[group.branch] = counts.get(group.branch, 0) + 1
    return [
        group._replace(problems=(*group.problems, "slug-collision"))
        if counts[group.branch] > 1
        else group
        for group in groups
    ]


def group_commits(commits: Sequence[Commit], login: str, prefix: str) -> list[Group]:
    """Pair each compression commit with its following commit, else group singly.

    Mixed-scope commits never join a pair - each gets its own single-commit
    group carrying only the ``mixed-scope`` problem.
    """
    groupable = [
        (index, commit)
        for index, commit in enumerate(commits)
        if not _is_mixed_scope(commit, prefix)
    ]

    groups: dict[int, Group] = {
        index: Group(
            commits=(commit,),
            slug=slug_for(commit.subject),
            branch=branch_name(login, slug_for(commit.subject)),
            problems=("mixed-scope",),
        )
        for index, commit in enumerate(commits)
        if _is_mixed_scope(commit, prefix)
    }

    position = 0
    while position < len(groupable):
        index, commit = groupable[position]
        if not commit.subject.startswith(_COMPRESSION_PREFIX):
            groups[index] = _make_group((commit,), login, ())
            position += 1
            continue

        if position + 1 >= len(groupable):
            groups[index] = _make_group((commit,), login, ("unpaired-compression",))
            position += 1
            continue

        _, next_commit = groupable[position + 1]
        problems: tuple[str, ...] = ()
        if next_commit.subject.startswith(_COMPRESSION_PREFIX):
            problems = ("double-compression",)
        elif not _is_in_scope_candidate(next_commit, prefix):
            problems = ("compression-pairs-out-of-scope",)
        groups[index] = _make_group((commit, next_commit), login, problems)
        position += 2

    return _flag_slug_collisions([groups[index] for index in sorted(groups)])


def fetch_base(repo: Path, remote: str) -> None:
    """Fetch ``main`` from ``remote`` so the base ref is up to date."""
    _git_network("fetch", "--quiet", remote, "main", repo=repo)


def base_ref(repo: Path) -> str:
    """Return the base ref to diff against: ``upstream/main`` post-fork, else ``origin/main``."""
    remotes = _git("remote", repo=repo).splitlines()
    return "upstream/main" if "upstream" in remotes else "origin/main"


def stale_main_warning(repo: Path, base: str, remote: str) -> str | None:
    """Warn if a commit on ``main`` is already reachable from ``base`` (e.g. squash-merged upstream)."""
    output = _git("cherry", base, "main", repo=repo)
    if not any(line.startswith("-") for line in output.splitlines()):
        return None
    return (
        "warning: local main has commits already merged upstream that are not "
        f"ancestors of {base} - fix with: git fetch {remote} main && "
        f"git rebase {base}"
    )


def log_commits(repo: Path, base: str) -> list[Commit]:
    """List every commit between base and main with its paths, oldest first."""
    log_output = _git(
        "log", "--format=%H%x09%aI%x09%s", "--reverse", f"{base}..main", repo=repo
    )
    rows = []
    for line in log_output.splitlines():
        sha, _, rest = line.partition("\t")
        authored_date, _, subject = rest.partition("\t")
        rows.append((sha, authored_date, subject))
    paths_by_sha = _paths_by_sha(repo, [sha for sha, _, _ in rows])
    return [
        Commit(
            sha=sha,
            subject=subject,
            paths=paths_by_sha.get(sha, ()),
            authored_date=authored_date,
        )
        for sha, authored_date, subject in rows
    ]


def _paths_by_sha(repo: Path, shas: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Map each of ``shas`` to the paths it touches, from a single ``git show``."""
    if not shas:
        return {}
    output = _git("show", "--pretty=format:%x00%H", "--name-only", *shas, repo=repo)
    paths_by_sha = {}
    for chunk in output.split("\x00")[1:]:
        sha, *lines = chunk.splitlines()
        paths_by_sha[sha] = tuple(line for line in lines if line)
    return paths_by_sha


def scope_commits(commits: Sequence[Commit], prefix: str) -> list[Commit]:
    """Keep the scope-candidate commits of ``commits``, in order."""
    return [commit for commit in commits if _is_in_scope_candidate(commit, prefix)]


def remote_branches(repo: Path, login: str) -> set[str]:
    """List this login's PR branches that already exist on origin."""
    output = _git_network(
        "ls-remote", "--heads", "origin", f"refs/heads/{login}/*", repo=repo
    )
    branches = set()
    for line in output.splitlines():
        _, _, ref = line.partition("\t")
        if ref.startswith("refs/heads/"):
            branches.add(ref.removeprefix("refs/heads/"))
    return branches


def all_prs(repo: Path) -> list[tuple[str, Pr]]:
    """Fetch every PR (any state) authored by the current gh user, as (branch, Pr) pairs.

    Unlike a dict keyed by branch, this keeps every PR when GitHub reports more
    than one for the same branch name (e.g. an earlier closed PR alongside a
    later one that reused the branch).
    """
    items = _gh_json(
        "pr",
        "list",
        "--author",
        "@me",
        "--state",
        "all",
        "--json",
        "number,state,url,headRefName",
        "--limit",
        "1000",
        repo=repo,
    )
    return [
        (item["headRefName"], Pr(item["number"], item["state"], item["url"]))
        for item in items
    ]


def _pr_recency(pr: Pr) -> tuple[int, int]:
    """Sort key for picking one PR per branch: OPEN first, then MERGED, then newest."""
    rank = {"OPEN": 0, "MERGED": 1}.get(pr.state, 2)
    return (rank, -pr.number)


def _prs_by_branch(pairs: list[tuple[str, Pr]]) -> dict[str, Pr]:
    """Pick one PR per branch: an OPEN one if any, else MERGED, else the newest."""
    grouped: dict[str, list[Pr]] = {}
    for branch, pr in pairs:
        grouped.setdefault(branch, []).append(pr)
    return {branch: min(prs, key=_pr_recency) for branch, prs in grouped.items()}


def _pr_commits_or_none(repo: Path, number: int) -> tuple[Commit, ...] | None:
    """Fetch a PR's commits, or ``None`` when the fetch fails."""
    try:
        return _pr_commits(repo, number)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def _pr_commits(repo: Path, number: int) -> tuple[Commit, ...]:
    """Fetch a PR's own commits via ``gh pr view``."""
    view = _gh_json("pr", "view", str(number), "--json", "commits", repo=repo)
    return tuple(
        Commit(
            sha=commit["oid"],
            subject=_rejoin_headline(commit["messageHeadline"], commit["messageBody"]),
            paths=(),
            authored_date=commit["authoredDate"],
        )
        for commit in view["commits"]
    )


def open_prs(repo: Path) -> tuple[list[OpenPr], frozenset[int]]:
    """Fetch every open PR authored by the current gh user, plus the numbers whose commits could not be fetched."""
    items = _gh_json(
        "pr",
        "list",
        "--state",
        "open",
        "--author",
        "@me",
        "--json",
        "number,state,url,headRefName,isDraft,reviewDecision,body",
        "--limit",
        "1000",
        repo=repo,
    )
    prs: list[OpenPr] = []
    skipped: set[int] = set()
    with ThreadPoolExecutor() as pool:
        fetched = list(
            pool.map(lambda item: _pr_commits_or_none(repo, item["number"]), items)
        )
    for item, commits in zip(items, fetched, strict=True):
        if commits is None:
            skipped.add(item["number"])
            commits = ()
        prs.append(
            OpenPr(
                pr=Pr(item["number"], item["state"], item["url"]),
                branch=item["headRefName"],
                is_draft=item["isDraft"],
                review_decision=item["reviewDecision"] or "",
                commits=commits,
                body=item.get("body") or "",
            )
        )
    return prs, frozenset(skipped)


def current_login(repo: Path) -> str:
    """Return the current gh user's login."""
    return str(_gh_json("api", "user", "--jq", ".login", repo=repo)).strip()


def push_remote(repo: Path) -> str:
    """Return the remote to push PR branches to, forking first if write access is lacking."""
    view = _gh_json("repo", "view", "--json", "viewerPermission", repo=repo)
    if view.get("viewerPermission") in ("WRITE", "MAINTAIN", "ADMIN"):
        return "origin"
    _gh_json("repo", "fork", "--remote", repo=repo)
    return "origin"


def _branch_in_scope(repo: Path, base: str, remote_ref: str, prefix: str) -> bool:
    paths = _git(
        "diff", "--name-only", f"{base}...{remote_ref}", repo=repo
    ).splitlines()
    return any(path.startswith(prefix) for path in paths)


def _patch_ids(repo: Path, shas: Sequence[str]) -> dict[str, str]:
    """Map each of ``shas`` to its stable patch-id, computed from its own diff with no context."""
    if not shas:
        return {}
    diff = _git("show", "-U0", *shas, repo=repo)
    result = subprocess.run(
        ["git", "patch-id", "--stable"],
        cwd=repo,
        input=diff,
        capture_output=True,
        text=True,
        check=True,
    )
    return {
        sha: patch_id
        for patch_id, sha in (line.split() for line in result.stdout.splitlines())
    }


def _branch_commits(repo: Path, base: str, branch: str) -> tuple[Commit, ...]:
    """List a pushed branch's commits ahead of ``base``, with their patch-ids."""
    log_output = _git(
        "log", "--format=%H%x09%s", "--reverse", f"{base}..origin/{branch}", repo=repo
    )
    rows = [line.partition("\t") for line in log_output.splitlines()]
    patch_ids = _patch_ids(repo, [sha for sha, _, _ in rows])
    return tuple(
        Commit(sha=sha, subject=subject, paths=(), patch_id=patch_ids.get(sha, ""))
        for sha, _, subject in rows
    )


_ELLIPSIS = "\u2026"


def _rejoin_headline(headline: str, body: str) -> str:
    """Reassemble a GitHub-truncated headline using its commit body's first line.

    GitHub truncates a long ``messageHeadline`` with a trailing ellipsis, moving
    the rest of the subject to ``messageBody``'s first line, prefixed with the
    same ellipsis character.
    """
    body_first_line = body.splitlines()[0] if body else ""
    if headline.endswith(_ELLIPSIS) and body_first_line.startswith(_ELLIPSIS):
        return headline[:-1] + body_first_line[1:]
    return headline


def skipped_prs_warning(skipped: Collection[int]) -> str | None:
    """Warn that merged PRs could not be fetched, so their commits may be re-proposed."""
    if not skipped:
        return None
    numbers = ", ".join(f"#{number}" for number in sorted(skipped))
    return (
        f"warning: could not fetch merged PR {numbers} - their commits may be "
        "reported as pending until the fetch succeeds"
    )


def _merged_pr_commits(
    repo: Path, subjects: Collection[str]
) -> tuple[list[tuple[int, str, list[Commit]]], frozenset[int]]:
    """List the pre-merge commits of merged PRs that could match one of ``subjects``.

    A merged PR is fetched only when its title (a single-commit PR's subject) or
    its branch slug (a multi-commit batch's first subject) matches, and the
    number of one whose fetch fails is returned alongside the commits.
    """
    slugs = {slug_for(subject) for subject in subjects}
    items = _gh_json(
        "pr",
        "list",
        "--state",
        "merged",
        "--author",
        "@me",
        "--json",
        "number,headRefName,title",
        "--limit",
        "1000",
        repo=repo,
    )
    merged: list[tuple[int, str, list[Commit]]] = []
    skipped: set[int] = set()
    matching = [
        item
        for item in items
        if item["title"] in subjects or item["headRefName"].rpartition("/")[2] in slugs
    ]
    with ThreadPoolExecutor() as pool:
        fetched = list(
            pool.map(lambda item: _pr_commits_or_none(repo, item["number"]), matching)
        )
    for item, pr_commits in zip(matching, fetched, strict=True):
        if pr_commits is None:
            skipped.add(item["number"])
            continue
        merged.append((item["number"], item["headRefName"], list(pr_commits)))
    return merged, frozenset(skipped)


def _first_commit_author_date(repo: Path, sha: str) -> datetime:
    """Return `sha`'s author date, for chronological no-PR batch ordering.

    A rebuild resets a batch tip's committer date to the rebuild time, so the
    branch's first commit's author date is used instead - cherry-pick
    preserves author dates across rebuilds.
    """
    return datetime.fromisoformat(_git("log", "-1", "--format=%aI", sha, repo=repo))


def _same_instant(a: str, b: str) -> bool:
    """Return whether two ISO 8601 datetime strings denote the same instant."""
    return (
        bool(a) and bool(b) and datetime.fromisoformat(a) == datetime.fromisoformat(b)
    )


def _same_commit(a: Commit, b: Commit) -> bool:
    """Return whether two commits share a subject and authored instant."""
    return a.subject == b.subject and _same_instant(a.authored_date, b.authored_date)


def _open_pr_by_sha(
    commits: Sequence[Commit], prs: Sequence[OpenPr]
) -> dict[str, OpenPr]:
    """Map each commit to the first open PR holding a same-subject, same-instant commit."""
    by_sha: dict[str, OpenPr] = {}
    for commit in commits:
        for open_pr in prs:
            if any(_same_commit(pr_commit, commit) for pr_commit in open_pr.commits):
                by_sha[commit.sha] = open_pr
                break
    return by_sha


def _pr_only_commits(
    commits: Sequence[Commit], prs: Sequence[OpenPr], login: str
) -> dict[int, tuple[Commit, ...]]:
    """Map each unmanaged open PR to its commits that no local commit matches."""
    by_number: dict[int, tuple[Commit, ...]] = {}
    for open_pr in prs:
        if is_managed(open_pr.branch, login):
            continue
        missing = tuple(
            pr_commit
            for pr_commit in open_pr.commits
            if not any(_same_commit(pr_commit, commit) for commit in commits)
        )
        if missing:
            by_number[open_pr.pr.number] = missing
    return by_number


def inventory(repo: Path, login: str, base: str, prefix: str) -> Inventory:
    """Build the remote batch/PR state needed to plan and report on pending commits."""
    commits = log_commits(repo, base)
    scoped = scope_commits(commits, prefix)
    with ThreadPoolExecutor() as pool:
        merged_future = pool.submit(
            _merged_pr_commits, repo, {commit.subject for commit in scoped}
        )
        all_prs_future = pool.submit(all_prs, repo)
        _git_network(
            "fetch",
            "--quiet",
            "--prune",
            "origin",
            f"+refs/heads/{login}/*:refs/remotes/origin/{login}/*",
            repo=repo,
        )
        pushed_future = pool.submit(remote_branches, repo, login)
        patch_ids = _patch_ids(repo, [commit.sha for commit in scoped])
        main_commits = tuple(
            commit._replace(patch_id=patch_ids.get(commit.sha, "")) for commit in scoped
        )
        subject_counts: dict[str, int] = {}
        by_subject: dict[str, Commit] = {}
        for commit in main_commits:
            subject_counts[commit.subject] = subject_counts.get(commit.subject, 0) + 1
            by_subject[commit.subject] = commit
        merged_pr_commits, skipped_prs = merged_future.result()
        all_pr_pairs = all_prs_future.result()
        pushed = pushed_future.result()

    prs_by_branch = _prs_by_branch(all_pr_pairs)
    branches = pushed | {
        branch
        for branch, pr in prs_by_branch.items()
        if is_managed(branch, login) or pr.state == "MERGED"
    }

    batches: list[Batch] = []
    done: set[str] = set()
    merged_by_sha: dict[str, tuple[int, str]] = {}
    unmanaged: dict[str, Pr] = {}
    legacy_orphans: list[str] = []
    legacy_regressed: list[Batch] = []
    past_slugs: set[str] = set()

    for number, head_branch, merged_commits in merged_pr_commits:
        for pr_commit in merged_commits:
            main_commit = by_subject.get(pr_commit.subject)
            if (
                main_commit is not None
                and subject_counts.get(pr_commit.subject) == 1
                and _same_instant(main_commit.authored_date, pr_commit.authored_date)
            ):
                done.add(main_commit.sha)
                merged_by_sha[main_commit.sha] = (number, head_branch)

    for branch in sorted(branches):
        pr = prs_by_branch.get(branch)
        managed = is_managed(branch, login)
        slug = branch.removeprefix(f"{login}/contribute/") if managed else ""

        if pr is not None and pr.state == "MERGED":
            if managed:
                past_slugs.add(slug)
            continue

        if managed and pr is not None and pr.state != "OPEN":
            past_slugs.add(slug)
            continue

        if managed:
            branch_commits = _branch_commits(repo, base, branch)
            match = match_commits(branch_commits, main_commits)
            batches.append(Batch(branch, slug, pr, branch_commits, match))
            continue

        if pr is not None and pr.state == "OPEN":
            branch_commits = _branch_commits(repo, base, branch)
            match = match_commits(branch_commits, main_commits)
            for main_commit in match.owned.values():
                unmanaged[main_commit.sha] = pr
            continue

        if pr is None and _branch_in_scope(repo, base, f"origin/{branch}", prefix):
            branch_commits = _branch_commits(repo, base, branch)
            match = match_commits(branch_commits, main_commits)
            if match.unmatched:
                legacy_regressed.append(Batch(branch, "", None, branch_commits, match))
            else:
                legacy_orphans.append(branch)

    batches.sort(
        key=lambda batch: (
            (float(batch.pr.number), "")
            if batch.pr
            else (
                float("inf"),
                _first_commit_author_date(repo, batch.commits[0].sha)
                if batch.commits
                else datetime.max.replace(tzinfo=UTC),
            )
        )
    )
    return Inventory(
        batches=tuple(batches),
        done=frozenset(done),
        merged_prs=merged_by_sha,
        unmanaged=unmanaged,
        legacy_orphans=tuple(legacy_orphans),
        legacy_regressed=tuple(legacy_regressed),
        past_slugs=frozenset(past_slugs),
        skipped_prs=skipped_prs,
        commits=tuple(commits),
    )


def _cherry_pick_onto(
    repo: Path,
    branch: str,
    start: str,
    commits: tuple[Commit, ...],
    prefix: str,
    mode: Literal["append", "rebuild", "new"],
) -> ApplyResult:
    """Cherry-pick ``commits`` onto a fresh ``branch`` starting from ``start``.

    Deletes any pre-existing local branch of the same name first, so a batch can
    be re-applied after an earlier successful or conflicting run without the
    ``switch -c`` failing because that branch already exists.
    """
    if _git("branch", "--list", branch, repo=repo).strip():
        _git("branch", "-D", branch, repo=repo)
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        _git("worktree", "add", "--detach", str(tmp_dir), start, repo=repo)
        _git("switch", "-c", branch, start, repo=tmp_dir)
        try:
            _git("cherry-pick", *(commit.sha for commit in commits), repo=tmp_dir)
        except subprocess.CalledProcessError as error:
            paths = tuple(
                _git(
                    "diff", "--name-only", "--diff-filter=U", repo=tmp_dir
                ).splitlines()
            )
            stderr_lines = [line for line in error.stderr.splitlines() if line.strip()]
            message = stderr_lines[0] if stderr_lines else ""
            _git("cherry-pick", "--abort", repo=tmp_dir)
            return ApplyResult(
                outcome="conflict", mode=mode, paths=paths, message=message
            )
        result = check([tmp_dir / prefix])
        if not result.passed:
            return ApplyResult(
                outcome="oversize", mode=mode, paths=(), message=result.report
            )
        return ApplyResult(outcome="picked", mode=mode, paths=(), message="")
    finally:
        _git("worktree", "remove", "--force", str(tmp_dir), repo=repo)


def apply_batch(
    repo: Path, plan: BatchPlan, base: str, prefix: str, batch: Batch | None = None
) -> ApplyResult:
    """Apply a batch plan's groups onto its branch in a throwaway worktree.

    ``append`` starts from ``origin/<branch>``, keeping that branch's existing
    commits and cherry-picking only the groups from ``plan.groups`` not
    already present on it (per ``batch``, required for this mode); ``rebuild``
    and ``new`` start fresh from ``base`` and cherry-pick every one of
    ``plan.groups``' commits in order. An ``append`` whose cherry-pick
    conflicts falls back to a rebuild from ``base``, reporting
    ``mode="rebuild"``.

    Pushing the resulting branch is the caller's responsibility: plainly for an
    ``append`` result, ``--force-with-lease`` otherwise.
    """
    all_commits = tuple(commit for group in plan.groups for commit in group.commits)
    if plan.mode == "append":
        if batch is None:
            raise ValueError("append plan requires its existing batch")
        new_groups = append_groups(plan, batch)
        new_commits = tuple(commit for group in new_groups for commit in group.commits)
        result = _cherry_pick_onto(
            repo, plan.branch, f"origin/{plan.branch}", new_commits, prefix, "append"
        )
        if result.outcome == "conflict":
            return _cherry_pick_onto(
                repo, plan.branch, base, all_commits, prefix, "rebuild"
            )
        return result
    return _cherry_pick_onto(repo, plan.branch, base, all_commits, prefix, plan.mode)


def find_blocking_commits(
    groups: list[Group], group: Group, paths: tuple[str, ...]
) -> list[Commit]:
    """Find earlier in-scope commits (outside `group`) touching any of `paths`."""
    own_shas = {commit.sha for commit in group.commits}
    blockers: list[Commit] = []
    for earlier_group in groups:
        if earlier_group is group:
            break
        for commit in earlier_group.commits:
            if commit.sha in own_shas:
                continue
            if set(commit.paths) & set(paths):
                blockers.append(commit)
    return blockers


def _print_warning(warning: str, out: TextIO | None = None) -> None:
    for line in warning.splitlines():
        print(f"  {line}", file=out)


Target = tuple[str, Path, str]


class Report(NamedTuple):
    stale_warning: str | None
    entries: list[Entry]
    problems: list[Group]
    warnings: list[str]
    exit: int
    statuses: dict[tuple[str, str], links.Status]
    pr_bodies: dict[str, str]


def _pending_statuses(
    entries: Sequence[Entry], inv: Inventory, prs: Sequence[OpenPr]
) -> dict[tuple[str, str], links.Status]:
    """Map each pending commit's (subject, authored date) to its stage, PR url and branch."""
    urls = {batch.branch: batch.pr.url for batch in inv.batches if batch.pr}
    urls.update({open_pr.branch: open_pr.pr.url for open_pr in prs})
    return {
        (commit.subject, commit.authored_date): links.Status(
            entry.stage, urls.get(entry.branch), entry.branch or None
        )
        for entry in entries
        if entry.stage != "merged"
        for commit, _ in entry.lines
    }


def _probed_statuses(
    repo: Path,
    commits: Sequence[Commit],
    manual: Collection[str],
    statuses: dict[tuple[str, str], links.Status],
    probe: Collection[tuple[str, str]],
) -> dict[tuple[str, str], links.Status]:
    """Mark probed code-only commits with no PR as local only when no remote branch holds them.

    Identity is the exact sha, so a rebased copy on the remote reads as unpushed, and
    remote refs are only as fresh as the last fetch.
    """
    unpushed = {
        key: links.Status("local only", None, None)
        for commit in commits
        if commit.sha in manual
        and (key := (commit.subject, commit.authored_date)) in probe
        and statuses.get(key) == links.Status("needs PR", None, None)
        and not _git("branch", "-r", "--contains", commit.sha, repo=repo)
    }
    return {**statuses, **unpushed}


def collect_report(
    repo: Path,
    login: str,
    prefix: str,
    probe: Collection[tuple[str, str]] = frozenset(),
) -> Report:
    """Gather pending commits, classify them, and compute warnings and exit code.

    `probe` names (subject, authored date) keys of code-only commits to check against
    remote branches when they have no PR.
    """
    base = base_ref(repo)
    remote = base.split("/", 1)[0]
    with ThreadPoolExecutor() as pool:
        open_prs_future = pool.submit(open_prs, repo)
        fetch_base(repo, remote)
        stale_warning = stale_main_warning(repo, base, remote)

        inv = inventory(repo, login, base, prefix)
        prs, skipped_open = open_prs_future.result()
    commits = inv.commits
    in_scope = scope_commits(commits, prefix)
    code_only = _manual_shas(commits, prefix)
    groups = group_commits(in_scope, login, prefix)
    plans = pending_plans(groups, inv, login)
    entries, problems = classify(
        commits,
        groups,
        plans,
        inv,
        prs,
        _open_pr_by_sha(commits, prs),
        code_only,
        _pr_only_commits(commits, prs, login),
    )

    pr_only = pr_only_warning(entries)
    warnings = [
        warning
        for warning in (
            regression_warning(inv.batches + inv.legacy_regressed),
            pr_only,
            skipped_prs_warning(inv.skipped_prs | skipped_open),
        )
        if warning is not None
    ]
    needs_sync = any(entry.stage == "needs sync" for entry in entries)
    return Report(
        stale_warning,
        entries,
        problems,
        warnings,
        int(needs_sync or bool(problems or pr_only)),
        _probed_statuses(
            repo, commits, code_only, _pending_statuses(entries, inv, prs), probe
        ),
        {open_pr.branch: open_pr.body for open_pr in prs},
    )


def _print_report(
    report: Report,
    out: TextIO | None = None,
    notes: Mapping[str, Sequence[links.Note]] | None = None,
) -> None:
    if report.stale_warning is not None:
        _print_warning(report.stale_warning, out)
    for line in render(report.entries, report.problems, sys.stdout.isatty(), notes):
        print(line, file=out)
    for warning in report.warnings:
        _print_warning(warning, out)


def run_list(repo: Path, login: str, prefix: str, out: TextIO | None = None) -> int:
    """Print pending commits grouped by stage; exit 0 iff nothing needs sync or is a problem."""
    report = collect_report(repo, login, prefix)
    _print_report(report, out)
    return report.exit


def _held_reasons(
    groups: Sequence[Group], inv: Inventory, held: dict[str, str]
) -> dict[str, str]:
    """Expand `held` to the shas of each unowned group that holds a held commit."""
    owned = {
        commit.sha for batch in inv.batches for commit in batch.match.owned.values()
    }
    reasons: dict[str, str] = {}
    for group in groups:
        shas = [commit.sha for commit in group.commits]
        reason = next((held[sha] for sha in shas if sha in held), None)
        if reason is not None and not owned.intersection(shas):
            reasons.update(dict.fromkeys(shas, reason))
    return reasons


def run_sync(
    repo: Path,
    login: str,
    prefix: str,
    apply: bool,
    only: str | None,
    cleanup: str | None,
    commits: Sequence[str] = (),
    held: dict[str, str] | None = None,
) -> int:
    """Preview or apply pending batch plans, or clean up one legacy orphan branch.

    `held` maps commit shas to the unpushed dependency they wait on; each held
    commit's whole group is left out unless a batch already owns it.
    """
    base = base_ref(repo)
    remote = base.split("/", 1)[0]
    fetch_base(repo, remote)
    warning = stale_main_warning(repo, base, remote)
    if warning is not None:
        print(warning)

    inv = inventory(repo, login, base, prefix)
    batches_by_branch = {batch.branch: batch for batch in inv.batches}
    regression = regression_warning(inv.batches + inv.legacy_regressed)
    if regression is not None:
        print(regression)

    skipped = skipped_prs_warning(inv.skipped_prs)
    if skipped is not None:
        print(skipped)
        return 1

    if cleanup is not None:
        if cleanup not in inv.legacy_orphans:
            print(f"{cleanup} is not a legacy orphan branch; refusing to clean up")
            return 1
        _git_network("push", "origin", "--delete", cleanup, repo=repo)
        return 0

    groups = group_commits(scope_commits(inv.commits, prefix), login, prefix)
    selected = None
    if commits:
        try:
            selected = select_groups(commits, groups, inv)
        except SelectionError as error:
            print("\n".join(error.lines))
            return 1
    held_reasons = _held_reasons(groups, inv, held or {})
    if held_reasons:
        selected = (
            frozenset(commit.sha for group in groups for commit in group.commits)
            if selected is None
            else selected
        ) - held_reasons.keys()
    scoped = only is not None or bool(commits)
    plans = pending_plans(groups, inv, login, selected)
    if only is not None:
        plans = [plan for plan in plans if plan.branch == only]

    if not apply:
        for sha, reason in held_reasons.items():
            print(f"{sha}: held while {reason}")
        for plan in plans:
            pick_groups = plan.groups
            batch = batches_by_branch.get(plan.branch)
            if plan.mode == "append" and batch is not None:
                pick_groups = append_groups(plan, batch)
            shas = " ".join(
                commit.sha for group in pick_groups for commit in group.commits
            )
            start = f"origin/{plan.branch}" if plan.mode == "append" else base
            print(f"git worktree add --detach <tmp-dir> {start}")
            print(f"git switch -c {plan.branch} {start}")
            print(f"git cherry-pick {shas}")
            if plan.mode == "append":
                print(f"git push <remote> {plan.branch}")
            else:
                print(f"git push --force-with-lease <remote> {plan.branch}")
        if not scoped:
            for branch in inv.legacy_orphans:
                print(f"{branch}: would delete (orphan, no PR)")
        return 1 if regression is not None else 0

    remote = push_remote(repo)
    failure = regression is not None
    for plan in plans:
        result = apply_batch(
            repo, plan, base, prefix, batches_by_branch.get(plan.branch)
        )
        if result.outcome == "conflict":
            detail = f"{', '.join(result.paths)}: {result.message}"
            print(f"{plan.branch}: conflict ({detail})")
            if commits:
                picked = {c.sha for g in plan.groups for c in g.commits}
                blockers = {
                    b.sha: b
                    for g in plan.groups
                    for b in find_blocking_commits(groups, g, result.paths)
                    if b.sha not in picked and b.sha not in inv.done
                }
                if blockers:
                    listed = ", ".join(
                        f"{b.sha} {b.subject}" for b in blockers.values()
                    )
                    print(f"  blocked by earlier unselected commits: {listed}")
            failure = True
            continue
        if result.outcome == "oversize":
            print(f"{plan.branch}: size check failed\n{result.message}")
            failure = True
            continue
        force = () if result.mode == "append" else ("--force-with-lease",)
        try:
            _git_network("push", *force, remote, plan.branch, repo=repo)
        except subprocess.CalledProcessError:
            print(f"{plan.branch}: rejected")
            failure = True
            continue
        _git("branch", "-D", plan.branch, repo=repo)
        print(f"{plan.branch}: pushed")

    if not scoped:
        for branch in inv.legacy_orphans:
            _git_network("push", "origin", "--delete", branch, repo=repo)
            print(f"{branch}: deleted (orphan, no PR)")

    print()
    run_list(repo, login, prefix)
    return 1 if failure else 0


def _target_lookup(
    targets: Sequence[Target], configured: Callable[[], Sequence[Target]] | None
) -> tuple[Callable[[str], Target | None], Callable[[], set[str]]]:
    """Build lookups of a target by name and of every configured name; `configured` loads lazily."""
    every = cache(configured) if configured is not None else lambda: ()

    def find(name: str) -> Target | None:
        return next((t for t in targets if t[0] == name), None) or next(
            (t for t in every() if t[0] == name), None
        )

    return find, lambda: {t[0] for t in [*targets, *every()]}


def list_targets(
    targets: Sequence[Target],
    login: str,
    configured: Callable[[], Sequence[Target]] | None = None,
) -> int:
    """Report every target in parallel, along with the repos its links depend on, and print each in order."""
    find, configured_names = _target_lookup(targets, configured)
    names = [name for name, _, _ in targets]
    stored = [
        link
        for link in links.load_links(links.LINKS_PATH)
        if link.dependent_tool in names
    ]
    dependencies = {link.dependency_tool for link in stored}
    needed = [
        *targets,
        *filter(None, (find(n) for n in sorted(dependencies - set(names)))),
    ]
    with ThreadPoolExecutor() as pool:
        futures = {
            name: pool.submit(
                collect_report,
                repo,
                login,
                prefix,
                *([keys] if (keys := _dependency_keys(stored, name)) else []),
            )
            for name, repo, prefix in needed
        }
        reports = {name: future.result() for name, future in futures.items()}
    statuses = {name: report.statuses for name, report in reports.items()}
    annotations = links.annotate(
        links.prune(
            stored, {n: set(s) for n, s in statuses.items()}, configured_names()
        )
        if stored
        else (),
        statuses,
    )
    status = 0
    for name in names:
        if len(targets) > 1:
            print(f"[{name}]")
        report = reports[name]
        notes = {
            commit.sha: text
            for entry in report.entries
            for commit, _ in entry.lines
            if (
                text := links.describe(
                    annotations.get((name, commit.subject, commit.authored_date), ()),
                    report.pr_bodies.get(entry.branch) if entry.branch else None,
                )
            )
        }
        _print_report(report, notes=notes)
        status = max(status, report.exit)
        if len(targets) > 1:
            print()
    return status


def _dependency_keys(
    linked: Sequence[links.Link], tool: str
) -> frozenset[tuple[str, str]]:
    """Return the (subject, authored date) keys of `tool`'s commits that `linked` depends on."""
    return frozenset(
        (link.dependency_subject, link.dependency_date)
        for link in linked
        if link.dependency_tool == tool
    )


def _rewritten_commits(
    values: Sequence[str],
    commits_by_tool: dict[str, list[Commit]],
    find: Callable[[str], Target | None],
) -> dict[str, tuple[str, Commit]]:
    """Map each value that names an amended commit to the repo and commit that replaced it.

    An amended commit keeps its subject and authored date, so its old sha still
    resolves locally and is matched on those.
    """
    rewritten: dict[str, tuple[str, Commit]] = {}
    for value in dict.fromkeys(values):
        for tool, commits in commits_by_tool.items():
            target = find(tool)
            if target is None or not value.strip():
                continue
            shown = subprocess.run(
                [
                    "git",
                    "-C",
                    str(target[1]),
                    "show",
                    "-s",
                    "--format=%aI%x09%s",
                    value,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            date, _, subject = shown.stdout.strip().partition("\t")
            match = next(
                (c for c in commits if (c.subject, c.authored_date) == (subject, date)),
                None,
            )
            if shown.returncode == 0 and match is not None:
                rewritten[value] = (tool, match)
    return rewritten


def _held_commits(
    name: str,
    dependencies: Sequence[links.Link],
    find: Callable[[str], Target | None],
    login: str,
    local_commits: Sequence[Commit],
) -> dict[str, str]:
    """Map the shas of `name`'s commits waiting on an unpushed dependency to that dependency."""
    status_by_tool = {}
    for tool in {link.dependency_tool for link in dependencies}:
        target = find(tool)
        if target is not None:
            status_by_tool[tool] = collect_report(
                target[1], login, target[2], _dependency_keys(dependencies, tool)
            ).statuses
    annotations = links.annotate(dependencies, status_by_tool)
    reasons = {
        key: next(
            f"{a.dependency_tool}: {a.dependency_subject} is {a.stage}"
            for a in annotations[key]
            if a.stage in links.HELD_STAGES
        )
        for key in links.holds(dependencies, status_by_tool)
    }
    return {
        commit.sha: reasons[(name, commit.subject, commit.authored_date)]
        for commit in local_commits
        if (name, commit.subject, commit.authored_date) in reasons
    }


def sync_targets(
    targets: Sequence[Target],
    login: str,
    apply: bool,
    only: str | None,
    cleanup: str | None,
    commits: Sequence[str] = (),
    configured: Callable[[], Sequence[Target]] | None = None,
) -> int:
    """Sync every target, dependency repos first, holding commits whose linked dependency is unpushed.

    `--commit` values across several targets are resolved to their repos and
    link later repos' commits to earlier ones; `--apply` saves the links
    before any push.
    """
    find, configured_names = _target_lookup(targets, configured)
    names = [name for name, _, _ in targets]
    by_name = {target[0]: target for target in targets}
    ahead: dict[str, list[Commit]] = {}

    def local_commits(name: str) -> list[Commit]:
        if name not in ahead:
            target = find(name)
            assert target is not None
            ahead[name] = log_commits(target[1], base_ref(target[1]))
        return ahead[name]

    stored = links.load_links(links.LINKS_PATH)
    linked = stored
    selection: dict[str, list[str]] | None = None
    commit_of: dict[str, tuple[str, Commit]] = {}
    try:
        if len(targets) > 1 and commits:
            by_tool = {name: local_commits(name) for name in names}
            try:
                selection = links.resolve_commits(commits, by_tool)
            except SelectionError:
                selection = links.resolve_commits(
                    commits, by_tool, _rewritten_commits(commits, by_tool, find)
                )
            commit_of = {
                value: (tool, commit)
                for tool, values in selection.items()
                for value in values
                for commit in local_commits(tool)
                if commit.sha.startswith(value.strip().lower())
            }
            linked = links.add_links(
                stored,
                links.derive_links(
                    [
                        (tool, commit.subject, commit.authored_date)
                        for tool, commit in (
                            commit_of[v] for v in dict.fromkeys(commits)
                        )
                    ]
                ),
            )
        ordered = links.order_targets(names, linked)
    except SelectionError as error:
        print("\n".join(error.lines))
        return 1

    if linked:
        known = configured_names()
        linked = links.prune(
            linked,
            {
                tool: {(c.subject, c.authored_date) for c in local_commits(tool)}
                for link in linked
                for tool in (link.dependent_tool, link.dependency_tool)
                if tool in known
            },
            known,
        )
        if apply and linked != stored:
            links.save_links(links.LINKS_PATH, linked)

    status = 0
    for name in ordered:
        if selection is not None and name not in selection:
            continue
        _, repo, prefix = by_name[name]
        own_commits = commits
        manual_commits: list[Commit] = []
        if selection is not None:
            manual = _manual_shas(local_commits(name), prefix)
            own_commits = [
                v for v in selection[name] if commit_of[v][1].sha not in manual
            ]
            manual_commits = [
                commit_of[v][1]
                for v in selection[name]
                if commit_of[v][1].sha in manual
            ]
        dependencies = [link for link in linked if link.dependent_tool == name]
        held = (
            _held_commits(name, dependencies, find, login, local_commits(name))
            if dependencies
            else {}
        )
        extra_held = (held,) if held else ()
        if len(targets) > 1:
            print(f"[{name}]")
        for commit in manual_commits:
            print(
                f"{commit.sha[:7]}: code-only, open its PR by hand "
                "(llm-prompts-contribute skill)"
            )
        if selection is None or own_commits:
            status = max(
                status,
                run_sync(
                    repo, login, prefix, apply, only, cleanup, own_commits, *extra_held
                ),
            )
        if len(targets) > 1:
            print()
    return status
