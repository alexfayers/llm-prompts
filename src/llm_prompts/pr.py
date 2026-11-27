"""`llm-prompts pr`: take a pull request through size, main sync and ready."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from . import size_guard, telemetry
from .benchmark.agents import AGENTS
from .benchmark.agents.adapter import ModelNotSet
from .benchmark.scenarios.checks.judge import JudgeMissing, judge_harness, require_judge
from .benchmark.types import Agent
from .contribute import checkouts, first_stderr_line, run_ready, run_update
from .install import prompts_dir
from .network import run_with_retries
from .render_template import render_template


def _gh(repo: Path, *args: str) -> str:
    """Run a ``gh`` command in ``repo`` and return its stdout."""
    return run_with_retries(
        ["gh", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


MAX_FIX_ROUNDS = 5
AGENT_TIMEOUT_S = 1800
CLEAN_VERDICT = re.compile(
    r"\A\s*OUTCOME[^\n]*\nCLEAN[ \t\r]*(?:\n[ \t]*DEFERRED:[^\n]*)*\s*\Z"
)
NUMBERED_FINDING = re.compile(r"^\s*\d+[.)]", re.MULTILINE)
DEFERRED_LINE = re.compile(r"^[ \t]*DEFERRED:(.*)$", re.MULTILINE)
FINDING_LOCATION = re.compile(r"\S+:\d+")
VERDICT_FORMAT = (
    "Start the reply with a line `OUTCOME review`. Then, on the next line, write exactly "
    "`CLEAN` when there are no findings, with no numbered finding anywhere in the reply. "
    "Otherwise write the numbered findings."
)
REVIEW_LOOP = Path("shared/skills/pr-review/review-loop.md")
REVIEW_INSTRUCTIONS = Path(".github/instructions/review.instructions.md")
BRIEF_TARGET = "claude-code"
FIXER_TOOLS: dict[Agent, list[str]] = {
    "pi": ["--tools", "read,edit,write,grep,find,ls"],
    "claude": [
        "--tools",
        "Read,Edit,Write,Grep,Glob",
        "--permission-mode",
        "acceptEdits",
    ],
}
REVIEW_TASK = "Review this PR. Report only medium and high findings."
FIX_TASK = (
    "Fix these review findings in the working tree. Do not commit or push. "
    "Push back on a finding below the bar, with the reason, instead of changing code."
)


class AgentFailed(RuntimeError):
    """The review or fix agent exited with an error."""


class StaleCheckout(RuntimeError):
    """The worktree's HEAD is not the head of the PR on GitHub."""


class DirtyWorktree(RuntimeError):
    """The worktree has uncommitted changes the fixer could not be told apart from."""


def _brief(checkout: Path) -> str:
    """Return the review-loop prompt, followed by the repo's review instructions where it has them."""
    root = prompts_dir("llm_prompts")
    loop = render_template(
        str(root / REVIEW_LOOP), str(root / BRIEF_TARGET / "vars.json"), BRIEF_TARGET
    )
    instructions = checkout / REVIEW_INSTRUCTIONS
    return f"{loop}\n\n{VERDICT_FORMAT}" + (
        f"\n\n{instructions.read_text(encoding='utf-8')}"
        if instructions.is_file()
        else ""
    )


def _is_clean(reply: str) -> bool:
    """Return whether ``reply`` starts with an OUTCOME line followed by a CLEAN line and any DEFERRED lines, and no numbered finding."""
    return bool(CLEAN_VERDICT.search(reply)) and not NUMBERED_FINDING.search(reply)


def _deferred_count(reply: str) -> int:
    """Return the findings on ``reply``'s DEFERRED lines: one per ``file:line``, or one for a line without any."""
    return sum(
        max(1, len(FINDING_LOCATION.findall(items)))
        for items in DEFERRED_LINE.findall(reply)
        if items.strip()
    )


def _ask(
    harness: Agent, system: str, prompt: str, cwd: Path, model: str, tools: list[str]
) -> str:
    """Run the agent with ``system`` and ``prompt`` in ``cwd`` and return its final reply."""
    agent = AGENTS[harness]
    done = subprocess.run(
        [*agent.judge_argv(system), "--model", model, *tools],
        input=prompt,
        env=agent.judge_env(model, AGENT_TIMEOUT_S),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=AGENT_TIMEOUT_S,
    )
    reply = agent.parse(((0.0, line) for line in done.stdout.splitlines()), 0.0)
    if done.returncode or reply.error:
        raise AgentFailed(
            f"{harness} failed: {reply.error or done.stderr.strip()[:500]}"
        )
    return reply.final_text.strip()


