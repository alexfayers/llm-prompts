"""Print the session-start steps that apply."""

from __future__ import annotations

import argparse
from pathlib import Path

HOOKED_AGENTS = frozenset({"claude-code", "pi"})
SEARCH = (
    'Run `search_all_projects(query="task", {scope}entityType="task", '
    'status=["in-progress", "planned"], names_only=True, limit=500)`.'
)
SCOPE = 'projects=["global", "<repo-name>"], expand_groups=True, '
RULES = "Read `RULES.md` in the workspace root in full."
TODOS = "(Optional) Run the `todos` skill for file and code TODOs. Skip by default."
TABLE = (
    "Show ONE table of all memory tasks, grouped by project, in-progress first: "
    '`| Project | Status | Task | What it is |`. Leave "What it is" blank where the '
    "name says it. For in-progress tasks add the status or next step after it "
    "(`<what-it-is> - <status/next-step>`), omitted if none. "
    "Show a positive vote_score as stars after the task name. "
    "Call `get_entity_with_relations` only on tasks the user picks. "
    "If nothing was found, say nothing."
)
UPDATES = (
    "Summarize the source updates in plain language and flag breaking changes "
    "in the first reply, even if the opening message is about something else."
)
BRANCHES = (
    "Once per repo per session, run `git branch -v --no-merged <main-branch>` "
    "(or `git -P log --all --oneline --not --remotes --not <main-branch>`). "
    "If one looks like real work (not throwaway), mention it with the memory "
    "tasks and let the user decide. A tip far behind main is likely stale - say so."
)


def git_root() -> Path | None:
    """Return the nearest directory at or above the cwd that holds `.git`."""
    here = Path.cwd()
    return next(
        (
            directory
            for directory in (here, *here.parents)
            if (directory / ".git").exists()
        ),
        None,
    )


def find_in_workspace(name: str) -> Path | None:
    """Return `name` in the cwd, the git root or the git root's parent, if any."""
    root = git_root()
    candidates = (Path.cwd(), *((root, root.parent) if root else ()))
    return next((c / name for c in candidates if (c / name).is_file()), None)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(description="Print the session-start steps")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--outstanding", action="store_true")
    parser.add_argument("--everywhere", action="store_true")
    parser.add_argument("--updates", action="store_true")
    return parser


def build_steps(args: argparse.Namespace) -> list[str]:
    """Return the steps that apply to the agent in the current directory."""
    hooked = args.agent in HOOKED_AGENTS
    if not hooked and find_in_workspace("HANDOFF.md"):
        return ["Run the `pickup` skill and stop."]
    steps: list[str] = []
    if find_in_workspace("RULES.md"):
        steps.append(RULES)
    if not hooked:
        steps.append('Run `read_graph(project="<repo-name>")`.')
    if args.outstanding or args.everywhere:
        scope = "" if args.everywhere else SCOPE
        steps += [SEARCH.format(scope=scope), TABLE]
    if args.updates:
        steps.append(UPDATES)
    if args.outstanding or args.everywhere:
        steps.append(TODOS)
    if git_root():
        steps.append(BRANCHES)
    return steps


def main(argv: list[str] | None = None) -> int:
    """Parse args and print the numbered steps that apply."""
    args = build_parser().parse_args(argv)
    for number, step in enumerate(build_steps(args), start=1):
        print(f"{number}. {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
