"""Gate a tidy-code diff on net line reduction. Fails when net additions exceed the neutral band."""

import argparse
import json
import subprocess
import sys

NEUTRAL_BAND = 5


def run_git_diff(range_arg: str | None) -> str:
    """Return `git diff --numstat` output for range_arg (default: working tree vs HEAD)."""
    cmd = ["git", "diff", "--numstat", range_arg if range_arg else "HEAD"]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return completed.stdout


def parse_numstat(output: str) -> tuple[int, int]:
    """Sum added/removed line counts from `git diff --numstat` output, skipping binaries."""
    added = 0
    removed = 0
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or parts[0] == "-" or parts[1] == "-":
            continue
        added += int(parts[0])
        removed += int(parts[1])
    return added, removed


def evaluate(added: int, removed: int) -> dict:
    """Classify a diff by net line change against the tidy-code threshold table."""
    net = added - removed
    if net < 0:
        passed, reason = True, "net-negative (deletions exceed insertions)"
    elif net <= NEUTRAL_BAND:
        passed, reason = (
            True,
            "neutral-cost (net within +/-5 lines; pass only with a clear maintainability win)",
        )
    else:
        passed, reason = (
            False,
            "net-positive (more than 5 lines added; revert unless it removes real complexity)",
        )
    return {
        "added": added,
        "removed": removed,
        "net": net,
        "pass": passed,
        "reason": reason,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser: one optional commit range (positional or --range)."""
    parser = argparse.ArgumentParser(
        description="Gate a tidy-code diff on net line reduction"
    )
    parser.add_argument(
        "range",
        nargs="?",
        default=None,
        help="Commit range to diff (e.g. '@{u}..'); default is working tree vs HEAD",
    )
    parser.add_argument(
        "--range",
        dest="range_flag",
        default=None,
        help="Alias for the positional range argument",
    )
    return parser


def main() -> None:
    """Parse args, diff via git, evaluate net reduction, dump JSON, exit 0/1."""
    args = build_parser().parse_args()
    added, removed = parse_numstat(run_git_diff(args.range_flag or args.range))
    result = evaluate(added, removed)
    json.dump(result, sys.stdout, indent=2)
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
