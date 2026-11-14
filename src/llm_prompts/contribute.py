"""Keep each worktree branch in sync with local main and its own PR.

A recorded worktree is any number of commits on its own branch. ``sync``
squashes them into one commit in local ``main``, pulls remote changes into the
worktree, pushes the branch and opens a draft PR once the entry is marked ready,
and removes the worktree after its PR merges.
"""

from __future__ import annotations

import graphlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, NamedTuple, TextIO

from . import github_api, main_sync, worktrees
from .exit_reason import ExitReason
from .network import run_with_retries, with_retries
from .worktrees import Link, WorktreeEntry

_DEPENDS_PREFIX = "Depends on "
_GENERATED_PREFIXES = ("- ", _DEPENDS_PREFIX)
_WHAT_HEADING = re.compile(r"^## What\n", re.MULTILINE)
_DEPENDENCIES_HEADING = re.compile(r"^## Dependencies\n", re.MULTILINE)
_HEADING = re.compile(r"^## ", re.MULTILINE)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BLANK_LINES = re.compile(r"\n{3,}")
_PR_TEMPLATE_PATH = ".github/PULL_REQUEST_TEMPLATE.md"
_FALLBACK_TEMPLATE = "## What\n\n## Why\n\n## Dependencies\n\n## Issues\n"
_SLUG_MAX_LEN = 50


class Commit(NamedTuple):
    """A single in-scope commit."""

    sha: str
    subject: str
    paths: tuple[str, ...]
    patch_id: str = ""
    authored_date: str = ""


class Pr(NamedTuple):
    """A GitHub pull request associated with a branch."""

    number: int
    state: str
    url: str
    is_draft: bool = False


class OpenPr(NamedTuple):
    """An open GitHub pull request with its review state and commits."""

    pr: Pr
    branch: str
    review_decision: str
    commits: tuple[Commit, ...]
    body: str = ""
    head_sha: str = ""
    base_branch: str = ""
    title: str = ""


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
    return run_with_retries(
        argv, cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def _git_network(*args: str, repo: Path) -> str:
    """Run a git command that contacts a remote against ``repo`` and return its stripped stdout."""
    return _run_with_retries(["git", "-C", str(repo), *args], repo).strip()


def _gh_json(*args: str, repo: Path) -> Any:
    """Run a ``gh`` command against ``repo`` and parse its stdout as JSON, if any."""
    stdout = _run_with_retries(["gh", *args], repo)
    return json.loads(stdout) if stdout.strip() else None


def _gh_installed() -> bool:
    """Return whether the gh CLI is on PATH."""
    return shutil.which("gh") is not None


_API_PR_QUALIFIERS = {"all": "", "open": "is:open", "merged": "is:merged"}


def _pr_list(repo: Path, state: str, fields: str) -> list[Any]:
    """List the current user's PRs in ``state`` with ``fields``, through gh or the GitHub API."""
    if _gh_installed():
        author_state = (
            ["--author", "@me", "--state", state]
            if state == "all"
            else ["--state", state, "--author", "@me"]
        )
        try:
            return list(
                _gh_json(
                    "pr",
                    "list",
                    *author_state,
                    "--json",
                    fields,
                    "--limit",
                    "1000",
                    repo=repo,
                )
            )
        except subprocess.CalledProcessError as error:
            raise ExitReason(
                "pr_list_failed", f"gh pr list failed: {first_stderr_line(error)}"
            ) from error
    return with_retries(
        partial(github_api.pr_list, repo, _API_PR_QUALIFIERS[state], fields.split(","))
    )


def _pr_view(repo: Path, number: int, fields: str) -> Any:
    """Fetch ``fields`` of PR ``number``, through gh or the GitHub API."""
    if _gh_installed():
        return _gh_json("pr", "view", str(number), "--json", fields, repo=repo)
    return with_retries(partial(github_api.pr_view, repo, number, fields.split(",")))


def fetch_base(repo: Path, remote: str) -> None:
    """Fetch ``main`` from ``remote`` so the base ref is up to date."""
    _git_network("fetch", "--quiet", remote, "main", repo=repo)


def base_ref(repo: Path) -> str:
    """Return the base ref to diff against: ``upstream/main`` post-fork, else ``origin/main``."""
    remotes = _git("remote", repo=repo).splitlines()
    return "upstream/main" if "upstream" in remotes else "origin/main"


def stale_main_warning(repo: Path, base: str) -> str | None:
    """Warn if a commit on ``main`` is already reachable from ``base`` (e.g. squash-merged upstream)."""
    output = _git("cherry", base, "main", repo=repo)
    if not any(line.startswith("-") for line in output.splitlines()):
        return None
    return (
        "warning: local main has commits already merged upstream that are not "
        f"ancestors of {base} - fix with: llm-prompts update"
    )


def _pr_commits_or_none(repo: Path, number: int) -> tuple[Commit, ...] | None:
    """Fetch a PR's commits, or ``None`` when the fetch fails."""
    try:
        return _pr_commits(repo, number)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def _pr_commits(repo: Path, number: int) -> tuple[Commit, ...]:
    """Fetch a PR's own commits via ``gh pr view``."""
    view = _pr_view(repo, number, "commits")
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
    items = _pr_list(
        repo,
        "open",
        "number,state,url,headRefName,isDraft,reviewDecision,body,headRefOid,baseRefName,title",
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
                pr=Pr(item["number"], item["state"], item["url"], item["isDraft"]),
                branch=item["headRefName"],
                review_decision=item["reviewDecision"] or "",
                commits=commits,
                body=item.get("body") or "",
                head_sha=item.get("headRefOid") or "",
                base_branch=item.get("baseRefName") or "",
                title=item.get("title") or "",
            )
        )
    return prs, frozenset(skipped)


def push_remote(repo: Path, fork: bool = True) -> tuple[str, bool]:
    """Return the remote to push PR branches to and whether it is a fork, forking first (when ``fork``) if write access is lacking."""
    if _gh_installed():
        view = _gh_json("repo", "view", "--json", "viewerPermission", repo=repo)
        permission = view.get("viewerPermission")
    else:
        permission = with_retries(partial(github_api.viewer_permission, repo))
    if permission in ("WRITE", "MAINTAIN", "ADMIN"):
        return "origin", False
    if _gh_installed():
        if fork:
            _gh_json("repo", "fork", "--remote", repo=repo)
    elif not github_api.has_upstream(repo):
        owner, name = github_api.base_repo(repo)
        raise ExitReason(
            "no_push_access",
            f"No push access to {owner}/{name} and gh is not installed: fork it on GitHub, "
            "run `git remote rename origin upstream` and `git remote add origin <fork-url>`, "
            "then rerun.",
        )
    return "origin", True


def pr_title(commits: Sequence[Commit]) -> str:
    """Return the first commit's subject, noting how many further commits the PR carries."""
    extra = len(commits) - 1
    return commits[0].subject + (f" (+{extra} more)" if extra else "")


def contribute_branch(login: str, branch: str) -> str:
    """Return the ``<login>/contribute/<branch>`` name a worktree branch is pushed under."""
    return f"{login}/contribute/{branch}"


def pr_template(repo: Path, base: str) -> str:
    """Return the PR template committed on ``base``, or a minimal one when it has none."""
    try:
        return _git("show", f"{base}:{_PR_TEMPLATE_PATH}", repo=repo)
    except subprocess.CalledProcessError:
        return _FALLBACK_TEMPLATE


