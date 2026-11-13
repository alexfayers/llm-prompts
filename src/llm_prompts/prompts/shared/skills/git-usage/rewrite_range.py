"""Execute a scripted interactive rebase from a declarative JSON plan.

Covers reorder, drop, squash, and fixup - the operations `--autosquash`
cannot do on its own because it only relocates commits already marked
`amend!`/`fixup!`/`squash!`, and cannot reorder or drop arbitrary commits.

Plan format (a JSON array, oldest-first - the final desired top-to-bottom
order of the rebase todo list):

    [
      {"sha": "<full-or-abbrev-sha>", "verb": "pick"},
      {"sha": "<sha>", "verb": "drop"},
      {"sha": "<anchor-sha>", "verb": "pick"},
      {"sha": "<sha>", "verb": "squash", "message": "final combined subject"},
      {"sha": "<sha>", "verb": "fixup"}
    ]

`verb` is one of: pick, drop, squash, fixup, reword.
`message` is optional and only meaningful on a squash/reword line - it is
the new subject for the commit that results from that block (the block
is: the preceding `pick`/`squash`/`fixup` lines up to and including this
one). Every squash/reword block that sets `message` gets exactly one
custom commit message; blocks that don't set it keep git's default
(concatenated) message. Message overrides are applied strictly in the
top-to-bottom order they appear in the plan, since that is the order the
rebase invokes the commit-message editor.

Usage:
    python3 rewrite_range.py <plan.json> [<base-ref> | --root]

`base-ref` defaults to `@{u}`, else `--root`, as in inspect_range.py. `--root`
rebases from the first commit, so the range is every commit. The plan
MUST list every range commit once. Remove a commit with `drop`. Run
inspect_range.py first and get explicit user confirmation of the plan.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from inspect_range import list_commits, resolve_base

VALID_VERBS = {"pick", "drop", "squash", "fixup", "reword"}


def run_git(args: list[str]) -> str:
    """Run a git command and return its stdout, raising on failure."""
    completed = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    )
    return completed.stdout


def load_plan(plan_path: Path) -> list[dict[str, str]]:
    """Load and validate the JSON plan."""
    plan = json.loads(plan_path.read_text())
    if not isinstance(plan, list) or not plan:
        raise ValueError("plan must be a non-empty JSON array")
    for entry in plan:
        if "sha" not in entry or "verb" not in entry:
            raise ValueError(f"plan entry missing sha/verb: {entry}")
        if entry["verb"] not in VALID_VERBS:
            raise ValueError(f"invalid verb {entry['verb']!r} in entry: {entry}")
    return plan


def validate_coverage(plan: list[dict[str, str]], base: str) -> None:
    """Raise unless the plan names every commit in the range exactly once."""
    range_shas = [commit["sha"] for commit in list_commits(base)]
    matches = [
        [sha for sha in range_shas if entry["sha"] and sha.startswith(entry["sha"])]
        for entry in plan
    ]
    resolved = [found[0] for found in matches if len(found) == 1]
    problems = {
        "unknown": [e["sha"] for e, found in zip(plan, matches) if len(found) != 1],
        "duplicate": sorted({sha for sha in resolved if resolved.count(sha) > 1}),
        "omitted": [sha for sha in range_shas if sha not in resolved],
    }
    detail = "; ".join(f"{k}: {', '.join(v)}" for k, v in problems.items() if v)
    if detail:
        raise ValueError(f"plan must cover the range once - {detail}")


def subject_for(sha: str) -> str:
    """Return a commit's subject line."""
    return run_git(["log", "-1", "--format=%s", sha]).strip()


def build_sequence_script(plan: list[dict[str, str]], script_path: Path) -> None:
    """Write a GIT_SEQUENCE_EDITOR script that emits the plan's todo list."""
    lines = [
        f"{entry['verb']} {entry['sha']} {subject_for(entry['sha'])}" for entry in plan
    ]
    todo = "\n".join(lines) + "\n"
    script_path.write_text(
        "#!/bin/bash\ncat > \"$1\" <<'RESCRIPT_TIDY_EOF'\n"
        + todo
        + "RESCRIPT_TIDY_EOF\n"
    )
    script_path.chmod(0o755)


def editor_messages(plan: list[dict[str, str]]) -> list[str | None]:
    """Return each editor call's message override, None for the default."""
    slots: list[str | None] = []
    group_slot: int | None = None
    for entry in plan:
        verb, message = entry["verb"], entry.get("message")
        if verb == "squash":
            if group_slot is None:
                group_slot = len(slots)
                slots.append(None)
            slots[group_slot] = message or slots[group_slot]
        elif verb in ("pick", "reword"):
            group_slot = None
            if verb == "reword":
                slots.append(message)
    return slots


def build_message_script(plan: list[dict[str, str]], script_path: Path) -> None:
    """Write a GIT_EDITOR script that applies the message overrides."""
    slots = editor_messages(plan)
    if not any(slots):
        script_path.write_text("#!/bin/bash\ntrue\n")
        script_path.chmod(0o755)
        return

    queue_dir = script_path.with_suffix(".queue.d")
    queue_dir.mkdir(exist_ok=True)
    for index, message in enumerate(slots, start=1):
        if message:
            (queue_dir / f"{index}.txt").write_text(message)

    count_file = script_path.with_suffix(".count")
    script = f"""#!/bin/bash
FILE="$1"
QUEUE_DIR="{queue_dir}"
COUNT_FILE="{count_file}"
COUNT=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
INDEX=$((COUNT + 1))
MESSAGE_FILE="$QUEUE_DIR/$INDEX.txt"
[ -f "$MESSAGE_FILE" ] && cp "$MESSAGE_FILE" "$FILE"
echo "$INDEX" > "$COUNT_FILE"
"""
    script_path.write_text(script)
    script_path.chmod(0o755)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Execute a scripted interactive rebase from a declarative JSON plan"
    )
    parser.add_argument("plan", type=Path, help="Path to the JSON plan file")
    parser.add_argument(
        "base",
        nargs="?",
        default=None,
        help="Base ref (default: @{u}, else --root)",
    )
    parser.add_argument(
        "--root", action="store_true", help="Rewrite from the first commit"
    )
    return parser


def main() -> None:
    """Parse args, build the editor scripts, and run the rebase."""
    parser = build_parser()
    args = parser.parse_args()
    if args.root and args.base:
        parser.error("base and --root are exclusive")
    plan = load_plan(args.plan)
    base = "--root" if args.root else resolve_base(args.base)
    validate_coverage(plan, base)

    with tempfile.TemporaryDirectory() as tmpdir:
        seq_script = Path(tmpdir) / "sequence_editor.sh"
        msg_script = Path(tmpdir) / "message_editor.sh"
        build_sequence_script(plan, seq_script)
        build_message_script(plan, msg_script)

        env = {
            "GIT_SEQUENCE_EDITOR": str(seq_script),
            "GIT_EDITOR": str(msg_script),
        }
        result = subprocess.run(
            ["git", "rebase", "-i", base],
            env={**__import__("os").environ, **env},
            check=False,
        )
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
