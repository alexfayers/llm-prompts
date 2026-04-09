"""CLI entry point for llm-prompts."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Run the llm-prompts CLI."""
    parser = argparse.ArgumentParser(prog="llm-prompts", description="Manage LLM prompt rules, workflows, and skills.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("install", help="Install rules, workflows, and skills for all agents.")

    args = parser.parse_args()

    if args.command == "install":
        from .install import main as install_main

        install_main()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
