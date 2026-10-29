"""Attach a benchmark run's report to a pull request body."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from llm_prompts import contribute, github_api, telemetry
from llm_prompts.benchmark.report.compare import Report, outcome_summary
from llm_prompts.benchmark.report.render import GATE_TEXT, render

HEADING = "## Benchmark"
_HEADING_LINE = re.compile(r"^(#+ )", re.MULTILINE)
_DEMOTION = "###"
_LEAK_PATTERNS = {
    "a path": r"(?<![\w.:/])/[\w.-]+/[\w./-]+|(?<!\w)~/",
    "a URL": r"\b(?:https?|ssh|git)://",
    "an email address": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "an IP address": r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
    "an ARN": r"\barn:",
}
_PR_URL = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)/?$")
FILE_NAME = "pr.md"
_TRAILING_DEPENDS = r"(?:^Depends on [^\n]*\n?)+\Z"
_SECTION = re.compile(
    rf"^{HEADING}\n.*?(?=^## |{_TRAILING_DEPENDS}|\Z)", re.MULTILINE | re.DOTALL
)
_INSERT_BEFORE = re.compile(
    rf"^## (?:Dependencies|Issues)$|{_TRAILING_DEPENDS}", re.MULTILINE
)


def with_section(body: str, section: str) -> str:
    """Return ``body`` with its Benchmark section replaced by ``section``, or inserted before Dependencies, Issues and trailing Depends on lines."""
    block = section.rstrip() + "\n\n"
    if found := _SECTION.search(body):
        return body[: found.start()] + block + body[found.end() :].lstrip("\n")
    if found := _INSERT_BEFORE.search(body):
        return body[: found.start()].rstrip() + "\n\n" + block + body[found.start() :]
    return body.rstrip() + "\n\n" + block.rstrip() + "\n"


def section(report: Report) -> str:
    """Return the PR body section for ``report``: a short summary with the full public report folded below."""
    overall, *prompt_values = outcome_summary(report).splitlines()
    gate = GATE_TEXT.get(report.verdict, report.verdict)
    bullets = [
        f"Compared {report.a} with {report.b} at level {report.level} for {', '.join(report.agents)}, and the gate result is {gate}.",
        overall,
        *([" ".join(prompt_values)] if prompt_values else []),
    ]
    full = _HEADING_LINE.sub(rf"{_DEMOTION}\1", render(report, public=True)).rstrip()
    return "\n".join(
        [
            HEADING,
            "",
            *(f"- {bullet}" for bullet in bullets),
            "",
            "<details><summary>Full report</summary>",
            "",
            full,
            "",
            "</details>",
            "",
        ]
    )


def leaks(text: str) -> list[str]:
    """Return the kinds of local or internal-looking value found in ``text``."""
    found = [
        kind for kind, pattern in _LEAK_PATTERNS.items() if re.search(pattern, text)
    ]
    if any(
        re.search(rf"(?<!\w){re.escape(own)}(?!\w)", text)
        for own in telemetry.own_identities()
    ):
        found.append("this machine's own name or path")
    return found


def _number(target: str, repo: Path) -> int:
    """Return the PR number of ``target``, a number or a URL of the pull request's own repository."""
    if target.isdigit():
        return int(target)
    match = _PR_URL.match(target)
    if match is None:
        raise ValueError(f"--pr must be a PR number or a github.com PR URL: {target}")
    if (match[1], match[2]) != github_api.base_repo(repo):
        raise ValueError(f"{target} is not a pull request of the {repo} repository")
    return int(match[3])


def attach(target: str, run_dir: Path, repo: Path, apply: bool) -> int:
    """Write the run's Benchmark section into PR ``target`` when ``apply``, else print it, and return the exit code."""
    try:
        number = _number(target, repo)
        text = (run_dir / FILE_NAME).read_text()
    except FileNotFoundError:
        print(
            f"{run_dir.name} has no {FILE_NAME}. Run the benchmark again.",
            file=sys.stderr,
        )
        return 2
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if found := leaks(text):
        print(f"Not attaching, the section has {', '.join(found)}.", file=sys.stderr)
        return 2
    if not apply:
        print(f"PR {number} would get this section. Add --apply to write it.\n\n{text}")
        return 0
    try:
        title, body = contribute.pr_title_body(repo, number)
        contribute.edit_pr(repo, number, title, with_section(body, text))
    except subprocess.CalledProcessError as error:
        print(contribute.first_stderr_line(error), file=sys.stderr)
        return 2
    print(f"Attached the benchmark section to PR {number}")
    return 0