def _what_lines(commits: Sequence[Commit]) -> list[str]:
    """Return the What section's subject bullets, one per commit."""
    return [f"- {commit.subject}" for commit in commits]


def _with_depends(
    body: str, depends_on: Sequence[str], dropped: Sequence[str] = ()
) -> str:
    """Return ``body`` with the Depends on lines for ``depends_on`` in its Dependencies section, else at its end.

    Sync owns the lines ``Depends on <ref>`` for each ref in ``depends_on`` and
    ``dropped``. Dropped ones are removed and all other lines are kept.
    """
    written = {f"{_DEPENDS_PREFIX}{ref}" for ref in (*depends_on, *dropped)}
    if not written:
        return body
    kept = "\n".join(
        line for line in body.rstrip().split("\n") if line not in written
    ).rstrip()
    if not depends_on:
        return f"{kept}\n" if kept != body.rstrip() else body
    block = "\n".join(f"{_DEPENDS_PREFIX}{ref}" for ref in depends_on)
    heading = _DEPENDENCIES_HEADING.search(f"{kept}\n")
    if heading is None:
        return f"{kept}\n\n{block}\n"
    text = f"{kept}\n"
    following = _HEADING.search(text, heading.end())
    end = following.start() if following else len(text)
    content = text[heading.end() : end].strip("\n")
    section = f"\n{content}\n{block}\n" if content else f"\n{block}\n"
    return text[: heading.end()] + section + (f"\n{text[end:]}" if following else "")


def pr_body(
    template: str, commits: Sequence[Commit], depends_on: Sequence[str] = ()
) -> str:
    """Return ``template`` without placeholder comments, with the What lines under its What heading and Depends on lines at the end."""
    lines = "\n".join(_what_lines(commits))
    template = _BLANK_LINES.sub("\n\n", _HTML_COMMENT.sub("", template))
    body, found = _WHAT_HEADING.subn(lambda m: f"{m[0]}\n{lines}\n", template, 1)
    return _with_depends(
        body if found else f"## What\n\n{lines}\n\n{template}", depends_on
    )


def rewrite_what(
    body: str,
    commits: Sequence[Commit],
    depends_on: Sequence[str] = (),
    dropped: Sequence[str] = (),
) -> str:
    """Return ``body`` with its What section's generated lines and trailing Depends on lines rebuilt, all else kept."""
    lines = _what_lines(commits)
    heading = _WHAT_HEADING.search(body)
    if heading is None:
        return _with_depends(
            "## What\n\n" + "\n".join(lines) + f"\n\n{body}", depends_on, dropped
        )
    following = _HEADING.search(body, heading.end())
    end = following.start() if following else len(body)
    section = body[heading.end() : end]
    old = section.lstrip("\n").split("\n")
    generated = next(
        (i for i, line in enumerate(old) if not line.startswith(_GENERATED_PREFIXES)),
        len(old),
    )
    stale = {f"{_DEPENDS_PREFIX}{ref}" for ref in (*depends_on, *dropped)}
    prose = "\n".join(
        line
        for i, line in enumerate(old)
        if line not in stale and (i >= generated or line.startswith(_DEPENDS_PREFIX))
    ).strip("\n")
    trailing = section[len(section.rstrip("\n")) :]
    rebuilt = "\n" + "\n".join(lines) + (f"\n\n{prose}" if prose else "") + trailing
    return _with_depends(
        body[: heading.end()] + rebuilt + body[end:], depends_on, dropped
    )


def refreshed_pr(
    title: str,
    body: str,
    commits: Sequence[Commit],
    depends_on: Sequence[str] = (),
    dropped: Sequence[str] = (),
) -> tuple[str, str] | None:
    """Return the PR title and body ``commits`` call for, or None when both are already current."""
    refreshed = pr_title(commits), rewrite_what(body, commits, depends_on, dropped)
    return None if refreshed == (title, body) else refreshed


def open_draft_pr(repo: Path, base: str, head: str, title: str, body: str) -> str:
    """Open a draft PR against ``base`` from ``head`` and return its URL."""
    branch = base.split("/", 1)[1]
    if not _gh_installed():
        return with_retries(
            partial(github_api.create_draft_pr, repo, branch, head, title, body)
        )
    argv = ["gh", "pr", "create", "--draft", "--base", branch]
    argv += ["--head", head, "--title", title, "--body", body]
    return _run_with_retries(argv, repo).strip()


def _contains(repo: Path, ancestor: str, sha: str) -> bool:
    """Return whether ``sha`` has ``ancestor`` in its history."""
    try:
        _git("merge-base", "--is-ancestor", ancestor, sha, repo=repo)
    except subprocess.CalledProcessError as error:
        if error.returncode == 1:
            return False
        raise
    return True


def behind_prs(
    repo: Path, base: str, remote: str, prs: Sequence[OpenPr]
) -> list[OpenPr]:
    """Return the PRs targeting ``main`` whose head lacks ``base``, oldest number first."""
    candidates = [pr for pr in prs if pr.head_sha and pr.base_branch == "main"]
    if candidates:
        _git_network(
            "fetch", "--quiet", remote, *(pr.head_sha for pr in candidates), repo=repo
        )
    return sorted(
        (pr for pr in candidates if not _contains(repo, base, pr.head_sha)),
        key=lambda pr: pr.pr.number,
    )


def first_stderr_line(error: subprocess.CalledProcessError) -> str:
    """Return the first line of a failed command's stderr."""
    return (error.stderr or "").strip().split("\n")[0]


def pr_title_body(repo: Path, number: int) -> tuple[str, str]:
    """Return the title and body of PR ``number``."""
    view = _pr_view(repo, number, "title,body")
    return view["title"] or "", view["body"] or ""


def edit_pr(repo: Path, number: int, title: str, body: str) -> None:
    """Replace the title and body of PR ``number``."""
    if _gh_installed():
        _run_with_retries(
            ["gh", "pr", "edit", str(number), "--title", title, "--body", body], repo
        )
    else:
        with_retries(partial(github_api.edit_pr, repo, number, title, body))


def update_pr_branch(repo: Path, number: int) -> None:
    """Rebase PR ``number``'s branch onto its base."""
    if _gh_installed():
        _run_with_retries(["gh", "pr", "update-branch", str(number), "--rebase"], repo)
    else:
        with_retries(partial(github_api.update_pr_branch, repo, number))


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


def _print_warning(warning: str, out: TextIO | None = None) -> None:
    for line in warning.splitlines():
        print(f"  {line}", file=out)


Target = tuple[str, Path, str]
Node = tuple[str, str]


