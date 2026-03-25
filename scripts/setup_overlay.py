#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gitpython>=3.1.46",
# ]
# ///
"""Clone an overlay repo into the llm-prompts directory and configure it."""

import argparse
import json
from pathlib import Path
import sys

import git


def _log(message: str) -> None:
    """Print a status message to stderr.

    Args:
        message: Message to print.
    """
    sys.stderr.write(message + "\n")


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the setup_overlay script.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        description="Clone an overlay repo into llm-prompts and configure install.py to use it.",
    )
    parser.add_argument("repo_url", help="Git URL or local path of the overlay repository to clone.")
    parser.add_argument("overlay_name", help="Name for the overlay directory (e.g. 'amazon').")
    return parser


def main() -> None:
    """Clone the overlay repo, write overlay.json, and add the dir to .git/info/exclude."""
    args = _build_parser().parse_args()
    root_dir = Path(__file__).parent.parent

    overlay_dir = root_dir / args.overlay_name
    overlay_json = root_dir / "overlay.json"
    git_exclude = root_dir / ".git" / "info" / "exclude"

    if overlay_dir.exists():
        _log(f"[>] Overlay directory '{args.overlay_name}' already exists. Skipping clone.")
    else:
        _log(f"[>] Cloning {args.repo_url} into {overlay_dir}...")
        git.Repo.clone_from(args.repo_url, overlay_dir)

    _log("[>] Writing overlay.json...")
    if overlay_json.exists():
        data = json.loads(overlay_json.read_text(encoding="utf-8"))
        overlays: list[str] = data.get("overlays") or ([data["overlay"]] if data.get("overlay") else [])
    else:
        overlays = []
    if args.overlay_name not in overlays:
        overlays.append(args.overlay_name)
    overlay_json.write_text(json.dumps({"overlays": overlays}) + "\n", encoding="utf-8")

    exclude_entry = f"{args.overlay_name}/"
    exclude_text = git_exclude.read_text(encoding="utf-8") if git_exclude.exists() else ""
    if exclude_entry not in exclude_text.splitlines():
        _log(f"[>] Adding '{exclude_entry}' to .git/info/exclude...")
        git_exclude.parent.mkdir(parents=True, exist_ok=True)
        with git_exclude.open("a", encoding="utf-8") as f:
            f.write(f"\n{exclude_entry}\n")
    else:
        _log(f"[>] '{exclude_entry}' already in .git/info/exclude. Skipping.")

    _log(f"[+] Overlay '{args.overlay_name}' configured. Run install.py to apply.")


if __name__ == "__main__":
    main()
