"""Drop low-severity pr-review findings."""

import argparse
import json
import subprocess
import sys
from typing import Any

KEEP_MAX = 3
SCALE = "Severity 1-5: 1 breaks behaviour or security, 2 bug or rule violation, 3 should fix, 4 minor, 5 nitpick."


def filter_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [f for f in findings if f["severity"] <= KEEP_MAX]
    return sorted(kept, key=lambda f: f["severity"])


def parse_findings(text: str) -> list[dict[str, Any]]:
    findings = json.loads(text)
    if not isinstance(findings, list):
        raise TypeError("input must be a JSON array")
    for finding in findings:
        severity = finding.get("severity") if isinstance(finding, dict) else None
        if type(severity) is not int or not 1 <= severity <= 5:
            raise ValueError(f"bad finding {finding!r}")
    return findings


def run(*command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), capture_output=True, text=True, check=check)


def git(*args: str) -> str:
    return run("git", *args).stdout


def default_branch() -> str:
    return git("symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()


def pr_base() -> str:
    command = ["gh", "pr", "view", "--json", "baseRefName", "--jq", ".baseRefName"]
    try:
        pr = run(*command, check=False)
    except FileNotFoundError:
        pr = None
    if pr and pr.returncode == 0:
        return f"origin/{pr.stdout.strip()}"
    return default_branch()


def scope() -> str:
    base = pr_base()
    sections = {"Uncommitted changes": git("diff", "HEAD")}
    if run("git", "rev-parse", "--abbrev-ref", "@{u}", check=False).returncode == 0:
        sections["Unpushed commits"] = git("diff", "@{u}...HEAD")
    for branch in dict.fromkeys([base, default_branch()]):
        sections[f"Diff against {branch}"] = git("diff", f"{branch}...HEAD")
    sections["Untracked files"] = git(
        "ls-files", "--others", "--exclude-standard", "--", ":/"
    )
    return "".join(f"## {title}\n{body}\n" for title, body in sections.items())


def main() -> int:
    parser = argparse.ArgumentParser(description=SCALE)
    parser.add_argument(
        "--scope",
        action="store_true",
        help="print the diffs and untracked paths to review",
    )
    if parser.parse_args().scope:
        try:
            report = scope()
        except subprocess.CalledProcessError as error:
            command = " ".join(error.cmd)
            print(f"{command} failed: {error.stderr.strip()}", file=sys.stderr)
            return 1
        print(report, end="")
        return 0
    try:
        findings = parse_findings(sys.stdin.read())
    except (TypeError, ValueError) as error:
        print(f"{error}. {SCALE}", file=sys.stderr)
        return 1
    print(json.dumps(filter_findings(findings), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
