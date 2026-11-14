"""Drop low-severity pr-review findings."""

import argparse
import json
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


def main() -> int:
    argparse.ArgumentParser(description=SCALE).parse_args()
    try:
        findings = parse_findings(sys.stdin.read())
    except (TypeError, ValueError) as error:
        print(f"{error}. {SCALE}", file=sys.stderr)
        return 1
    print(json.dumps(filter_findings(findings), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
