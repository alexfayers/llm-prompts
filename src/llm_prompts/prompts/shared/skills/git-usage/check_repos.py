"""Report uncommitted and unpushed changes across the workspace and prompt-source repos."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

AGENTS = ("cline", "copilot", "kiro", "claude-code", "codex")


def source_paths() -> list[str]:
    """Return the deduped filesystem paths printed by `llm-prompts source <agent>` across all agents."""
    paths: list[str] = []
    for agent in AGENTS:
        try:
            result = subprocess.run(
                ["llm-prompts", "source", agent],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return []
        if result.returncode != 0:
            continue
        paths.extend(
            stripped
            for line in result.stdout.splitlines()
            if (stripped := line.strip()).startswith("/")
        )
    return list(dict.fromkeys(paths))


def git_toplevel(path: Path) -> str | None:
    """Return the git repository root containing path, or None if it is not tracked."""
    start = path if path.is_dir() else path.parent
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def collect_repos(workspace: Path) -> list[str]:
    """Return the deduped, ordered list of git repo roots to inspect."""
    roots: list[str] = []
    workspace_root = git_toplevel(workspace)
    roots.append(workspace_root if workspace_root else str(workspace.resolve()))
    for path in source_paths():
        root = git_toplevel(Path(path))
        if root:
            roots.append(root)
    return list(dict.fromkeys(roots))


def inspect_repo(repo: str) -> dict:
    """Report uncommitted changes, unpushed commits, and upstream state for one repo."""
    entry: dict = {
        "path": repo,
        "uncommitted": [],
        "unpushed": [],
        "no_upstream": False,
    }

    status = subprocess.run(
        ["git", "-C", repo, "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        entry["error"] = status.stderr.strip()
        return entry
    entry["uncommitted"] = [line for line in status.stdout.splitlines() if line]

    upstream = subprocess.run(
        [
            "git",
            "-C",
            repo,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if upstream.returncode != 0:
        entry["no_upstream"] = True
        return entry

    log = subprocess.run(
        ["git", "-C", repo, "log", "--oneline", "@{u}..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if log.returncode != 0:
        entry["error"] = log.stderr.strip()
        return entry
    entry["unpushed"] = [line for line in log.stdout.splitlines() if line]
    return entry


def check_repos(workspace: Path) -> dict:
    """Inspect every repo and return {repos, clean}; clean is true iff nothing outstanding."""
    repos = [inspect_repo(repo) for repo in collect_repos(workspace)]
    clean = all(
        not r["uncommitted"] and not r["unpushed"] and not r.get("error") for r in repos
    )
    return {"repos": repos, "clean": clean}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser: one optional `--workspace` (default current directory)."""
    parser = argparse.ArgumentParser(
        description="Report uncommitted/unpushed changes across the workspace and prompt-source repos"
    )
    parser.add_argument(
        "--workspace", default=".", help="Workspace directory to check (default: cwd)"
    )
    return parser


def main() -> None:
    """Parse args, run check_repos, dump JSON, and exit non-zero when anything is outstanding."""
    args = build_parser().parse_args()
    result = check_repos(Path(args.workspace))
    json.dump(result, sys.stdout, indent=2)
    sys.exit(0 if result["clean"] else 1)


if __name__ == "__main__":
    main()
