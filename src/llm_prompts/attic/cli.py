"""The ``llm-prompts attic`` subcommand."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from ..install import _pi_agent_dir
from ..render_template import parse_frontmatter
from .manifest import AtticError, build_manifest, read_ledger

LEDGER_NAME = "usage-ledger.jsonl"
MANIFEST_NAME = "attic.json"


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``attic build``."""
    attic = subparsers.add_parser(
        "attic", help="List the skills and tools that the usage ledger shows as unused."
    ).add_subparsers(dest="attic_command", required=True)
    build = attic.add_parser("build", help="Write the attic manifest.")
    add = build.add_argument
    add(
        "--ledger",
        type=Path,
        help=f"Usage ledger (default: {LEDGER_NAME} in pi's agent directory).",
    )
    add(
        "--out",
        type=Path,
        help=f"Manifest file (default: {MANIFEST_NAME} next to the ledger).",
    )
    add(
        "--threshold",
        type=int,
        default=1,
        help="List items used fewer times than this (default: 1).",
    )
    add(
        "--min-days",
        type=float,
        default=7,
        help="Least days the ledger must cover (default: 7).",
    )
    add(
        "--tool",
        action="append",
        default=[],
        metavar="NAME",
        help="An installed tool to consider; only these tools are candidates. Repeatable.",
    )
    add("--dry-run", action="store_true", help="Print the manifest without writing it.")


def _skill_stubs() -> dict[str, str]:
    return {
        skill.parent.name: parse_frontmatter(skill.read_text("utf-8"))[1].get(
            "description", ""
        )
        for skill in sorted((_pi_agent_dir() / "skills").glob("*/SKILL.md"))
    }


def run(args: argparse.Namespace) -> int:
    """Build the manifest, returning the exit code."""
    ledger = args.ledger or _pi_agent_dir() / LEDGER_NAME
    if not ledger.is_file():
        print(f"No ledger at {ledger}.", file=sys.stderr)
        return 1
    rows, skipped = read_ledger(ledger)
    if skipped:
        print(f"Skipped {skipped} unreadable ledger lines.", file=sys.stderr)
    try:
        manifest = build_manifest(
            rows,
            _skill_stubs(),
            dict.fromkeys(args.tool, ""),
            now=datetime.now(UTC),
            min_days=args.min_days,
            threshold=args.threshold,
        )
    except AtticError as error:
        print(error, file=sys.stderr)
        return 1
    text = json.dumps(manifest.to_json(), indent=2)
    if args.dry_run:
        print(text)
        return 0
    (args.out or ledger.with_name(MANIFEST_NAME)).write_text(f"{text}\n", "utf-8")
    return 0
