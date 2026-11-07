"""Report a commit range's safety for rewriting via interactive rebase."""

import argparse
import json
import subprocess
import sys


def run_git(repo_args: list[str]) -> str:
    """Run a git command and return its stdout, raising on failure."""
    completed = subprocess.run(
        ["git", *repo_args], capture_output=True, text=True, check=True
    )
    return completed.stdout


def is_working_tree_dirty() -> bool:
    """Return True if the working tree has staged or unstaged changes."""
    return bool(run_git(["status", "--porcelain"]).strip())


def resolve_base(explicit_range: str | None) -> str:
    """Resolve the base ref for the range, falling back to --root with no upstream."""
    if explicit_range:
        return explicit_range
    try:
        return run_git(["rev-parse", "--abbrev-ref", "@{u}"]).strip()
    except subprocess.CalledProcessError:
        return "--root"


def range_args(base: str) -> list[str]:
    """Build the git rev-range args for base, handling the --root sentinel."""
    if base == "--root":
        return ["--root", "HEAD"]
    return [f"{base}..HEAD"]


def list_commits(base: str) -> list[dict[str, str]]:
    """List commits in the range as sha/subject pairs, oldest first."""
    output = run_git(["log", "--reverse", "--format=%H\t%s", *range_args(base)])
    commits = []
    for line in output.splitlines():
        sha, _, subject = line.partition("\t")
        commits.append({"sha": sha, "subject": subject})
    return commits


def has_merge_commits(base: str) -> bool:
    """Return True if any commit in the range has more than one parent."""
    return bool(run_git(["rev-list", "--min-parents=2", *range_args(base)]).strip())


def has_pushed_commits(base: str) -> bool:
    """Return True if any commit in the range is already reachable from the upstream."""
    args = range_args(base)
    try:
        unpushed = run_git(["rev-list", *args, "^@{u}"]).splitlines()
    except subprocess.CalledProcessError:
        return False
    return len(unpushed) < len(run_git(["rev-list", *args]).splitlines())


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser: one optional base ref or range."""
    parser = argparse.ArgumentParser(
        description="Report a commit range's safety for rewriting via interactive rebase"
    )
    parser.add_argument(
        "range",
        nargs="?",
        default=None,
        help="Base ref to diff against (default: the branch's upstream, @{u})",
    )
    return parser


def main() -> None:
    """Parse args, inspect the range, dump JSON, exit 0/1/2."""
    args = build_parser().parse_args()
    base = resolve_base(args.range)
    dirty = is_working_tree_dirty()
    try:
        commits = list_commits(base)
    except subprocess.CalledProcessError:
        print(json.dumps({"error": "no resolvable base (repo has no commits)"}))
        sys.exit(2)
    merges = has_merge_commits(base)
    pushed = has_pushed_commits(base)
    safe = not dirty and not merges and not pushed

    result = {
        "base": base,
        "working_tree_dirty": dirty,
        "commit_count": len(commits),
        "commits": commits,
        "has_merge_commits": merges,
        "has_pushed_commits": pushed,
        "safe_to_rewrite": safe,
    }
    json.dump(result, sys.stdout, indent=2)
    sys.exit(0 if safe else 1)


if __name__ == "__main__":
    main()