def _git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        env={**os.environ, "GIT_SEQUENCE_EDITOR": "true"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _pr_head(path: Path, number: int) -> str:
    """Return the head commit of PR ``number`` on GitHub."""
    view = json.loads(_gh(path, "pr", "view", str(number), "--json", "headRefOid"))
    return str(view["headRefOid"])


def _require_pr_head(path: Path, number: int) -> str:
    """Return the head commit of PR ``number``, raising StaleCheckout unless ``path``'s HEAD is that commit."""
    remote = _pr_head(path, number)
    local = _git(path, "rev-parse", "HEAD").strip()
    if local != remote:
        raise StaleCheckout(
            f"#{number}: {path} is at {local[:12]}, not the PR head {remote[:12]}. Pull or push first."
        )
    return remote


def _commit_fixes(path: Path, base: str) -> bool:
    """Fold the working tree's changes into the branch's tip commit, returning whether there were any."""
    if not _git(path, "status", "--porcelain").strip():
        return False
    _git(path, "add", "-A")
    _git(path, "commit", "--fixup=HEAD")
    _git(
        path,
        "rebase",
        "-i",
        "--autosquash",
        _git(path, "merge-base", "HEAD", base).strip(),
    )
    return True


def _push(path: Path, branch: str) -> None:
    # shortcut: pushes to origin, so a PR from a fork is not supported. Use the remote of the PR's head when needed.
    _git(path, "push", "--force-with-lease", "origin", f"HEAD:{branch}")


def review_and_fix(
    path: Path,
    number: int,
    branch: str,
    base: str,
    after_fix: Callable[[], bool],
) -> bool:
    """Review the branch in ``path``'s clean worktree, fixing it locally until the review is CLEAN or ``MAX_FIX_ROUNDS`` fixes are spent, and push the fixes only once ``after_fix`` passed and the review is CLEAN.

    Returns:
        Whether the review ended CLEAN.
    """
    if _git(path, "status", "--porcelain").strip():
        raise DirtyWorktree(
            f"{path} has uncommitted changes. Commit or stash them first."
        )
    _require_pr_head(path, number)
    harness = judge_harness("auto")
    agent = AGENTS[harness]
    brief = _brief(path)
    text = json.loads(_gh(path, "pr", "view", str(number), "--json", "title,body"))
    context = f"{text['title']}\n\n{text['body']}"
    findings = ""
    rounds = 0
    clean = False
    for round_number in range(MAX_FIX_ROUNDS + 1):
        diff = _git(path, "diff", f"{base}...HEAD")
        earlier = f"\n\nEarlier findings:\n{findings}" if findings else ""
        findings = _ask(
            harness,
            brief,
            f"{REVIEW_TASK}\n\nPR #{number}: {context}{earlier}\n\nDiff:\n{diff}",
            path,
            agent.judge_model,
            [],
        )
        print(f"review round {round_number}:\n{findings}")
        clean = _is_clean(findings)
        if clean or round_number == MAX_FIX_ROUNDS:
            break
        _ask(
            harness,
            brief,
            f"{FIX_TASK}\n\nPR #{number}: {context}\n\nFindings:\n{findings}",
            path,
            agent.judge_model,
            FIXER_TOOLS[harness],
        )
        if not _commit_fixes(path, base):
            print("the fixer changed nothing")
            break
        rounds += 1
        if not after_fix():
            break
    if clean and rounds:
        _push(path, branch)
    elif rounds:
        print("the fixes are committed locally and not pushed")
    telemetry.send_pr_review(
        rounds=rounds, clean=clean, deferred=_deferred_count(findings)
    )
    return clean


def _size_passes(prompts: Path) -> bool:
    """Print the size report for ``prompts`` and return whether it passed."""
    result = size_guard.check([prompts])
    print(result.report)
    return result.passed


def run_pr(repo: Path, prefix: str, number: int) -> int:
    """Check the size of PR ``number``'s prompts, review and fix it, rebase it onto main and mark it ready, stopping at the first failing step."""
    try:
        view = json.loads(
            _gh(
                repo,
                "pr",
                "view",
                str(number),
                "--json",
                "state,headRefName,baseRefName",
            )
        )
        if view["state"] != "OPEN":
            print(f"#{number} is {view['state'].lower()}")
            return 1
        checkout = next(
            (c for c in checkouts(repo) if c.branch == view["headRefName"]), None
        )
        if checkout is None:
            print(
                f"#{number}: {view['headRefName']} is not checked out in a worktree of {repo}"
            )
            return 1
        prompts = checkout.path / prefix
        require_judge("auto")
        if not _size_passes(prompts):
            return 1
        if not review_and_fix(
            checkout.path,
            number,
            view["headRefName"],
            f"origin/{view['baseRefName']}",
            lambda: _size_passes(prompts),
        ):
            print(f"#{number}: the review is not CLEAN")
            return 1
        reviewed = _require_pr_head(checkout.path, number)
        if run_update(repo, True, (number,)):
            return 1
        if _pr_head(checkout.path, number) != reviewed:
            print(
                f"#{number}: the rebase onto main changed the PR head. Review it again before marking it ready."
            )
            return 1
    except subprocess.CalledProcessError as error:
        print(f"command failed: {first_stderr_line(error)}", file=sys.stderr)
        return 1
    except (
        JudgeMissing,
        ModelNotSet,
        AgentFailed,
        DirtyWorktree,
        StaleCheckout,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"#{number}: {error}")
        return 1
    return run_ready(repo, number)