def run_update(repo: Path, apply: bool, numbers: Collection[int] = ()) -> int:
    """Rebase the open PRs that are behind main onto it, or print the commands when not applying."""
    base = base_ref(repo)
    remote = base.split("/", 1)[0]
    fetch_base(repo, remote)
    prs, _ = open_prs(repo)
    behind = behind_prs(repo, base, remote, prs)
    if numbers:
        open_numbers = {open_pr.pr.number for open_pr in prs}
        behind_numbers = {open_pr.pr.number for open_pr in behind}
        for number in sorted(set(numbers) - open_numbers):
            print(f"#{number}: not one of your open PRs")
        for number in sorted(set(numbers) & open_numbers - behind_numbers):
            print(f"#{number}: already up to date with main")
        if set(numbers) - open_numbers:
            return 1
        behind = [open_pr for open_pr in behind if open_pr.pr.number in numbers]
    if not behind:
        print("nothing behind main")
        return 0
    if not apply:
        for open_pr in behind:
            print(f"gh pr update-branch {open_pr.pr.number} --rebase")
        return 0

    def update_one(open_pr: OpenPr) -> str:
        try:
            update_pr_branch(repo, open_pr.pr.number)
        except subprocess.CalledProcessError as error:
            return f"{open_pr.branch}: not updated ({first_stderr_line(error)})"
        return f"{open_pr.branch}: rebased onto main {open_pr.pr.url}"

    with ThreadPoolExecutor() as pool:
        lines = list(pool.map(update_one, behind))
    print("\n".join(lines))
    return int(any("not updated" in line for line in lines))


def update_targets(
    targets: Sequence[Target], apply: bool, numbers: Collection[int] = ()
) -> int:
    """Update each target's behind PRs in order and return the highest status."""
    status = 0
    for name, repo, _ in targets:
        if len(targets) > 1:
            print(f"[{name}]")
        status = max(status, run_update(repo, apply, numbers))
        if len(targets) > 1:
            print()
    return status


class SyncOptions(NamedTuple):
    """What a ``sync`` run was asked to do."""

    apply: bool = False
    branch: str | None = None
    forget: str | None = None
    ready: str | None = None
    local: str | None = None
    rescan: bool = False
    depends_on: tuple[str, str] | None = None
    no_depends_on: tuple[str, str] | None = None

    @property
    def record_edits(self) -> int:
        """How many record-edit flags the run was given."""
        return sum(
            map(
                bool,
                (
                    self.branch,
                    self.forget,
                    self.ready,
                    self.local,
                    self.depends_on,
                    self.no_depends_on,
                ),
            )
        )

    @property
    def edits_record(self) -> bool:
        """Whether the run only edits the record, with no network call."""
        return self.record_edits > 0


class Checkout(NamedTuple):
    """A branch checked out in a worktree of a repo."""

    path: Path
    branch: str


def _repo_key(repo: Path) -> str:
    return str(repo.expanduser().resolve())


def checkouts(repo: Path) -> list[Checkout]:
    """List the branches checked out in ``repo``'s linked worktrees."""
    found: list[Checkout] = []
    path: Path | None = None
    for line in _git("worktree", "list", "--porcelain", repo=repo).splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree ")).resolve()
        elif line.startswith("branch refs/heads/") and path is not None:
            found.append(Checkout(path, line.removeprefix("branch refs/heads/")))
    return [c for c in found if c.path != repo.resolve() and c.path.exists()]


def _record_branch(
    tool: str, repo: Path, entries: list[WorktreeEntry], branch: str
) -> str:
    key = _repo_key(repo)
    if any(e.repo == key and e.branch == branch for e in entries):
        return f"{branch}: already recorded"
    checkout = next((c for c in checkouts(repo) if c.branch == branch), None)
    if checkout is None:
        raise LookupError(f"{branch}: no worktree has this branch checked out")
    entries.append(WorktreeEntry(key, branch, str(checkout.path), None, None, None))
    return f"{branch}: recorded, local only until: llm-prompts contribute sync --tool {tool} --ready {branch}"


def _entry_edit(
    repo: Path,
    entries: list[WorktreeEntry],
    branch: str,
    edit: Callable[[WorktreeEntry], WorktreeEntry | None],
    done: str,
) -> str:
    key = _repo_key(repo)
    for index, entry in enumerate(entries):
        if entry.repo == key and entry.branch == branch:
            changed = edit(entry)
            if changed is None:
                del entries[index]
            else:
                entries[index] = changed
            return f"{branch}: {done}"
    raise LookupError(f"{branch}: not recorded")


def _find(
    entries: Sequence[WorktreeEntry], key: str, branch: str
) -> WorktreeEntry | None:
    return next((e for e in entries if (e.repo, e.branch) == (key, branch)), None)


def _spec_target(tools: Sequence[Target], spec: str) -> tuple[str, str]:
    """Return the repo key and branch a ``TOOL:BRANCH`` spec names."""
    tool, _, branch = spec.partition(":")
    repo = next((r for name, r, _ in tools if name == tool), None)
    if repo is None or not branch:
        raise LookupError(f"{spec}: not a TOOL:BRANCH of a locally cloned tool")
    return _repo_key(repo), branch


def _link_branches(
    repo: Path,
    entries: list[WorktreeEntry],
    tools: Sequence[Target],
    branch: str,
    spec: str,
) -> str:
    """Record that ``branch`` depends on the ``TOOL:BRANCH`` named by ``spec``."""
    lower_key, lower_branch = _spec_target(tools, spec)
    lower = _find(entries, lower_key, lower_branch)
    if lower is None:
        raise LookupError(f"{spec}: not recorded")
    dependent = _find(entries, _repo_key(repo), branch)
    if dependent is None:
        raise LookupError(f"{branch}: not recorded")
    if dependent.pr is not None:
        raise LookupError(
            f"{branch} already has PR #{dependent.pr}; links must be added before sync opens it"
        )
    if any(
        (k.repo, k.branch) == (lower_key, lower_branch) for k in dependent.depends_on
    ):
        raise LookupError(f"{branch} already depends on {spec}")
    link = Link(lower_key, lower_branch)
    if _has_cycle(entries, dependent, link):
        raise LookupError(f"{spec}: {branch} would make a cycle")
    base = None
    if lower_key == dependent.repo:
        if any(old.repo == dependent.repo for old in dependent.depends_on):
            raise LookupError(f"{branch} already stacks on another branch of this repo")
        base = _stack_base(repo, branch, lower_branch)
        _refuse_small_stack(repo, lower_branch, branch)
    return _entry_edit(
        repo,
        entries,
        branch,
        lambda e: e._replace(depends_on=(*e.depends_on, link), base=base or e.base),
        f"depends on {spec}",
    )


def _refuse_small_stack(repo: Path, lower: str, upper: str) -> None:
    """Raise when the diff the upper PR would show is small enough for one worktree."""
    lines, binary = _diff_lines(repo, base_ref(repo), f"refs/heads/{upper}")
    limit = yappy_limits()["lines"]
    if not binary and lines <= limit:
        raise LookupError(
            f"{lower} and {upper} change {lines} lines together, within the "
            f"slightly-yappy limit of {limit}. Combine them into one worktree."
        )


def _stack_base(repo: Path, upper: str, lower: str) -> str:
    """Return the tip of ``lower`` when ``upper`` is on it."""
    tip = _git("rev-parse", f"refs/heads/{lower}", repo=repo)
    upper_ref = f"refs/heads/{upper}"
    if not _contains(repo, tip, upper_ref):
        raise LookupError(f"{upper} is not on {lower}; rebase it onto {lower} first")
    return tip


def _without_link(entry: WorktreeEntry, link: Link) -> WorktreeEntry:
    """Return ``entry`` without ``link``; a ref sync wrote into a PR body is kept to be taken out again."""
    written = (link.ref,) if entry.pr is not None and link.ref else ()
    return entry._replace(
        depends_on=tuple(old for old in entry.depends_on if old != link),
        base=None if link.repo == entry.repo else entry.base,
        dropped_refs=(*entry.dropped_refs, *written),
    )


