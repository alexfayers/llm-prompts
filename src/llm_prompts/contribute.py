"""Manage derived PR branches for this repo's own rule/skill-source commits.

``main`` is the single source of truth. A PR branch is a disposable export
built by cherry-picking specific ``main`` commits onto a fresh branch off the
upstream base - never by moving a branch pointer onto a ``main`` commit
directly, which would drag every earlier unmerged commit along too.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

from .size_guard import check

PROMPTS_PREFIX = "src/llm_prompts/prompts/"

_COMPRESSION_PREFIX = "chore: compress "
_CONVENTIONAL_PREFIX = re.compile(r"^[a-z]+(\([^)]*\))?!?: ", re.IGNORECASE)
_CONVENTIONAL_SUBJECT = re.compile(r"^[a-z]+(\([^)]*\))?!?: .+", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SLUG_MAX_LEN = 50


class Commit(NamedTuple):
    """A single in-scope commit."""

    sha: str
    subject: str
    paths: tuple[str, ...]


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


class State(NamedTuple):
    """The classified sync state of one group/branch."""

    group: Group | None
    branch: str
    pushed: bool
    pr: Pr | None
    stale: bool


def _git(*args: str, repo: Path) -> str:
    """Run a git command against ``repo`` and return its stripped stdout."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _gh_json(*args: str, repo: Path) -> Any:
    """Run a ``gh`` command against ``repo`` and parse its stdout as JSON, if any."""
    completed = subprocess.run(
        ["gh", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout) if completed.stdout.strip() else None


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


def _is_in_scope_candidate(commit: Commit) -> bool:
    return any(path.startswith(PROMPTS_PREFIX) for path in commit.paths)


def _is_mixed_scope(commit: Commit) -> bool:
    in_scope = any(path.startswith(PROMPTS_PREFIX) for path in commit.paths)
    out_of_scope = any(not path.startswith(PROMPTS_PREFIX) for path in commit.paths)
    return in_scope and out_of_scope


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


def group_commits(commits: Sequence[Commit], login: str) -> list[Group]:
    """Pair each compression commit with its following commit, else group singly.

    Mixed-scope commits never join a pair - each gets its own single-commit
    group carrying only the ``mixed-scope`` problem.
    """
    groupable = [
        (index, commit)
        for index, commit in enumerate(commits)
        if not _is_mixed_scope(commit)
    ]

    groups: dict[int, Group] = {
        index: Group(
            commits=(commit,),
            slug=slug_for(commit.subject),
            branch=branch_name(login, slug_for(commit.subject)),
            problems=("mixed-scope",),
        )
        for index, commit in enumerate(commits)
        if _is_mixed_scope(commit)
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
        elif not _is_in_scope_candidate(next_commit):
            problems = ("compression-pairs-out-of-scope",)
        groups[index] = _make_group((commit, next_commit), login, problems)
        position += 2

    return _flag_slug_collisions([groups[index] for index in sorted(groups)])


def classify(
    group: Group | None,
    branch: str,
    remote_branches: set[str],
    pr: Pr | None,
    branch_subjects: tuple[str, ...],
    branch_diff: str,
    group_subjects: tuple[str, ...],
    group_diff: str,
) -> State:
    """Classify one branch's sync state from pre-fetched git/gh facts."""
    pushed = branch in remote_branches
    stale = not (branch_subjects == group_subjects and branch_diff == group_diff)
    return State(group=group, branch=branch, pushed=pushed, pr=pr, stale=stale)


def fetch_base(repo: Path, remote: str) -> None:
    """Fetch ``main`` from ``remote`` so the base ref is up to date."""
    _git("fetch", "--quiet", remote, "main", repo=repo)


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


def scope_commits(repo: Path, base: str) -> list[Commit]:
    """List every scope-candidate commit between base and main, oldest first."""
    log_output = _git(
        "log", "--format=%H%x09%s", "--reverse", f"{base}..main", repo=repo
    )
    commits = []
    for line in log_output.splitlines():
        sha, _, subject = line.partition("\t")
        paths = tuple(
            path
            for path in _git(
                "show", "--pretty=format:", "--name-only", sha, repo=repo
            ).splitlines()
            if path
        )
        commit = Commit(sha=sha, subject=subject, paths=paths)
        if _is_in_scope_candidate(commit):
            commits.append(commit)
    return commits


def remote_branches(repo: Path, login: str) -> set[str]:
    """List this login's PR branches that already exist on origin."""
    output = _git("ls-remote", "--heads", "origin", f"refs/heads/{login}/*", repo=repo)
    branches = set()
    for line in output.splitlines():
        _, _, ref = line.partition("\t")
        if ref.startswith("refs/heads/"):
            branches.add(ref.removeprefix("refs/heads/"))
    return branches


def open_prs(repo: Path) -> dict[str, Pr]:
    """Fetch every PR (any state) authored by the current gh user, keyed by branch."""
    items = _gh_json(
        "pr",
        "list",
        "--author",
        "@me",
        "--state",
        "all",
        "--json",
        "number,state,url,headRefName",
        repo=repo,
    )
    return {
        item["headRefName"]: Pr(item["number"], item["state"], item["url"])
        for item in items
    }


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


def _branch_subjects(repo: Path, base: str, remote_ref: str) -> tuple[str, ...]:
    output = _git("log", "--format=%s", "--reverse", f"{base}..{remote_ref}", repo=repo)
    return tuple(output.splitlines()) if output else ()


def _branch_diff(repo: Path, base: str, remote_ref: str) -> str:
    return _git("diff", f"{base}...{remote_ref}", repo=repo)


def _group_diff(repo: Path, group: Group) -> str:
    shas = [commit.sha for commit in group.commits]
    return _git("diff", f"{shas[0]}^", shas[-1], repo=repo)


def _compute(repo: Path, login: str, base: str) -> tuple[list[Group], dict[str, State]]:
    """Compute every group and its classified sync state."""
    commits = scope_commits(repo, base)
    groups = group_commits(commits, login)
    pushed_branches = remote_branches(repo, login)
    prs = open_prs(repo)

    states: dict[str, State] = {}
    expected_branches = {group.branch for group in groups if not group.problems}
    for group in groups:
        if group.problems:
            continue
        branch = group.branch
        group_subjects = tuple(commit.subject for commit in group.commits)
        group_diff = _group_diff(repo, group)
        if branch in pushed_branches:
            remote_ref = f"origin/{branch}"
            branch_subjects = _branch_subjects(repo, base, remote_ref)
            branch_diff = _branch_diff(repo, base, remote_ref)
        else:
            branch_subjects, branch_diff = (), ""
        states[branch] = classify(
            group,
            branch,
            pushed_branches,
            prs.get(branch),
            branch_subjects,
            branch_diff,
            group_subjects,
            group_diff,
        )

    for branch in sorted(pushed_branches - expected_branches):
        states[branch] = classify(
            None, branch, pushed_branches, prs.get(branch), (), "", (), ""
        )

    return groups, states


def apply_group(
    repo: Path, group: Group, base: str
) -> tuple[str, tuple[str, ...], str]:
    """Cherry-pick one group's commits onto a fresh branch in a throwaway worktree.

    Deletes any pre-existing local branch of the same name first, so a group can
    be re-applied after an earlier successful or conflicting run without the
    ``switch -c`` failing because that branch already exists.

    Returns ``("picked", (), "")`` on success, ``("conflict", paths, message)``
    on a failed cherry-pick, where ``paths`` are the conflicting file(s) and
    ``message`` is git's own error message, or ``("oversize", (), report)`` if
    the cherry-picked branch's prompts tree fails the size guard, where
    ``report`` is the check's report string. Pushing the resulting branch is
    the caller's responsibility.
    """
    if _git("branch", "--list", group.branch, repo=repo).strip():
        _git("branch", "-D", group.branch, repo=repo)
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        _git("worktree", "add", "--detach", str(tmp_dir), base, repo=repo)
        _git("switch", "-c", group.branch, base, repo=tmp_dir)
        try:
            _git("cherry-pick", *(commit.sha for commit in group.commits), repo=tmp_dir)
        except subprocess.CalledProcessError as error:
            paths = tuple(
                _git(
                    "diff", "--name-only", "--diff-filter=U", repo=tmp_dir
                ).splitlines()
            )
            stderr_lines = [line for line in error.stderr.splitlines() if line.strip()]
            message = stderr_lines[0] if stderr_lines else ""
            _git("cherry-pick", "--abort", repo=tmp_dir)
            return "conflict", paths, message
        result = check([tmp_dir / PROMPTS_PREFIX])
        if not result.passed:
            return "oversize", (), result.report
        return "picked", (), ""
    finally:
        _git("worktree", "remove", "--force", str(tmp_dir), repo=repo)


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


def _state_label(state: State) -> str:
    if state.group is None:
        return f"orphan ({state.pr.state.lower()})" if state.pr else "orphan (no PR)"
    if not state.pushed:
        return "new (no PR)"
    return "needs-sync" if state.stale else "ok"


def _print_table(rows: list[tuple[str, str, str, str]]) -> None:
    headers = ("BRANCH", "COMMITS", "PR", "STATE")
    all_rows = [headers, *rows]
    widths = [max(len(row[column]) for row in all_rows) for column in range(4)]
    for row in all_rows:
        print("  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)))


def run_list(repo: Path, login: str) -> int:
    """Print every group's sync state as a table; exit 0 iff nothing needs attention."""
    base = base_ref(repo)
    remote = base.split("/", 1)[0]
    fetch_base(repo, remote)
    warning = stale_main_warning(repo, base, remote)
    if warning is not None:
        print(warning)
    groups, states = _compute(repo, login, base)

    rows: list[tuple[str, str, str, str]] = []
    ok = True
    for group in groups:
        if group.problems:
            continue
        state = states[group.branch]
        label = _state_label(state)
        pr_text = f"#{state.pr.number}" if state.pr else "-"
        rows.append((group.branch, str(len(group.commits)), pr_text, label))
        if label not in ("ok", "new (no PR)"):
            ok = False

    for branch, state in states.items():
        if state.group is not None:
            continue
        label = _state_label(state)
        pr_text = f"#{state.pr.number}" if state.pr else "-"
        rows.append((branch, "-", pr_text, label))
        ok = False

    _print_table(rows)

    problem_groups = [group for group in groups if group.problems]
    if problem_groups:
        ok = False
        print("problems:")
        for group in problem_groups:
            for commit in group.commits:
                print(
                    f"  {commit.sha[:7]} {commit.subject} [{','.join(group.problems)}]"
                )

    return 0 if ok else 1


def run_sync(
    repo: Path, login: str, apply: bool, only: str | None, cleanup: str | None
) -> int:
    """Preview or apply pending group syncs, or clean up one orphan branch."""
    base = base_ref(repo)
    remote = base.split("/", 1)[0]
    fetch_base(repo, remote)
    warning = stale_main_warning(repo, base, remote)
    if warning is not None:
        print(warning)
    groups, states = _compute(repo, login, base)

    if cleanup is not None:
        state = states.get(cleanup)
        if state is None or state.group is not None:
            print(f"{cleanup} is not an orphan branch; refusing to clean up")
            return 1
        if state.pr is not None:
            _gh_json("pr", "close", str(state.pr.number), repo=repo)
        _git("push", "origin", "--delete", cleanup, repo=repo)
        return 0

    targets = [
        group
        for group in groups
        if not group.problems
        and (not states[group.branch].pushed or states[group.branch].stale)
    ]
    if only is not None:
        targets = [group for group in targets if group.branch == only]

    if not apply:
        for group in targets:
            shas = " ".join(commit.sha for commit in group.commits)
            print(f"git worktree add --detach <tmp-dir> {base}")
            print(f"git switch -c {group.branch} {base}")
            print(f"git cherry-pick {shas}")
            print(f"git push --force-with-lease <remote> {group.branch}")
        if only is None:
            for branch, state in states.items():
                if state.group is None and state.pr is None:
                    print(f"{branch}: would delete (orphan, no PR)")
        return 0

    remote = push_remote(repo)
    failure = False
    for group in targets:
        outcome, paths, message = apply_group(repo, group, base)
        if outcome == "conflict":
            detail = f"{', '.join(paths)}: {message}"
            blockers = find_blocking_commits(groups, group, paths)
            if blockers:
                names = ", ".join(
                    f'{commit.sha[:7]} "{commit.subject}"' for commit in blockers
                )
                detail += (
                    f" - depends on unmerged commit(s) {names}; squash them"
                    " together on main"
                )
            print(f"{group.branch}: conflict ({detail})")
            failure = True
            continue
        if outcome == "oversize":
            print(f"{group.branch}: size check failed\n{message}")
            failure = True
            continue
        try:
            _git("push", "--force-with-lease", remote, group.branch, repo=repo)
        except subprocess.CalledProcessError:
            print(f"{group.branch}: rejected")
            failure = True
            continue
        _git("branch", "-D", group.branch, repo=repo)
        print(f"{group.branch}: pushed")

    if only is None:
        for branch, state in states.items():
            if state.group is None and state.pr is None:
                _git("push", "origin", "--delete", branch, repo=repo)
                print(f"{branch}: deleted (orphan, no PR)")

    print()
    run_list(repo, login)
    return 1 if failure else 0
