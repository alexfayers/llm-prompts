#!/usr/bin/env python3
"""A fake ``gh`` for the contribute worktree tests: state lives in the JSON file named by GH_FAKE."""

import json
import os
import re
import subprocess
import sys
from typing import Any

STATE_PATH = os.environ["GH_FAKE"]
ORIGIN = os.environ.get("GH_FAKE_ORIGIN", "")


def load() -> dict[str, Any]:
    with open(STATE_PATH, encoding="utf-8") as handle:
        state: dict[str, Any] = json.load(handle)
    return state


def save(state: dict[str, Any]) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def option(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def remote_tip(branch: str) -> str:
    done = subprocess.run(
        ["git", "--git-dir", ORIGIN, "rev-parse", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip()


def view(number: str, pr: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": int(number),
        "state": pr["state"],
        "isDraft": pr["isDraft"],
        "title": pr["title"],
        "body": pr["body"],
        "url": f"https://github.com/o/r/pull/{number}",
        "headRefName": pr["headRefName"],
        "headRefOid": pr.get("headRefOid") or remote_tip(pr["headRefName"]),
    }


def main(argv: list[str]) -> int:
    state = load()
    state["calls"].append(argv)
    if argv[:2] == ["api", "graphql"]:
        query = next(arg for arg in argv if arg.startswith("query="))
        aliases = {}
        for number in re.findall(r"pr(\d+): pullRequest", query):
            pr = state["prs"].get(number)
            aliases[f"pr{number}"] = view(number, pr) if pr else None
        print(json.dumps({"data": {"repository": aliases}}))
    elif argv[:2] == ["pr", "create"]:
        head = option(argv, "--head").split(":")[-1]
        if any(
            pr["headRefName"] == head and pr["state"] == "OPEN"
            for pr in state["prs"].values()
        ):
            save(state)
            print(f"a pull request for branch {head} already exists", file=sys.stderr)
            return 1
        number = str(state["next"])
        state["next"] += 1
        state["prs"][number] = {
            "state": "OPEN",
            "isDraft": "--draft" in argv,
            "title": option(argv, "--title"),
            "body": option(argv, "--body"),
            "headRefName": head,
        }
        print(f"https://github.com/o/r/pull/{number}")
    elif argv[:2] == ["pr", "edit"]:
        pr = state["prs"][argv[2]]
        pr["title"] = option(argv, "--title")
        pr["body"] = option(argv, "--body")
    elif argv[:2] == ["pr", "view"]:
        number = next(
            n for n, pr in state["prs"].items() if pr["headRefName"] == argv[2]
        )
        print(json.dumps({"number": int(number)}))
    elif argv[:2] == ["pr", "list"]:
        print(
            json.dumps(
                [view(n, pr) for n, pr in state["prs"].items() if pr["state"] == "OPEN"]
            )
        )
    elif argv[:2] == ["repo", "view"]:
        print(json.dumps({"viewerPermission": "WRITE"}))
    save(state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