def _unlink_branches(
    repo: Path,
    entries: list[WorktreeEntry],
    tools: Sequence[Target],
    branch: str,
    spec: str,
) -> str:
    """Remove the link from ``branch`` to the ``TOOL:BRANCH`` named by ``spec``."""
    lower_key, lower_branch = _spec_target(tools, spec)
    dependent = _find(entries, _repo_key(repo), branch)
    link = next(
        (
            old
            for old in (dependent.depends_on if dependent else ())
            if (old.repo, old.branch) == (lower_key, lower_branch)
        ),
        None,
    )
    if link is None:
        raise LookupError(f"{branch} does not depend on {spec}")
    return _entry_edit(
        repo,
        entries,
        branch,
        lambda e: _without_link(e, link),
        f"no longer depends on {spec}",
    )


def _dependency_graph(entries: Sequence[WorktreeEntry]) -> dict[Node, set[Node]]:
    return {
        (e.repo, e.branch): {(link.repo, link.branch) for link in e.depends_on}
        for e in entries
    }


def _has_cycle(
    entries: Sequence[WorktreeEntry], dependent: WorktreeEntry, link: Link
) -> bool:
    graph = _dependency_graph(entries)
    graph[(dependent.repo, dependent.branch)].add((link.repo, link.branch))
    try:
        graphlib.TopologicalSorter(graph).prepare()
    except graphlib.CycleError:
        return True
    return False


def _dependencies_first(
    targets: Sequence[Target], entries: Sequence[WorktreeEntry]
) -> list[Target]:
    """Return ``targets`` with each tool after the tools its entries depend on, or as given when they depend on each other."""
    by_key = {_repo_key(target[1]): target for target in targets}
    graph = {
        key: {
            link.repo
            for e in entries
            if e.repo == key
            for link in e.depends_on
            if link.repo in by_key and link.repo != key
        }
        for key in by_key
    }
    try:
        return [by_key[key] for key in graphlib.TopologicalSorter(graph).static_order()]
    except graphlib.CycleError:
        return list(targets)


def edit_record(
    tool: str,
    repo: Path,
    entries: list[WorktreeEntry],
    options: SyncOptions,
    tools: Sequence[Target] = (),
) -> str:
    """Apply the record edit ``options`` asks for to ``entries`` and describe it."""
    if options.depends_on is not None:
        return _link_branches(repo, entries, tools, *options.depends_on)
    if options.no_depends_on is not None:
        return _unlink_branches(repo, entries, tools, *options.no_depends_on)
    if options.branch is not None:
        return _record_branch(tool, repo, entries, options.branch)
    if options.forget is not None:
        return _entry_edit(repo, entries, options.forget, lambda e: None, "forgotten")
    if options.ready is not None:
        return _entry_edit(
            repo,
            entries,
            options.ready,
            lambda e: e._replace(ready=True),
            "ready: sync may push it and open its draft PR",
        )
    if options.local is not None:
        return _entry_edit(
            repo,
            entries,
            options.local,
            lambda e: e._replace(ready=False),
            "local only: sync will not push it",
        )
    raise AssertionError("no record edit asked for")


class Tip(NamedTuple):
    """A recorded worktree's commits on its floor, oldest first, and why it is skipped, if it is."""

    entry: WorktreeEntry
    floor: str
    commits: list[str]
    skipped: str | None


def _tips(repo: Path, base: str, entries: Sequence[WorktreeEntry]) -> list[Tip]:
    """Return each entry's commits on its floor, which is the lower commit for a stacked entry."""
    return [
        Tip(
            entry,
            entry.base or base,
            _commit_shas(repo, entry.base or base, f"refs/heads/{entry.branch}"),
            _skip_reason(repo, base, entry, f"refs/heads/{entry.branch}", entries),
        )
        for entry in entries
    ]


