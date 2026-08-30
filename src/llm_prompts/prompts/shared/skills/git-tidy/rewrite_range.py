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
    python3 rewrite_range.py <plan.json> [<base-ref>]

`base-ref` defaults to the branch's upstream (`@{u}`). Run inspect_range.py
first and get explicit user confirmation of the plan before invoking this.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

VALID_VERBS = {"pick", "drop", "squash", "fixup", "reword"}


def run_git(args: list[str]) -> str:
    """Run a git command and return its stdout, raising on failure."""
    completed = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    )
    return completed.stdout


def resolve_base(explicit_base: str | None) -> str:
    """Resolve the base ref, falling back to the branch's upstream."""
    if explicit_base:
        return explicit_base
    return run_git(["rev-parse", "--abbrev-ref", "@{u}"]).strip()


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


def subject_for(sha: str) -> str:
    """Return a commit's subject line."""
    return run_git(["log", "-1", "--format=%s", sha]).strip()


def build_sequence_script(plan: list[dict[str, str]], script_path: Path) -> None:
    """Write a GIT_SEQUENCE_EDITOR script that emits the plan's todo list."""
    lines = [f"{entry['verb']} {entry['sha']} {subject_for(entry['sha'])}" for entry in plan]
    todo = "\n".join(lines) + "\n"
    script_path.write_text(
        "#!/bin/bash\ncat > \"$1\" <<'RESCRIPT_TIDY_EOF'\n" + todo + "RESCRIPT_TIDY_EOF\n"
    )
    script_path.chmod(0o755)


def build_message_script(plan: list[dict[str, str]], script_path: Path) -> None:
    """Write a GIT_EDITOR script that applies message overrides in order.

    Each message is written to its own numbered file (rather than one
    newline-joined queue read back line-by-line) so multi-line messages
    survive intact.
    """
    messages = [entry["message"] for entry in plan if entry["verb"] in ("squash", "reword") and entry.get("message")]
    if not messages:
        script_path.write_text("#!/bin/bash\ntrue\n")
        script_path.chmod(0o755)
        return

    queue_dir = script_path.with_suffix(".queue.d")
    queue_dir.mkdir(exist_ok=True)
    for index, message in enumerate(messages, start=1):
        (queue_dir / f"{index}.txt").write_text(message)

    count_file = script_path.with_suffix(".count")
    script = f"""#!/bin/bash
FILE="$1"
QUEUE_DIR="{queue_dir}"
COUNT_FILE="{count_file}"
COUNT=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
INDEX=$((COUNT + 1))
MESSAGE_FILE="$QUEUE_DIR/$INDEX.txt"
if [ -f "$MESSAGE_FILE" ]; then
  cp "$MESSAGE_FILE" "$FILE"
  echo $((COUNT + 1)) > "$COUNT_FILE"
fi
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
        "base", nargs="?", default=None, help="Base ref (default: @{u})"
    )
    return parser


def main() -> None:
    """Parse args, build the editor scripts, and run the rebase."""
    args = build_parser().parse_args()
    plan = load_plan(args.plan)
    base = resolve_base(args.base)

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