def _patch_id(repo: Path, *diff_args: str) -> str:
    shown = _git(*diff_args, repo=repo)
    done = subprocess.run(
        ["git", "patch-id", "--stable"],
        cwd=repo,
        input=shown,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.split()[0] if done.stdout else ""


def _squash_patch_id(repo: Path, squash: main_sync.Squash) -> str:
    return _patch_id(repo, "diff", "-U0", squash.floor, squash.tip)


def _copies_of(
    repo: Path,
    base: str,
    squashes: Sequence[main_sync.Squash],
    copied: Mapping[str, str | None],
) -> dict[str, str]:
    """Map each squash's tip to its copy on main ahead of ``base``.

    A copy matches by the identity saved when it was copied, else by its first
    commit's author time and subject, else by the patch of the squash.
    """
    free = [
        row.split("\t", 2)
        for row in _git(
            "log", "--format=%H%x09%at%x09%s", f"{base}..main", repo=repo
        ).splitlines()
    ]
    identities = {
        squash.tip: _commit_identity(repo, squash.first).split("\t", 1)
        for squash in squashes
    }
    found: dict[str, str] = {}
    for tip, saved in copied.items():
        if match := next(
            (row for row in free if saved and row[1:] == saved.split("\t", 1)), None
        ):
            free.remove(match)
            found[tip] = match[0]
    for tip, identity in identities.items():
        if tip in found:
            continue
        if match := next((row for row in free if row[1:] == identity), None):
            free.remove(match)
            found[tip] = match[0]
    for squash in squashes:
        if squash.tip in found or not free:
            continue
        patch = _squash_patch_id(repo, squash)
        if match := next(
            (row for row in free if _patch_id(repo, "show", "-U0", row[0]) == patch),
            None,
        ):
            free.remove(match)
            found[squash.tip] = match[0]
    return found


def _main_changes(
    repo: Path, base: str, tips: Sequence[Tip]
) -> tuple[dict[str, main_sync.Squash], dict[str, str], list[main_sync.Squash]]:
    """Return the main commits to swap for newer squashes, the first commit each copy on main stands for, and the squashes main has no copy of."""
    swaps: dict[str, main_sync.Squash] = {}
    adds: list[main_sync.Squash] = []
    squashes = [
        main_sync.Squash(
            t.commits[-1],
            _git("merge-base", t.floor, t.commits[-1], repo=repo),
            t.commits[0],
        )
        for t in tips
    ]
    found = _copies_of(
        repo, base, squashes, {t.commits[-1]: t.entry.copied for t in tips}
    )
    copies: dict[str, str] = {}
    for squash in squashes:
        copy = found.get(squash.tip)
        if copy is None:
            adds.append(squash)
            continue
        copies[copy] = squash.first
        if _commit_identity(repo, copy) != _commit_identity(
            repo, squash.first
        ) or _patch_id(repo, "show", "-U0", copy) != _squash_patch_id(repo, squash):
            swaps[copy] = squash
    return swaps, copies, adds


_PR_URL_NUMBER = re.compile(r"/pull/(\d+)")


def _commit_of(repo: Path, sha: str) -> Commit:
    subject = _git("log", "-1", "--format=%s", sha, repo=repo)
    return Commit(sha, subject, ())


def _pr_number_of(repo: Path, branch: str) -> int:
    """Return the number of the open PR whose head is ``branch``, through gh or the GitHub API."""
    if _gh_installed():
        return int(
            _gh_json("pr", "view", branch, "--json", "number", repo=repo)["number"]
        )
    [pr] = [
        pr
        for pr in with_retries(
            partial(
                github_api.pr_list,
                repo,
                f"is:open head:{branch}",
                ["number", "headRefName"],
            )
        )
        if pr["headRefName"] == branch
    ]
    return int(pr["number"])


def _open_pr(
    repo: Path,
    base: str,
    branch: str,
    head_owner: str,
    commits: Sequence[Commit],
    depends_on: Sequence[str] = (),
) -> tuple[int, bool]:
    """Open a draft PR for ``branch`` and return its number, or that of the existing one and True."""
    try:
        url = open_draft_pr(
            repo,
            base,
            f"{head_owner}{branch}",
            pr_title(commits),
            pr_body(pr_template(repo, base), commits, depends_on),
        )
    except subprocess.CalledProcessError as error:
        if "already exists" not in (error.stderr or ""):
            raise
        return _pr_number_of(repo, branch), True
    return int(_PR_URL_NUMBER.search(url)[1]), False  # type: ignore[index]


class PrState(NamedTuple):
    """A PR as GitHub reports it right now."""

    state: str
    is_draft: bool
    head_sha: str
    title: str
    body: str
    head_ref: str = ""


_PR_STATE_FIELDS = "state isDraft headRefOid title body headRefName"


def pr_states(repo: Path, numbers: Sequence[int]) -> dict[int, PrState]:
    """Fetch the state of PRs ``numbers`` with one GraphQL query."""
    owner, name = github_api.base_repo(repo)
    aliases = " ".join(
        f"pr{n}: pullRequest(number: {n}) {{ {_PR_STATE_FIELDS} }}" for n in numbers
    )
    query = (
        "query($owner: String!, $name: String!) "
        f"{{ repository(owner: $owner, name: $name) {{ {aliases} }} }}"
    )
    if _gh_installed():
        data = _gh_json(
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            repo=repo,
        )["data"]
    else:
        data = with_retries(
            partial(github_api.graphql, query, {"owner": owner, "name": name})
        )
    found = data["repository"]
    return {
        n: PrState(
            item["state"],
            item["isDraft"],
            item["headRefOid"],
            item["title"] or "",
            item["body"] or "",
            item["headRefName"],
        )
        for n in numbers
        if (item := found.get(f"pr{n}")) is not None
    }


class _RepoSync:
    """One repo's sync: observe the remote, pull, copy into main, publish, remove merged worktrees."""

    def __init__(
        self,
        repo: Path,
        entries: list[WorktreeEntry],
        apply: bool,
        login: str,
        others: Sequence[WorktreeEntry] = (),
    ) -> None:
        self.repo = repo
        self.others = others
        self.apply = apply
        self.login = login
        self.entries = list(entries)
        self.status = 0
        self.base = base_ref(repo)
        self.remote_heads: dict[str, str] = {}
        self.prs: dict[int, PrState] = {}
        self._remote: tuple[str, bool] | None = None

    def remote(self) -> tuple[str, bool]:
        if self._remote is None:
            self._remote = push_remote(self.repo, fork=self.apply)
        return self._remote

    def remote_name(self, entry: WorktreeEntry) -> str:
        """Return the branch name the entry has on the remote: its PR's head, else under ``<login>/contribute/``."""
        pr = self.prs.get(entry.pr) if entry.pr is not None else None
        if pr is not None and pr.head_ref:
            return pr.head_ref
        return contribute_branch(self.login, entry.branch)

    def say(self, entry: WorktreeEntry, message: str) -> None:
        print(f"{entry.branch}: {message}")

    def fail(self, entry: WorktreeEntry, message: str) -> None:
        self.say(entry, message)
        self.status = 1

    def update(self, entry: WorktreeEntry, **changes: Any) -> WorktreeEntry:
        updated = entry._replace(**changes)
        self.entries[self.entries.index(entry)] = updated
        return updated

    def dependency(self, link: Link) -> WorktreeEntry | None:
        return _find([*self.entries, *self.others], link.repo, link.branch)

    def with_refs(self, entry: WorktreeEntry) -> tuple[WorktreeEntry, Link | None]:
        """Return ``entry`` with every link's ref filled in, and the first link whose dependency has no PR."""
        links = tuple(
            _with_ref(link, self.dependency(link)) for link in entry.depends_on
        )
        waiting = next((link for link in links if not link.ref), None)
        return self.update(entry, depends_on=links), waiting

    def tip(self, entry: WorktreeEntry) -> str:
        return _git("rev-parse", f"refs/heads/{entry.branch}", repo=self.repo)

    def skip_reason(self, entry: WorktreeEntry, ref: str) -> str | None:
        """Return why ``ref`` is not copied or pushed, or None when it has commits on the entry's floor."""
        return _skip_reason(self.repo, self.base, entry, ref, self.open_entries())

    def commits(self, entry: WorktreeEntry, ref: str) -> list[Commit]:
        """Return the entry's own commits on its base, oldest first."""
        return [
            _commit_of(self.repo, sha)
            for sha in _commit_shas(self.repo, entry.base or self.base, ref)
        ]

    def observe(self) -> None:
        numbers = [e.pr for e in self.entries if e.pr is not None]
        if numbers:
            self.prs = pr_states(self.repo, numbers)
            for entry in list(self.entries):
                if (pr := self.prs.get(entry.pr or 0)) is not None:
                    self.update(entry, pr_state=pr.state)
        pushed = [e for e in self.entries if e.pr is not None or e.remote_head]
        if pushed:
            remote, _ = self.remote()
            refs = [f"refs/heads/{self.remote_name(e)}" for e in pushed]
            listing = _git_network("ls-remote", remote, *refs, repo=self.repo)
            self.remote_heads = {
                ref.removeprefix("refs/heads/"): sha
                for sha, _, ref in (row.partition("\t") for row in listing.splitlines())
            }
            if self.remote_heads:
                specs = [
                    f"+refs/heads/{b}:refs/remotes/{remote}/{b}"
                    for b in self.remote_heads
                ]
                _git_network("fetch", "--quiet", remote, *specs, repo=self.repo)

    def relation(self, entry: WorktreeEntry) -> str:
        """Compare the worktree tip with the remote branch: none, pull, push, force or diverged."""
        tip, head = self.tip(entry), self.remote_heads.get(self.remote_name(entry))
        if head is None or head == tip:
            return "none"
        if _contains(self.repo, tip, head):
            return "pull"
        if _contains(self.repo, head, tip):
            return "push"
        if entry.remote_head == head:
            return "force"
        return "pull" if entry.remote_head == tip else "diverged"

    def pull(self, entry: WorktreeEntry) -> WorktreeEntry:
        name = self.remote_name(entry)
        head = self.remote_heads[name]
        remote, _ = self.remote()
        reason = self.skip_reason(entry, f"refs/remotes/{remote}/{name}")
        if reason is not None:
            self.say(entry, f"skipped: the remote branch has {reason}")
            return entry
        if not self.apply:
            self.say(entry, "would pull the remote branch into the worktree")
            return entry
        done = subprocess.run(
            ["git", "-C", entry.path, "reset", "--keep", head],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            self.fail(entry, f"not pulled ({done.stderr.strip()})")
            return entry
        self.say(entry, "pulled the remote branch into the worktree")
        return self.update(entry, remote_head=head)

    def blocker(self, entry: WorktreeEntry, tip: str) -> str | None:
        """Return why a merged worktree must stay, or None when it holds nothing the PR lacks."""
        pr = self.prs[entry.pr or 0]
        if above := self.stacked_on(entry):
            return f"{above[0].branch} sits on it"
        if tip != pr.head_sha:
            return "the branch has commits the PR lacks"
        if _git("status", "--porcelain", repo=Path(entry.path)):
            return "the worktree has uncommitted changes"
        own = set(_git("rev-list", f"{self.base}..{tip}", repo=self.repo).split())
        stashed_on = {
            line.split()[0]
            for line in _git(
                "stash", "list", "--format=%P", repo=self.repo
            ).splitlines()
        }
        if stashed_on & own:
            return "a stash is based on the branch"
        return None

    def remove_merged(self) -> None:
        for entry in list(self.entries):
            if not self.merged(entry) or not Path(entry.path).exists():
                continue
            if reason := self.blocker(entry, self.tip(entry)):
                self.say(entry, f"merged, but {reason}; kept")
                continue
            if not self.apply:
                self.say(entry, "merged: would remove the worktree and branch")
                continue
            _remove_worktree(self.repo, Path(entry.path))
            _git("branch", "-D", entry.branch, repo=self.repo)
            self.entries.remove(entry)
            self.say(entry, "merged: removed the worktree and branch")

    def stack_link(self, entry: WorktreeEntry) -> Link | None:
        return next((k for k in entry.depends_on if k.repo == entry.repo), None)

    def stacked_on(self, lower: WorktreeEntry) -> list[WorktreeEntry]:
        """Return the unmerged entries stacked directly on ``lower``."""
        return [
            e
            for e in self.open_entries()
            if (link := self.stack_link(e)) and link.branch == lower.branch
        ]

    def above(self, branch: str) -> list[str]:
        """Return the branches that sit on ``branch``, directly or not."""
        found: list[str] = []
        pending = [branch]
        while pending:
            lower = pending.pop()
            for entry in self.entries:
                link = self.stack_link(entry)
                if link and link.branch == lower and entry.branch not in found:
                    found.append(entry.branch)
                    pending.append(entry.branch)
        return found

    def edit_blocker(self, entry: WorktreeEntry) -> str | None:
        """Return why sync must not rewrite ``entry``'s branch or PR body, or None when it may."""
        if entry.pr is not None:
            pr = self.prs.get(entry.pr)
            if pr is None or not pr.is_draft:
                return f"PR #{entry.pr} is not a draft"
        if operation := main_sync._operation_in_progress(Path(entry.path)):
            return f"a {operation} is in progress"
        if _git("status", "--porcelain", repo=Path(entry.path)):
            return "the worktree has uncommitted changes"
        return None

    def on(self, entry: WorktreeEntry, ref: str) -> bool:
        """Return whether the entry's branch sits on ``ref``."""
        return _contains(self.repo, ref, f"refs/heads/{entry.branch}")

    def restack(self) -> None:
        """Rebase each stacked branch onto its lower's new tip, or onto main once the lower merged or its unpublished branch was deleted, lowest first."""
        held: set[str] = set()
        for entry in self.open_entries():
            link = self.stack_link(entry)
            lower = self.dependency(link) if link else None
            if (
                link is None
                or lower is None
                or entry.base is None
                or not Path(entry.path).exists()
            ):
                continue
            merged = self.merged(lower)
            abandoned = not merged and not _branch_exists(self.repo, lower.branch)
            if abandoned and lower.pr is not None:
                continue
            released = merged or abandoned
            if link.branch in held:
                held.add(entry.branch)
                continue
            target = self.base if released else self.tip(lower)
            if target == entry.base and not released:
                continue
            named = (
                f"main ({lower.branch} {'was deleted' if abandoned else 'merged'})"
                if released
                else lower.branch
            )
            if self.on(entry, target) and not abandoned:
                self.update(
                    entry,
                    **(
                        _without_link(entry, link)._asdict()
                        if released
                        else {"base": target}
                    ),
                )
                continue
            reason = self.edit_blocker(entry)
            if reason is None and not self.on(entry, entry.base):
                reason = "it is not on its base"
            if reason is None and not self.apply:
                self.say(entry, f"would restack onto {named}")
                continue
            if reason is None:
                done = subprocess.run(
                    ["git", "-C", entry.path, "rebase", "--onto", target, entry.base],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if done.returncode != 0:
                    subprocess.run(
                        ["git", "-C", entry.path, "rebase", "--abort"],
                        capture_output=True,
                        check=False,
                    )
                    reason = "the rebase does not apply"
            if reason is not None:
                held.add(entry.branch)
                above = self.above(entry.branch)
                left = f"; {', '.join(above)} left alone too" if above else ""
                self.say(entry, f"not restacked ({reason}){left}")
                continue
            if released:
                entry = self.update(entry, **_without_link(entry, link)._asdict())
            else:
                entry = self.update(entry, base=target)
            self.say(entry, f"restacked onto {named}")

    def open_entries(self) -> list[WorktreeEntry]:
        """Return the unmerged entries with each stack lower before the branches above it."""
        open_ = {
            e.branch: e
            for e in self.entries
            if not self.merged(e) and _branch_exists(self.repo, e.branch)
        }
        graph = {
            branch: {
                link.branch
                for link in entry.depends_on
                if link.repo == entry.repo and link.branch in open_
            }
            for branch, entry in open_.items()
        }
        return [
            open_[branch] for branch in graphlib.TopologicalSorter(graph).static_order()
        ]

    def merged(self, entry: WorktreeEntry) -> bool:
        pr = self.prs.get(entry.pr) if entry.pr is not None else None
        return pr is not None and pr.state == "MERGED"

    def forget_gone(self) -> None:
        """Drop entries with no worktree, deleting the branch of a merged one that holds nothing new."""
        checked_out = {c.branch: c.path for c in checkouts(self.repo)}
        for entry in list(self.entries):
            if entry.branch in checked_out:
                self.update(entry, path=str(checked_out[entry.branch]))
                continue
            exists = _branch_exists(self.repo, entry.branch)
            if (above := self.stacked_on(entry)) and (
                exists or entry.pr is None or self.merged(entry)
            ):
                state = "merged" if self.merged(entry) else "worktree is gone"
                self.say(entry, f"{state}, but {above[0].branch} sits on it; kept")
                continue
            if (
                self.merged(entry)
                and exists
                and self.tip(entry) == self.prs[entry.pr or 0].head_sha
            ):
                if self.apply:
                    _git("branch", "-D", entry.branch, repo=self.repo)
                self.say(entry, "merged: worktree is gone; branch deleted")
            else:
                self.say(entry, "worktree is gone; forgotten")
            self.entries.remove(entry)

    def run(self) -> tuple[int, list[WorktreeEntry]]:
        fetch_base(self.repo, self.base.split("/", 1)[0])
        if (stale := stale_main_warning(self.repo, self.base)) is not None:
            _print_warning(stale)
        self.observe()
        self.restack()
        self.forget_gone()
        self.remove_merged()
        for entry in self.open_entries():
            if (
                self.skip_reason(entry, f"refs/heads/{entry.branch}") is None
                and self.relation(entry) == "pull"
            ):
                self.pull(entry)
        self.restack()
        self.copy_into_main()
        self.publish()
        return self.status, self.entries

    def copy_into_main(self) -> None:
        tips = _tips(self.repo, self.base, self.open_entries())
        for tip in tips:
            if tip.skipped is not None:
                self.say(tip.entry, f"skipped: {tip.skipped}")
        usable = [tip for tip in tips if tip.skipped is None]
        swaps, copies, adds = _main_changes(self.repo, self.base, usable)
        changed = {squash.tip for squash in [*swaps.values(), *adds]}
        result = None
        if self.apply and (
            swaps or adds or not _contains(self.repo, self.base, "refs/heads/main")
        ):
            result = main_sync.rebuild_local(self.repo, self.base, swaps, copies, adds)
            if result.mode == "failed":
                print(f"main not updated: {result.detail}")
                self.status = 1
                return
        skipped = {copy.first: copy.reason for copy in result.skipped} if result else {}
        for tip in usable:
            if tip.commits[0] in skipped:
                self.say(tip.entry, f"not copied into main: {skipped[tip.commits[0]]}")
            elif tip.commits[-1] in changed:
                verb = "copied" if self.apply else "would copy"
                self.say(tip.entry, f"{verb} into main")
        if self.apply:
            for tip in usable:
                self.update(
                    tip.entry,
                    copied=None
                    if tip.commits[0] in skipped
                    else _commit_identity(self.repo, tip.commits[0]),
                )

    def publish(self) -> None:
        for entry in self.open_entries():
            tip = self.tip(entry)
            if entry.ready and self.skip_reason(entry, tip) is None:
                self.publish_one(entry, tip)

    def publish_one(self, entry: WorktreeEntry, tip: str) -> None:
        entry, waiting = self.with_refs(entry)
        if entry.pr is None and waiting is not None:
            self.say(entry, f"waiting: {waiting.branch} has no PR yet")
            return
        relation = self.relation(entry)
        pr = self.prs.get(entry.pr) if entry.pr is not None else None
        if relation == "diverged":
            self.say(entry, "diverged from the remote branch; left alone")
            return
        if pr is not None and pr.state != "OPEN":
            self.say(entry, f"PR #{entry.pr} is {pr.state.lower()}; left alone")
            return
        if relation == "force" and pr is not None and not pr.is_draft:
            self.say(entry, f"PR #{entry.pr} is not a draft; not force-pushed")
            return
        name = self.remote_name(entry)
        if entry.pr is None and name not in self.remote_heads:
            action = "push and open a draft PR"
        elif relation in ("push", "force"):
            action = "push"
        else:
            action = ""
        if not self.apply:
            if action:
                self.say(entry, f"would {action}")
            return
        remote, forked = self.remote()
        number = entry.pr
        try:
            if action:
                lease: tuple[str, ...] = ()
                if relation == "force":
                    lease = (f"--force-with-lease={name}:{self.remote_heads[name]}",)
                _git_network(
                    "push",
                    *lease,
                    remote,
                    f"refs/heads/{entry.branch}:refs/heads/{name}",
                    repo=self.repo,
                )
                entry = self.update(entry, remote_head=tip)
            if number is None:
                head_owner = f"{self.login}:" if forked else ""
                number, adopted = _open_pr(
                    self.repo,
                    self.base,
                    name,
                    head_owner,
                    self.commits(entry, tip),
                    [link.ref for link in entry.depends_on],
                )
                entry = self.update(entry, pr=number, pr_state="OPEN")
                self.say(entry, f"pushed, opened draft PR #{number}")
                if adopted:
                    pr = pr_states(self.repo, [number]).get(number)
            elif action:
                self.say(entry, "pushed")
            if pr is not None:
                self.settle_body(entry, pr, tip)
        except subprocess.CalledProcessError as error:
            self.fail(entry, f"not pushed ({first_stderr_line(error)})")

    def settle_body(self, entry: WorktreeEntry, pr: PrState, tip: str) -> None:
        """Refresh a draft PR's title and body, or name a non-draft one whose Depends on lines are out of date."""
        if pr.is_draft:
            self.refresh(entry, pr, tip)
            return
        refs = [link.ref for link in entry.depends_on]
        if _with_depends(pr.body, refs, entry.dropped_refs) != pr.body:
            self.say(
                entry,
                f"PR #{entry.pr} is not a draft; Depends on lines left as they are",
            )

    def refresh(self, entry: WorktreeEntry, pr: PrState, tip: str) -> None:
        refreshed = refreshed_pr(
            pr.title,
            pr.body,
            self.commits(entry, tip),
            [link.ref for link in entry.depends_on],
            entry.dropped_refs,
        )
        if refreshed is not None:
            edit_pr(self.repo, int(entry.pr or 0), *refreshed)
            self.say(entry, f"updated PR #{entry.pr} title and What")
        self.update(entry, dropped_refs=())


def _branch_exists(repo: Path, branch: str) -> bool:
    done = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
        ],
        capture_output=True,
        check=False,
    )
    return done.returncode == 0


def _remove_worktree(repo: Path, path: Path) -> None:
    """Remove the worktree at ``path`` through Herdr when it has a workspace there, else through git."""
    if shutil.which("herdr"):
        listing = subprocess.run(
            ["herdr", "worktree", "list", "--cwd", str(repo)],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            found = json.loads(listing.stdout)["result"]["worktrees"]
        except (ValueError, KeyError):
            found = []
        workspace = next(
            (w.get("open_workspace_id") for w in found if Path(w["path"]) == path), None
        )
        if (
            workspace
            and subprocess.run(
                ["herdr", "worktree", "remove", "--workspace", workspace],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        ):
            return
    _git("worktree", "remove", str(path), repo=repo)


def _with_ref(link: Link, dependency: WorktreeEntry | None) -> Link:
    """Return ``link`` with the ``owner/repo#N`` of its dependency's PR once there is one; a ref never changes."""
    if link.ref or dependency is None or dependency.pr is None:
        return link
    owner, name = github_api.base_repo(Path(dependency.repo))
    return link._replace(ref=f"{owner}/{name}#{dependency.pr}")


def _cached_refs(entries: Sequence[WorktreeEntry]) -> list[WorktreeEntry]:
    """Return ``entries`` with every link's ref filled in where its dependency has a PR."""
    return [
        e._replace(
            depends_on=tuple(
                _with_ref(link, _find(entries, link.repo, link.branch))
                for link in e.depends_on
            )
        )
        for e in entries
    ]


def _sync_repo(
    repo: Path,
    entries: list[WorktreeEntry],
    apply: bool,
    login: str,
    others: Sequence[WorktreeEntry] = (),
) -> tuple[int, list[WorktreeEntry]]:
    """Sync one repo's recorded worktrees and return the status and the updated entries."""
    return _RepoSync(repo, entries, apply, login, others).run()


def rescan_record(repo: Path, entries: list[WorktreeEntry], login: str) -> list[str]:
    """Record each open PR of mine whose branch is checked out in a worktree; return what was added."""
    key = _repo_key(repo)
    open_by_branch = {
        item["headRefName"]: item
        for item in _pr_list(repo, "open", "number,headRefName,headRefOid")
    }
    lines: list[str] = []
    for checkout in checkouts(repo):
        item = open_by_branch.get(
            contribute_branch(login, checkout.branch)
        ) or open_by_branch.get(checkout.branch)
        if item is None:
            continue
        found = WorktreeEntry(
            key,
            checkout.branch,
            str(checkout.path),
            item["number"],
            "OPEN",
            item["headRefOid"],
        )
        old = next(
            (e for e in entries if (e.repo, e.branch) == (key, checkout.branch)), None
        )
        if old is None:
            entries.append(found)
        else:
            entries[entries.index(old)] = old._replace(
                path=found.path,
                pr=found.pr,
                pr_state=found.pr_state,
                remote_head=old.remote_head or found.remote_head,
            )
        lines.append(f"{checkout.branch}: recorded with PR #{item['number']}")
    return lines


def yappy_limits() -> dict[str, Any]:
    """Read the slightly-yappy limits shared with the PR template check."""
    return dict(
        json.loads((Path(__file__).parent / "yappy_limits.json").read_text("utf-8"))
    )


def _count_numstat(numstat: str) -> tuple[int, bool]:
    """Return the lines a numstat changes outside lockfiles, and whether it has a binary file."""
    lockfiles = set(yappy_limits()["lockfiles"])
    total, binary = 0, False
    for row in numstat.splitlines():
        added, deleted, path = row.split("\t", 2)
        if added == "-":
            binary = True
        elif path.rsplit("/", 1)[-1] not in lockfiles:
            total += int(added) + int(deleted)
    return total, binary


def _diff_lines(repo: Path, floor: str, ref: str) -> tuple[int, bool]:
    """Count the lines ``ref`` changes on ``floor`` outside lockfiles, and say whether it has a binary file."""
    return _count_numstat(
        _git("diff", "--numstat", "--no-renames", f"{floor}...{ref}", repo=repo)
    )


def _commit_shas(repo: Path, floor: str, ref: str) -> list[str]:
    """Return the commits ``ref`` has on ``floor``, oldest first."""
    return _git("rev-list", "--reverse", f"{floor}..{ref}", repo=repo).splitlines()


def _commit_identity(repo: Path, sha: str) -> str:
    return _git("log", "-1", "--format=%at%x09%s", sha, repo=repo)


def _on_main_only(repo: Path, base: str, entry: WorktreeEntry, sha: str) -> bool:
    """Return whether ``sha`` is on local main but not on ``base`` and is not the entry's own copy."""
    return (
        _contains(repo, sha, "main")
        and not _contains(repo, sha, base)
        and _commit_identity(repo, sha) != entry.copied
    )


def _held_branch(
    repo: Path,
    base: str,
    entry: WorktreeEntry,
    commits: Sequence[str],
    local_main: Sequence[str],
    entries: Sequence[WorktreeEntry],
) -> str | None:
    """Return a branch whose tip sits among ``commits``, or whose copy is among the ``local_main`` ones."""
    firsts = {
        other.branch: _commit_identity(repo, theirs[0])
        for other in entries
        if other.branch != entry.branch
        and _branch_exists(repo, other.branch)
        and (
            theirs := _commit_shas(
                repo, other.base or base, f"refs/heads/{other.branch}"
            )
        )
    }
    for sha in local_main:
        identity = _commit_identity(repo, sha)
        if held := next((b for b, first in firsts.items() if first == identity), None):
            return held
    return next(
        (
            other.branch
            for other in entries
            if other.branch in firsts
            and _git("rev-parse", f"refs/heads/{other.branch}", repo=repo) in commits
        ),
        None,
    )


def _skip_reason(
    repo: Path,
    base: str,
    entry: WorktreeEntry,
    ref: str,
    entries: Sequence[WorktreeEntry],
) -> str | None:
    """Return why ``ref`` is not copied or pushed, or None when it has commits of its own on its floor."""
    commits = _commit_shas(repo, entry.base or base, ref)
    if not commits:
        return "no commits"
    local_main = [sha for sha in commits if _on_main_only(repo, base, entry, sha)]
    if held := _held_branch(repo, base, entry, commits, local_main, entries):
        return f"holds commits of {held}"
    return "holds local main commits" if local_main else None


def _list_line(
    repo: Path, base: str, entry: WorktreeEntry, entries: Sequence[WorktreeEntry]
) -> str:
    floor, ref = entry.base or base, f"refs/heads/{entry.branch}"
    pr = f"PR #{entry.pr} ({entry.pr_state or 'unknown'})" if entry.pr else "no PR"
    if not _branch_exists(repo, entry.branch):
        detail = "skipped: branch is gone"
    elif (reason := _skip_reason(repo, base, entry, ref, entries)) is not None:
        detail = f"skipped: {reason}"
    else:
        count = len(_commit_shas(repo, floor, ref))
        lines = _diff_lines(repo, floor, ref)[0]
        detail = f"{count} commits, " if count > 1 else ""
        detail += f"{lines} lines"
        if lines > yappy_limits()["lines"]:
            detail += f" (over the {yappy_limits()['lines']}-line limit)"
    return f"{entry.branch}  {'ready' if entry.ready else 'local only'}  {pr}  {detail}"


def list_targets(targets: Sequence[Target]) -> int:
    """Print every recorded worktree from the record and local git, with no network calls."""
    try:
        entries = worktrees.load_entries(worktrees.record_path())
    except worktrees.CorruptRecord as error:
        print(error)
        return 1
    for name, repo, _ in targets:
        key = _repo_key(repo)
        if len(targets) > 1:
            print(f"[{name}]")
        base = base_ref(repo)
        mine = [e for e in entries if e.repo == key]
        unmerged = [e for e in mine if e.pr_state != "MERGED"]
        for entry in mine:
            print(_list_line(repo, base, entry, unmerged))
    return 0


def _sync_locked(
    targets: Sequence[Target],
    login: str,
    options: SyncOptions,
    tools: Sequence[Target],
) -> int:
    path = worktrees.record_path()
    try:
        entries = worktrees.load_entries(path)
    except worktrees.CorruptRecord as error:
        print(error)
        if not options.rescan:
            return 1
        entries = []
    editing = options.edits_record
    status = 0
    if not (editing or options.rescan):
        targets = _dependencies_first(targets, entries)
    for tool, repo, _ in targets:
        key = _repo_key(repo)
        if options.rescan:
            for line in rescan_record(repo, entries, login):
                print(line)
            continue
        if editing:
            try:
                print(edit_record(tool, repo, entries, options, tools))
            except LookupError as error:
                print(error)
                status = 1
            continue
        entries = _cached_refs(entries)
        mine = [e for e in entries if e.repo == key]
        others = [e for e in entries if e.repo != key]
        repo_status, updated = _sync_repo(repo, mine, options.apply, login, others)
        status = max(status, repo_status)
        entries = [e for e in entries if e.repo != key] + updated
    if editing or options.rescan or options.apply:
        worktrees.save_entries(path, entries)
    return status


def sync_targets(
    targets: Sequence[Target],
    login: str,
    options: SyncOptions,
    tools: Sequence[Target] = (),
) -> int:
    """Edit the record or sync each target's recorded worktrees; return the highest status.

    ``tools`` are the tools a link may name, ``targets`` when empty.
    """
    try:
        with worktrees.locked(worktrees.record_path()):
            return _sync_locked(targets, login, options, tools or targets)
    except worktrees.LockHeld as error:
        print(error)
        return 1
