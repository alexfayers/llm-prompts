"""CLI entry point for llm-prompts."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, Self
from urllib.parse import urlparse

from . import github_api, telemetry
from .console import log
from .exit_reason import ExitReason, Reason
from .home import set_root
from .install import AGENT_CLASSES, REMOVED_AGENTS, prompts_dir, user_binary
from .network import run_with_retries, stderr_text
from .setup import (
    _RELEASE_TAG,
    _UPDATE_INSTRUCTION,
    GIT_TIMEOUT,
    SHIPPED_PATHS,
    TEST_TIMEOUT,
    _commit_subjects_between,
    _extract_git_url,
    _format_update_message,
    _latest_release_tag,
    _remote_changes,
    _remote_head,
    _uv_tools_dir,
    release_notes,
    release_version,
)

if TYPE_CHECKING:
    from .contribute import SyncOptions
    from .manifest import AgentManifest
    from .size_guard import Artifact
    from .worktrees import WorktreeEntry

_AGENTS = tuple(AGENT_CLASSES)
_MEMORY_TOOL = "mcp-memory"
_OWN_TOOL = "llm-prompts"
_MEMORY_FLUSH_TIMEOUT_SECONDS = 10
_ARGPARSE_USAGE_ERROR = 2
_RUN_SETUP_TRACKED_TOOLS = (_MEMORY_TOOL, "cline-hooks")
_UPDATE_RESUME_ENV = "LLM_PROMPTS_UPDATE_RESUME"
_INSTALLING_COMMANDS = frozenset({"install", "setup", "update"})
_URL_CREDENTIALS = re.compile(r"(://)[^/@\s]+@")
_FETCHED_REPOS: set[Path] = set()


def _get_root_dir() -> Path:
    """Return the llm-prompts package data directory."""
    return prompts_dir("llm_prompts")


def _collect_sources(agent: str) -> dict[str, Path]:
    """Collect source files for an agent, respecting overlay priority.

    Returns a dict mapping destination filename to source path. Overlays
    take priority over shared sources, and agent-specific sources are
    added if they don't exist in shared.
    """
    from .install import _agent_source_dirs, _discover_overlay_paths, content_subdirs

    root = _get_root_dir()

    with contextlib.redirect_stderr(io.StringIO()):
        overlay_dirs = _discover_overlay_paths()

    sources: dict[str, Path] = {}

    for subdir in content_subdirs(agent):
        # Overlay sources (highest priority)
        for overlay_dir in overlay_dirs:
            overlay_src = overlay_dir / "shared" / subdir
            if overlay_src.is_dir():
                for f in sorted(overlay_src.glob("*.md")):
                    sources.setdefault(f"{subdir}/{f.name}", f)

        # Shared sources
        shared_src = root / "shared" / subdir
        if shared_src.is_dir():
            for f in sorted(shared_src.glob("*.md")):
                sources.setdefault(f"{subdir}/{f.name}", f)

        # Agent-specific sources (only if not in shared)
        agent_src = root / agent / subdir
        if agent_src.is_dir():
            for f in sorted(agent_src.glob("*.md")):
                sources.setdefault(f"{subdir}/{f.name}", f)

        # Overlay agent-specific sources
        for overlay_dir in overlay_dirs:
            overlay_agent_src = overlay_dir / agent / subdir
            if overlay_agent_src.is_dir():
                for f in sorted(overlay_agent_src.glob("*.md")):
                    sources.setdefault(f"{subdir}/{f.name}", f)

    # Skills
    for skill_src in [d / "shared" / "skills" for d in overlay_dirs] + [
        root / "shared" / "skills"
    ]:
        if skill_src.is_dir():
            for skill_dir in sorted(skill_src.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if skill_file.is_file():
                    sources.setdefault(f"skills/{skill_dir.name}", skill_file)

    # Agents
    if agent in ("claude-code", "pi"):
        for agents_src in _agent_source_dirs(root, overlay_dirs, agent):
            if agents_src.is_dir():
                for f in sorted(agents_src.glob("*.md")):
                    sources.setdefault(f"agents/{f.name}", f)

    # Extensions and seed files (pi only); the last overlay wins, as when installed
    if agent == "pi":
        for prompts in [root, *overlay_dirs]:
            for ext in sorted((prompts / "pi" / "extensions").glob("*.ts")):
                sources[f"extensions/{ext.name}"] = ext
            seed_dir = prompts / "pi" / "seed"
            for seed in sorted(seed_dir.rglob("*")):
                if seed.is_file():
                    sources[f"seed/{seed.relative_to(seed_dir)}"] = seed

    return sources


def _print_sources(agent: str) -> None:
    """Print source file paths for an agent."""
    sources = _collect_sources(agent)
    if not sources:
        print(f"No sources found for agent '{agent}'.")
        return

    current_section = ""
    for key in sorted(sources):
        section = key.split("/")[0]
        if section != current_section:
            if current_section:
                print()
            print(f"{section}:")
            current_section = section
        print(f"  {sources[key]}")


def _size_guard_roots() -> list[Path]:
    """Return this package's own prompts dir plus every discovered overlay's.

    Used by the `check` subcommand, which measures the full checked union a
    real install would see - unlike the pytest suite, which is confined to
    this package's own root (see `size_guard`'s module docstring).
    """
    from .install import _discover_overlay_paths

    with contextlib.redirect_stderr(io.StringIO()):
        overlay_dirs = _discover_overlay_paths()
    return [_get_root_dir(), *overlay_dirs]


def _print_parked_state(artifacts: list[Artifact]) -> None:
    """Print one visibility line per metric with artifacts still over final.

    Args:
        artifacts: Every measured artifact from a `size_guard.check()` run.
    """
    from .size_guard import parked_state_lines

    for line in parked_state_lines(artifacts):
        print(line)


def _run_size_check() -> None:
    """Run the prompt-size guard against the full checked union and report."""
    from .size_guard import check as run_size_check

    result = run_size_check(_size_guard_roots())
    print(result.report)
    if not result.passed:
        sys.exit(1)
    _print_parked_state(result.artifacts)
    for line in result.stale:
        print(line)


def _run_extension_factory_check() -> None:
    """Report pi extensions lacking a default factory or summary header and exit 1 if any."""
    from .extension_factories import (
        find_missing_default_factory,
        find_missing_summary_header,
    )

    roots = _size_guard_roots()
    missing = find_missing_default_factory(roots)
    unsummarised = find_missing_summary_header(roots)
    for extension in missing:
        print(f"{extension}: no default factory function")
    for extension in unsummarised:
        print(f"{extension}: missing summary header")
    if missing or unsummarised:
        sys.exit(1)


def _reexec_update(
    changed_sources: set[str],
    size_baseline: dict[Path, str],
    run: telemetry.Run,
) -> None:
    """Restart `update` on the upgraded code, handing over the work done so far."""
    os.environ[_UPDATE_RESUME_ENV] = json.dumps(
        {
            "changed_sources": sorted(changed_sources),
            "size_baseline": {str(path): h for path, h in size_baseline.items()},
            "telemetry": run.hand_over(),
        }
    )
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvp(sys.argv[0], sys.argv)


def _get_installed_commit(package_name: str) -> str | None:
    """Get the installed commit hash from direct_url.json in a uv tool env."""
    installed = _get_installed_dist(package_name)
    return installed[1] if installed else None


def _get_installed_dist(package_name: str) -> tuple[Path, str] | None:
    """Find a tool's git-installed direct_url.json in a uv tool env.

    Returns:
        The direct_url.json path and its commit hash, or None if not found.
    """
    import json

    uv_tools = Path.home() / ".local" / "share" / "uv" / "tools"
    dist_name = package_name.replace("-", "_")

    search_dirs = [uv_tools / package_name, uv_tools / "llm-prompts"]
    for tools_dir in search_dirs:
        if not tools_dir.is_dir():
            continue
        for dist_info in tools_dir.rglob(f"{dist_name}-*.dist-info/direct_url.json"):
            try:
                data = json.loads(dist_info.read_text(encoding="utf-8"))
                vcs_info = data.get("vcs_info", {})
                commit_id: str | None = vcs_info.get("commit_id")
                if commit_id:
                    return dist_info, commit_id
            except (OSError, json.JSONDecodeError):
                continue
    return None


def _get_installed_version(package_name: str) -> tuple[str | None, str | None]:
    """Get a uv tool env's git-installed commit and its version as a stable vX.Y.Z tag."""
    installed = _get_installed_dist(package_name)
    if not installed:
        return None, None
    tag = "v" + installed[0].parent.name.removesuffix(".dist-info").rpartition("-")[2]
    return installed[1], tag if release_version(tag) else None


def _get_installed_revision(package_name: str) -> str | None:
    """Get the ref a uv tool env's git install was requested at, if any."""
    installed = _get_installed_dist(package_name)
    if not installed:
        return None
    vcs_info = json.loads(installed[0].read_text(encoding="utf-8")).get("vcs_info", {})
    revision: str | None = vcs_info.get("requested_revision")
    return revision


def _remote_source_messages(
    name: str, source: str, ref: str | None = None
) -> list[str]:
    """Return update-availability messages for a remote git source.

    Args:
        name: The tool name.
        source: The configured source.
        ref: A ref to follow instead of the latest release tag.

    Returns:
        Message lines describing available updates, or an empty list.
    """
    git_url = _extract_git_url(source)
    if not git_url:
        return []

    installed_commit = _get_installed_commit(name)
    if not installed_commit:
        return [f"[{name}] not installed (run `llm-prompts setup` first)"]

    release = None if ref else _latest_release_tag(git_url)
    remote_commit = release[1] if release else _remote_head(git_url, ref)
    if remote_commit is None or remote_commit == installed_commit:
        return []

    subjects, changelog = _remote_changes(
        git_url, installed_commit, remote_commit, read_changelog=bool(release)
    )
    if subjects == []:
        return []
    if release:
        revision = _get_installed_revision(name)
        installed = revision if revision and _RELEASE_TAG.fullmatch(revision) else None
        return _format_update_message(
            name,
            subjects,
            release=(installed or installed_commit[:8], release[0]),
            changelog=_changelog_url(git_url, release[0]),
            sections=release_notes(changelog, installed or "", release[0]),
        )
    return _format_update_message(
        name, subjects, installed_commit[:8], remote_commit[:8]
    )


def _source_identity(entry: dict[str, Any], kind: str = "tool") -> list[str]:
    """Return a tool or plugin entry's name, source URL digest, ref and kind."""
    source = str(entry.get("source", ""))
    return [
        str(entry.get("name", "")),
        hashlib.sha256(source.encode()).hexdigest(),
        str(entry.get("ref", "")),
        kind,
    ]


def _fingerprint_versions(fingerprint: str) -> dict[tuple[str, ...], str]:
    """Map each source identity in an installed-version fingerprint to its installed commit."""
    try:
        return {tuple(entry[:-1]): entry[-1] for entry in json.loads(fingerprint)}
    except (ValueError, TypeError):
        return {}


def _previous_source_messages(
    identity: list[str], fingerprint: str, messages: list[str]
) -> list[str]:
    """Return a remote source's messages from the previous check, or none once its installed version moved."""
    name = identity[0]
    versions = _fingerprint_versions(fingerprint)
    key = tuple(identity)
    if key not in versions or versions[key] != (_get_installed_commit(name) or ""):
        return []
    return [
        message
        for message in messages
        if message.startswith(f"[{name}] ")
        and getattr(message, "source", identity) == identity
    ]


class UpdateCheckFailure(str):
    """An update-check-failed message, with the identity of the source whose check failed."""

    source: list[str]

    def __new__(cls, message: str, source: list[str] | None = None) -> Self:
        failure = super().__new__(cls, message)
        failure.source = source or []
        return failure


def _previous_failures_or(
    identity: list[str],
    previous: tuple[str, list[str]] | None,
    check: Callable[[], list[str]],
) -> list[str]:
    """Return a source's failed checks from the previous check of the same source, or run the check when it had none."""
    failures: list[str] = [
        message
        for message in (previous or ("", []))[1]
        if isinstance(message, UpdateCheckFailure) and message.source == identity
    ]
    return failures or check()


def _update_check_or_failure(
    identity: list[str], check: Callable[[], list[str]]
) -> list[str]:
    """Run an update check, reporting a failed git call as a message.

    Returns:
        The check's messages, or a single update-check-failed message.
    """
    try:
        return check()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        reason = str(exc)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            reason += " " + " ".join(stderr_text(exc).strip().splitlines()[-2:])
        reason = _URL_CREDENTIALS.sub(r"\1", reason)
        return [
            UpdateCheckFailure(
                f"[{identity[0]}] update check failed: {reason}", identity
            )
        ]


def _waiting_conflict_messages(name: str, source: str) -> list[str]:
    """Return a message when local main waits on an unresolved conflict in its resolve worktree."""
    from .main_sync import resolve_worktree, run_git
    from .setup import _expand

    repo = _expand(source)
    if not (repo / ".git").is_dir() or not (work := resolve_worktree(repo)).exists():
        return []
    unmerged = run_git(work, "diff", "--name-only", "--diff-filter=U").stdout.split()
    if not unmerged:
        return []
    files = ", ".join(unmerged)
    return [f"[{name}] local main is waiting on a conflict in {work}: {files}"]


def _local_source_messages(
    name: str, source: str, ref: str = "", fetch: bool = True
) -> list[str]:
    """Return update-availability messages for a local-path git source.

    Args:
        name: The tool name.
        source: The configured source.
        ref: A remote branch to follow instead of the latest release tag.
        fetch: Whether to fetch before comparing against the remote refs.

    Returns:
        Message lines describing available updates, or an empty list.
    """
    from .main_sync import UPSTREAM, point_upstream, run_git, unreleased
    from .setup import _expand, release_version

    repo = _expand(source)
    if not (repo / ".git").is_dir():
        return []

    if fetch:
        run_with_retries(
            ["git", "-C", str(repo), "fetch", "--quiet", "--tags", "--force"],
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
        _FETCHED_REPOS.add(repo)
    if not point_upstream(repo, ref):
        return []
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", f"HEAD..{UPSTREAM}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=GIT_TIMEOUT,
    )
    if result.returncode != 0:
        return []

    count = int(result.stdout.strip())
    if count == 0:
        if not unreleased(repo):
            return []
        new = run_git(repo, "symbolic-ref", "--short", UPSTREAM).stdout.strip()
        return [f"[{name}] update available: move main back to release {new}"]

    subjects = _commit_subjects_between(repo, "HEAD", UPSTREAM, SHIPPED_PATHS)
    if subjects == []:
        return []
    new = run_git(repo, "symbolic-ref", "--short", UPSTREAM).stdout.strip()
    old = run_git(
        repo, "describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD"
    ).stdout.strip()
    if not (release_version(new) and release_version(old)):
        return _format_update_message(name, subjects)
    changelog = run_git(repo, "show", f"{UPSTREAM}:CHANGELOG.md").stdout
    return _format_update_message(
        name,
        subjects,
        release=(old, new),
        changelog=_changelog_url(github_api.base_remote_url(repo), new),
        sections=release_notes(changelog, old, new),
    )


def _prompts_prefix(repo: Path) -> str | None:
    """Return the repo-relative prompts-dir prefix, if exactly one exists.

    Args:
        repo: The local repo checkout path.

    Returns:
        The repo-relative prompts-dir prefix (e.g. "src/llm_prompts/prompts/"),
        trailing slash included, or None if there isn't exactly one match.
    """
    matches = sorted(repo.glob("src/*/prompts"))
    if len(matches) != 1:
        return None
    return f"{matches[0].relative_to(repo).as_posix()}/"


def _is_github_remote_url(url: str) -> bool:
    """Check whether a git remote URL's host is exactly github.com.

    Args:
        url: A single remote URL, either standard (`https://`/`ssh://`) or
            scp-like (`git@github.com:owner/repo.git`).

    Returns:
        True if the URL's host is github.com.
    """
    if "://" in url:
        return urlparse(url).hostname == "github.com"
    host = url.split("@", 1)[-1].split(":", 1)[0]
    return host == "github.com"


def _changelog_url(url: str, tag: str) -> str | None:
    """Return the GitHub page of a remote's CHANGELOG.md at ``tag``, or None for a non-GitHub remote."""
    match = github_api._REMOTE_REPO.search(url)
    if not (match and _is_github_remote_url(url)):
        return None
    return f"https://github.com/{match[1]}/{match[2]}/blob/{tag}/CHANGELOG.md"


def _has_github_remote(repo: Path) -> bool:
    """Check whether a local checkout is a git repo with a github.com remote.

    Args:
        repo: The local repo checkout path.

    Returns:
        True if `git remote -v` succeeds and lists a github.com remote.
    """
    result = subprocess.run(
        ["git", "-C", str(repo), "remote", "-v"],
        check=False,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )
    return any(
        _is_github_remote_url(line.split()[1])
        for line in result.stdout.splitlines()
        if len(line.split()) >= 2
    )


def _contribute_target(name: str) -> tuple[Path, str]:
    """Resolve the checkout path and repo-relative prompts prefix for a configured tool.

    Args:
        name: The tool name to look up in config, e.g. "llm-prompts".

    Returns:
        The local checkout path and the repo-relative prompts-dir prefix
        (e.g. "src/llm_prompts/prompts/"), trailing slash included.
    """
    from .setup import _expand, _is_local_path, _load_config

    for tool in _load_config():
        if str(tool.get("name", "")) == name:
            source = str(tool.get("source", ""))
            if not _is_local_path(source):
                print(
                    f"The {name} tool source is not a local path; "
                    "`contribute` requires a local checkout.",
                    file=sys.stderr,
                )
                raise ExitReason("tool_not_local")
            repo = _expand(source)
            prefix = _prompts_prefix(repo)
            if prefix is None:
                print(
                    f"Expected exactly one src/*/prompts directory in {repo}.",
                    file=sys.stderr,
                )
                raise ExitReason("no_prompts_dir")
            return repo, prefix
    print(f"No {name} tool entry found in config.", file=sys.stderr)
    raise ExitReason("tool_not_configured")


class _ContributeTarget(NamedTuple):
    """A resolved contribute target: a configured tool's local checkout."""

    name: str
    repo: Path
    prefix: str


def _contribute_targets() -> list[_ContributeTarget]:
    """Discover every locally-cloned GitHub tool source with a prompts directory.

    Returns:
        The matching targets, in config order.
    """
    from .setup import _expand, _is_local_path, _load_config

    targets: list[_ContributeTarget] = []
    for tool in _load_config():
        source = str(tool.get("source", ""))
        if not _is_local_path(source):
            continue
        repo = _expand(source)
        prefix = _prompts_prefix(repo)
        if prefix is None:
            continue
        if not _has_github_remote(repo):
            continue
        targets.append(_ContributeTarget(str(tool.get("name", "")), repo, prefix))
    if not targets:
        print(
            "No locally-cloned GitHub tool sources with a prompts directory "
            "found in config.",
            file=sys.stderr,
        )
        raise ExitReason("no_contribute_targets")
    return targets


class _PullOutcome(NamedTuple):
    """The result of pulling one tool source."""

    name: str
    changed: bool
    messages: list[str]
    failed: Reason | None = None


def _source_test_warnings(name: str, repo: Path, test: str) -> list[str]:
    """Run a source's test command and describe how it went wrong, if it did."""
    from .main_sync import PRE_SYNC_REF

    try:
        if not (argv := shlex.split(test)):
            raise ValueError("empty command")
        passed = (
            subprocess.run(
                argv,
                cwd=repo,
                capture_output=True,
                check=False,
                timeout=TEST_TIMEOUT,
            ).returncode
            == 0
        )
        problem = "failed on the synced main"
    except subprocess.TimeoutExpired:
        passed, problem = False, f"timed out after {TEST_TIMEOUT}s"
    except (OSError, ValueError):
        passed, problem = False, "could not be run"
    if passed:
        return []
    return [
        f"[{name}] warning: `{test}` {problem}; undo with: git reset --keep {PRE_SYNC_REF}"
    ]


def _pull_one_local_source(
    name: str, source: str, test: str = "", ref: str = ""
) -> _PullOutcome:
    """Pull a single local-path tool source, warning when its main then holds commits on no open PR."""
    from . import worktrees
    from .main_sync import UPSTREAM, unpublished
    from .setup import _expand

    outcome = _sync_local_source(name, source, test, ref)
    repo = _expand(source)
    if outcome.failed or not (repo / ".git").is_dir():
        return outcome
    if not (shas := unpublished(repo, UPSTREAM, worktrees.copied_identities(repo))):
        return outcome
    warning = (
        f"[{name}] warning: main holds {len(shas)} commit(s) on no open PR"
        f" ({', '.join(shas)}); drop them with:"
        f" cd {shlex.quote(str(repo))} && git rebase -i {UPSTREAM} main"
    )
    return outcome._replace(messages=[*outcome.messages, warning])


def _sync_local_source(
    name: str, source: str, test: str = "", ref: str = ""
) -> _PullOutcome:
    """Pull upstream changes for a single local-path tool source.

    Args:
        name: The source name, used in the messages.
        source: The configured source string.
        test: Optional command run in the source after local commits are rebased or replayed.
        ref: A remote branch to follow instead of the latest release tag.

    Returns:
        Whether the source moved, and message lines describing the pull outcome.
    """
    from . import worktrees
    from .main_sync import (
        GIT_TIMED_OUT,
        PRE_SYNC_REF,
        UPSTREAM,
        SyncResult,
        empty_merged_copies,
        point_upstream,
        rebuild_local,
        run_git,
        sync_diverged,
        unreleased,
    )
    from .setup import _expand, _is_local_path

    unchanged = _PullOutcome(name, False, [])
    if not _is_local_path(source):
        return unchanged
    repo = _expand(source)
    if not (repo / ".git").is_dir():
        return unchanged
    fetch = (
        subprocess.CompletedProcess([], 0, "", "")
        if repo in _FETCHED_REPOS
        else run_git(repo, "fetch", "--quiet", "--tags", "--force")
    )
    fetch_failed = fetch.returncode != 0
    fetch_error = f"[{name}] could not fetch: {fetch.stderr.strip()}"
    fetch_failure = _PullOutcome(
        name, False, [fetch_error], failed="source_fetch_failed"
    )
    if not point_upstream(repo, ref):
        return fetch_failure if fetch_failed else unchanged
    result = run_git(repo, "rev-list", "--count", f"HEAD..{UPSTREAM}")
    if result.returncode != 0:
        return fetch_failure if fetch_failed else unchanged
    count = int(result.stdout.strip())
    if not fetch_failed and (drops := unreleased(repo)):
        release = run_git(repo, "symbolic-ref", "--short", UPSTREAM).stdout.strip()
        synced = rebuild_local(repo, UPSTREAM, {}, drops, {}, [])
        if synced.mode == "stopped":
            return _PullOutcome(
                name, False, [f"[{name}] main not updated: {synced.detail}"]
            )
        if synced.mode == "failed":
            return _PullOutcome(
                name,
                False,
                [f"[{name}] could not move to release {release}", f"  {synced.detail}"],
                failed="source_release_failed",
            )
        moved = [
            f"[{name}] moved to release {release}; left {len(drops)} unreleased commit(s); undo with: git reset --keep {PRE_SYNC_REF}"
        ]
        if test:
            moved += _source_test_warnings(name, repo, test)
        return _PullOutcome(name, True, moved)
    if count == 0:
        if fetch_failed:
            return fetch_failure
        if not (
            empty := empty_merged_copies(
                repo, UPSTREAM, worktrees.copied_identities(repo)
            )
        ):
            return unchanged
        synced = rebuild_local(repo, UPSTREAM, {}, empty, {}, [])
        if synced.mode == "stopped":
            return _PullOutcome(
                name, False, [f"[{name}] main not updated: {synced.detail}"]
            )
        if synced.mode == "failed":
            return _PullOutcome(
                name,
                False,
                [f"[{name}] could not drop empty commits", f"  {synced.detail}"],
                failed="source_cleanup_failed",
            )
        dropped = f"[{name}] dropped {len(empty)} empty copies of merged commits; undo with: git reset --keep {PRE_SYNC_REF}"
        return _PullOutcome(name, True, [dropped])
    pull = run_git(repo, "merge", "--ff-only", "--quiet", UPSTREAM)
    if pull.returncode == 0:
        return _PullOutcome(name, True, [f"[{name}] pulled {count} new commit(s)"])
    if pull.returncode == GIT_TIMED_OUT:
        synced = SyncResult("failed", detail=pull.stderr.strip())
    else:
        synced = sync_diverged(repo, UPSTREAM)
    if synced.mode == "failed":
        return _PullOutcome(
            name,
            False,
            [
                f"[{name}] {count} new commit(s) available but sync failed",
                f"  {synced.detail}",
            ],
            failed="source_merge_failed",
        )
    if synced.mode == "reset":
        message = (
            f"[{name}] local commits already upstream; reset to {count} new commit(s)"
        )
    elif synced.mode == "rebased":
        message = f"[{name}] rebased local commits onto {count} new commit(s)"
    else:
        message = f"[{name}] dropped squash-merged commits"
        if synced.replayed:
            message += f"; replayed {synced.replayed} local commit(s)"
        message += f"; undo with: git reset --keep {PRE_SYNC_REF}"
    messages = [message]
    if fetch_failed:
        messages.append(fetch_error)
    if test and (synced.replayed or synced.mode == "rebased"):
        messages += _source_test_warnings(name, repo, test)
    return _PullOutcome(
        name, True, messages, failed="source_fetch_failed" if fetch_failed else None
    )


def _local_sources(tools: list[dict[str, Any]]) -> dict[str, Path]:
    """Map each local-path tool source that is a git checkout to its checkout."""
    from .setup import _expand, _is_local_path

    sources = {
        str(tool.get("name", "")): _expand(str(tool.get("source", "")))
        for tool in tools
        if _is_local_path(str(tool.get("source", "")))
    }
    return {name: repo for name, repo in sources.items() if (repo / ".git").is_dir()}


def _recorded_sources(
    tools: list[dict[str, Any]], entries: list[WorktreeEntry]
) -> dict[str, Path]:
    """Map each local-path tool source with recorded worktrees to its checkout."""
    from .contribute import _repo_key

    recorded = {entry.repo for entry in entries}
    return {
        name: repo
        for name, repo in _local_sources(tools).items()
        if _repo_key(repo) in recorded
    }


def _copy_blocker(repo: Path) -> str | None:
    """Return why ``repo`` cannot take copies of recorded worktrees, or None when it can."""
    from .main_sync import _operation_in_progress, run_git

    if (operation := _operation_in_progress(repo)) is not None:
        return f"a {operation} is in progress"
    branch = run_git(repo, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
    return (
        None
        if branch == "main"
        else f"{branch or 'no branch'} is checked out, not main"
    )


def _copy_recorded_into(
    name: str, repo: Path, entries: list[WorktreeEntry], test: str = ""
) -> tuple[bool, bool, list[WorktreeEntry]]:
    """Copy the ready worktrees of ``repo`` into its main, then run ``test`` when copying moved main.

    Returns:
        Whether main moved, whether copying failed, and the updated record entries.
    """
    from .contribute import _repo_key, copy_recorded, first_stderr_line
    from .main_sync import run_git

    key = _repo_key(repo)
    others = [entry for entry in entries if entry.repo != key]
    before = run_git(repo, "rev-parse", "HEAD").stdout
    try:
        status, updated = copy_recorded(
            repo, [entry for entry in entries if entry.repo == key], others, name
        )
    except subprocess.CalledProcessError as error:
        print(
            f"[{name}] copying recorded worktrees failed ({first_stderr_line(error)})"
        )
        return False, True, entries
    moved = run_git(repo, "rev-parse", "HEAD").stdout != before
    if name == _OWN_TOOL and (
        pending := [e.branch for e in updated if e.pr_state != "MERGED"]
    ):
        has_copy_code = run_git(
            repo,
            "grep",
            "-q",
            "def copy_recorded",
            "main",
            "--",
            "src/llm_prompts/contribute.py",
        )
        if has_copy_code.returncode != 0:
            print(
                f"[{name}] main has no copy-into-main code, so the next update cannot add "
                f"recorded copies: {', '.join(pending)}"
            )
    if status == 0 and moved and test:
        for line in _source_test_warnings(name, repo, test):
            print(line)
    return moved, status != 0, others + updated


def _pull_and_copy(
    tools: list[dict[str, Any]],
    entries: list[WorktreeEntry],
    failed: dict[str, Reason],
) -> tuple[set[str], list[WorktreeEntry]]:
    """Pull every local source, then copy ready worktrees into each main that pulled cleanly.

    Args:
        tools: The configured tool sources.
        entries: The recorded worktrees.
        failed: Collects why each source that could not be pulled or copied failed, by name.

    Returns:
        The names of the sources that moved and the updated record entries.
    """
    from functools import partial

    from .contribute import first_stderr_line, unrecorded_warning
    from .setup import _run_parallel_ordered

    local = _local_sources(tools)
    recorded = _recorded_sources(tools, entries)
    for name, repo in recorded.items():
        if (blocker := _copy_blocker(repo)) is not None:
            print(f"[{name}] {blocker}")
            raise ExitReason("copy_blocked")
    tests = {str(tool.get("name", "")): str(tool.get("test", "")) for tool in tools}
    pulls: list[Callable[[], _PullOutcome]] = [
        partial(
            _pull_one_local_source,
            str(tool.get("name", "")),
            str(tool.get("source", "")),
            str(tool.get("test", "")),
            str(tool.get("ref", "")),
        )
        for tool in tools
    ]
    changed: set[str] = set()
    for outcome in _run_parallel_ordered(pulls):
        for line in outcome.messages:
            print(line)
        if outcome.changed:
            changed.add(outcome.name)
        if outcome.failed:
            failed[outcome.name] = outcome.failed
        elif outcome.name in recorded:
            moved, copied_failed, entries = _copy_recorded_into(
                outcome.name, recorded[outcome.name], entries, tests[outcome.name]
            )
            if copied_failed:
                failed[outcome.name] = "copy_failed"
            if moved:
                changed.add(outcome.name)
        if not outcome.failed and outcome.name in local:
            try:
                warning = unrecorded_warning(local[outcome.name], entries)
            except subprocess.CalledProcessError as error:
                warning = (
                    f"unrecorded branches not checked ({first_stderr_line(error)})"
                )
            if warning is not None:
                print(f"[{outcome.name}] {warning}")
    return changed, entries


def _pull_local_sources(failed: dict[str, Reason] | None = None) -> set[str]:
    """Pull upstream changes for all local-path tool sources, then copy ready worktrees into each main.

    Args:
        failed: Collects why each tool source that could not be pulled or copied failed, by name.

    Returns:
        The names of the tool sources that actually moved.

    Raises:
        ExitReason: When another contribute run holds the record lock or a main cannot take copies.
    """
    from . import worktrees
    from .setup import _load_config, config_path

    if not config_path().exists():
        return set()

    path = worktrees.record_path()
    try:
        with worktrees.locked(path):
            entries = worktrees.load_entries(path)
            changed, updated = _pull_and_copy(
                _load_config(),
                entries,
                failed if failed is not None else {},
            )
            if updated != entries:
                worktrees.save_entries(path, updated)
    except (worktrees.LockHeld, worktrees.CorruptRecord) as error:
        print(error)
        raise ExitReason(
            "record_locked"
            if isinstance(error, worktrees.LockHeld)
            else "record_corrupt"
        ) from error
    return changed


UpdateSources = tuple[list[dict[str, Any]], list[dict[str, Any]]]


def _update_sources() -> UpdateSources:
    """Return the configured tools and plugins, or none without a config file."""
    from .plugins import _load_plugins
    from .setup import _load_config, config_path, read_config

    if not config_path().exists():
        return [], []
    config = read_config()
    return _load_config(config), _load_plugins(config)


def _collect_update_messages(
    previous: tuple[str, list[str]] | None = None,
    sources: UpdateSources | None = None,
) -> list[str]:
    """Collect update-availability messages across all configured tool sources.

    Args:
        previous: The fingerprint and messages of the previous check, to rebuild
            the messages from the refs already fetched instead of fetching.
        sources: The configured tools and plugins, read from config when omitted.

    Returns:
        Message lines describing available updates, in config order, followed
        by a single instruction line when any update is reported.
    """
    from functools import partial

    from .plugins import plugin_source_messages
    from .setup import _is_local_path, _run_parallel_ordered

    tools, plugins = sources or _update_sources()
    checks: list[Callable[[], list[str]]] = []
    for tool in tools:
        name = str(tool.get("name", ""))
        source = str(tool.get("source", ""))
        if _is_local_path(source):
            checks.append(partial(_waiting_conflict_messages, name, source))
            check = partial(
                _previous_failures_or,
                _source_identity(tool),
                previous,
                partial(
                    _local_source_messages,
                    name,
                    source,
                    str(tool.get("ref", "")),
                    previous is None,
                ),
            )
        elif previous is not None:
            check = partial(
                _previous_source_messages, _source_identity(tool), *previous
            )
        else:
            check = partial(_remote_source_messages, name, source, tool.get("ref"))
        checks.append(partial(_update_check_or_failure, _source_identity(tool), check))
    for plugin in plugins:
        name = str(plugin.get("name", ""))
        check = partial(
            _previous_failures_or,
            _source_identity(plugin, "plugin"),
            previous,
            partial(plugin_source_messages, plugin, previous is None),
        )
        checks.append(
            partial(_update_check_or_failure, _source_identity(plugin, "plugin"), check)
        )

    messages: list[str] = []
    for result in _run_parallel_ordered(checks):
        messages.extend(result)
    if messages:
        messages.append(_UPDATE_INSTRUCTION)
    return messages


def _installed_fingerprint(sources: UpdateSources | None = None) -> str:
    """Return each source's identity and installed commit, as JSON, or nothing without sources.

    Args:
        sources: The configured tools and plugins, read from config when omitted.
    """
    from .main_sync import run_git
    from .plugins import _checkout_dir
    from .setup import _expand, _is_local_path

    tools, plugins = sources or _update_sources()
    versions: list[list[str]] = []
    for tool in tools:
        name = str(tool.get("name", ""))
        source = str(tool.get("source", ""))
        if _is_local_path(source):
            sha = run_git(_expand(source), "rev-parse", "HEAD").stdout.strip()
        else:
            sha = _get_installed_commit(name) or ""
        versions.append([*_source_identity(tool), sha])
    for plugin in plugins:
        checkout = _checkout_dir(str(plugin.get("name", "")))
        sha = run_git(checkout, "rev-parse", "HEAD").stdout.strip()
        versions.append([*_source_identity(plugin, "plugin"), sha])
    return json.dumps(versions) if versions else ""


def _check_for_updates() -> bool:
    """Check configured tool sources for available upstream changes.

    Returns:
        True if any updates are available.
    """
    messages = _collect_update_messages()
    for message in messages:
        print(message)
    if not messages:
        print("All tools are up to date.")
    return bool(messages)


def _print_update_status() -> None:
    """Print which sources have updates, ahead of applying them."""
    print("Checking for updates...", flush=True)
    messages = [m for m in _collect_update_messages() if m != _UPDATE_INSTRUCTION]
    print("\n".join(messages) if messages else "No updates found.", flush=True)


def _auto_migrate_memory_db() -> None:
    """Consolidate a split mcp-memory database onto the default path.

    TODO(remove later): transitional self-heal for machines whose service was set up with a
    custom --db-path, which the hook plugin does not inherit (it reads the default). Idempotent
    - a no-op once the DB is already at the default. Remove once all machines are migrated.
    """
    binary = user_binary("mcp-memory")
    if binary:
        result = subprocess.run(
            [binary, "utils", "migrate-db"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == _ARGPARSE_USAGE_ERROR:
            subprocess.run([binary, "migrate-db"], check=False)
        else:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)


def _reconfigure_agents(
    manifest: dict[str, AgentManifest], *, memory_changed: bool
) -> None:
    """Re-apply hook, memory and agent-config wiring for every installed agent.

    Args:
        manifest: The installed-agent manifest.
        memory_changed: Whether the mcp-memory source moved, gating the memory wiring.
    """
    from .install import (
        patch_kiro_agent_config,
        try_allow_update_claude_code,
        try_install_hooks,
        try_install_hooks_antigravity,
        try_install_hooks_claude_code,
        try_install_hooks_opencode,
        try_install_memory,
        try_install_memory_antigravity,
        try_install_memory_claude_code,
        try_install_memory_codex,
        try_install_memory_opencode,
        try_install_memory_pi,
    )

    if "claude-code" in manifest:
        try_install_hooks_claude_code()
        if memory_changed:
            try_install_memory_claude_code()
        try_allow_update_claude_code()

    if "codex" in manifest and memory_changed:
        try_install_memory_codex()

    if "antigravity" in manifest:
        try_install_hooks_antigravity()
        if memory_changed:
            try_install_memory_antigravity()

    if "opencode" in manifest:
        try_install_hooks_opencode()
        if memory_changed:
            try_install_memory_opencode()

    if "pi" in manifest and memory_changed:
        try_install_memory_pi()

    for entry in manifest.values():
        agent_config = entry.get("agent_config")
        if agent_config:
            patch_kiro_agent_config(agent_config)
            try_install_hooks(agent_config)
            if memory_changed:
                try_install_memory(agent_config)


def _standalone_tool_envs() -> set[str]:
    """Return the tracked tools that still have a uv tool env of their own.

    Setup removes these once the tools share one env, which moves their
    binaries and leaves agent hooks and memory servers pointing at nothing.
    """
    return {
        name for name in _RUN_SETUP_TRACKED_TOOLS if (_uv_tools_dir() / name).is_dir()
    }


def _restart_memory_service() -> None:
    """Restart the mcp-memory background service if installed."""
    binary = user_binary("mcp-memory")
    if binary:
        subprocess.run([binary, "restart"], check=False)


def _flush_memory_telemetry() -> None:
    """Ask the running mcp-memory server to send its pending usage telemetry."""
    binary = shutil.which("mcp-memory")
    if binary:
        try:
            result = subprocess.run(
                [binary, "utils", "telemetry-flush"],
                check=False,
                capture_output=True,
                text=True,
                timeout=_MEMORY_FLUSH_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"Could not flush mcp-memory telemetry: {error}", file=sys.stderr)
        else:
            if result.returncode not in (0, _ARGPARSE_USAGE_ERROR):
                print(
                    f"Could not flush mcp-memory telemetry: exit {result.returncode}",
                    result.stderr.strip(),
                    file=sys.stderr,
                )


def _sync_options(args: argparse.Namespace) -> SyncOptions:
    """Return the ``contribute sync`` options the parsed ``args`` ask for."""
    from .contribute import SyncOptions

    return SyncOptions(
        args.apply,
        args.branch,
        args.forget,
        args.ready,
        args.local,
        args.rescan,
        tuple(args.depends_on) if args.depends_on else None,
        tuple(args.no_depends_on) if args.no_depends_on else None,
        tuple(args.why) if args.why else None,
        tuple(args.title) if args.title else None,
        args.only,
    )


def _get_gh_login() -> str:
    """Return the current GitHub user's login, through gh or the GitHub API."""
    if shutil.which("gh") is None:
        try:
            return github_api.login()
        except subprocess.CalledProcessError as error:
            print(error.stderr, file=sys.stderr)
            raise ExitReason("gh_login_failed") from error
    result = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise ExitReason("gh_login_failed")
    return result.stdout.strip()


def main() -> int | None:
    """Run the llm-prompts CLI, reporting anonymous telemetry when it finishes."""
    with telemetry.Run(_get_installed_version) as run, contextlib.ExitStack() as stack:
        return _run_command(run, stack)


def _changes_installed_versions(args: argparse.Namespace) -> bool:
    """Whether the command moves installed versions, and so must not run alongside another that does."""
    if args.command == "update":
        return not args.check
    return args.command in ("install", "setup") or (
        args.command == "contribute"
        and args.contribute_command == "sync"
        and bool(args.apply)
    )


def _flag_names(parser: argparse.ArgumentParser, argv: list[str]) -> list[str]:
    """Return the sorted known option names present in argv, without their values."""
    known: set[str] = set()
    pending = [parser]
    while pending:
        for action in pending.pop()._actions:
            known.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                pending.extend(action.choices.values())
    return sorted({t for a in argv if (t := a.split("=", 1)[0]) in known})


def _add_watch_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ``watch`` command with one subcommand per watch source."""
    from .watch.core.condition import takes
    from .watch.core.registry import sources

    watch_parser = subparsers.add_parser(
        "watch",
        help="Wait until a condition holds on a PR or command, then exit.",
    )
    source_parsers = watch_parser.add_subparsers(dest="source", required=True)
    for name, source in sources().items():
        source_parser = source_parsers.add_parser(
            name,
            help=f"Aliases for --until: {', '.join(source.aliases)}.",
        )
        source.add_arguments(source_parser)
        source_parser.add_argument(
            "--until",
            action="append",
            required=True,
            help=" ".join(
                [
                    "Stop when field=value or changed:field holds, label=GLOB (gh-pr) matches a label, or an alias does. Repeat to stop on any.",
                    *(
                        [f"Aliases: {', '.join(source.aliases)}."]
                        if source.aliases
                        else []
                    ),
                    *(
                        f"{takes(field, values)}."
                        for field, values in getattr(source, "values", {}).items()
                    ),
                ]
            ),
        )
        source_parser.add_argument(
            "--interval",
            type=float,
            help=f"Seconds between polls (default {source.default_interval:g}).",
        )
        source_parser.add_argument(
            "--all",
            action="store_true",
            help="With several targets, wait until every one matches. Default is any.",
        )
        source_parser.add_argument(
            "--timeout", type=float, help="Exit 124 after this many seconds."
        )
        source_parser.add_argument(
            "--follow",
            action="store_true",
            help="Print each match, then keep watching from the new state until the timeout or a terminal state.",
        )


def _run_command(
    run: telemetry.Run, stack: contextlib.ExitStack[bool | None]
) -> int | None:
    """Parse the command line and run the chosen command."""
    version_parser = argparse.ArgumentParser(add_help=False)
    version_parser.add_argument(
        "--version", action="store_true", help="Print the installed version and exit."
    )
    if version_parser.parse_known_args()[0].version:
        print(f"llm-prompts {version('llm-prompts')}")
        return 0
    parser = argparse.ArgumentParser(
        prog="llm-prompts",
        description="Manage LLM prompt rules, workflows, and skills.",
        parents=[version_parser],
    )
    subparsers = parser.add_subparsers(dest="command")
    install_parser = subparsers.add_parser(
        "install",
        help="Install rules, workflows, and skills. Auto-updates remote sources first.",
    )
    install_parser.add_argument(
        "agent",
        choices=[*_AGENTS, "all"],
        help="Agent to install for, or 'all'.",
    )
    install_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show debug output."
    )
    install_parser.add_argument(
        "--no-update",
        action="store_true",
        help="Skip running setup before installing.",
    )
    install_parser.add_argument(
        "--agent-config",
        metavar="PATH",
        help="Kiro agent JSON to patch with resource entries.",
    )
    install_parser.add_argument(
        "--root",
        type=Path,
        metavar="DIR",
        help="Install root used as the home directory.",
    )
    source_parser = subparsers.add_parser(
        "source", help="Show source file locations for an agent."
    )
    source_parser.add_argument(
        "agent",
        choices=_AGENTS,
        help="Agent to show sources for.",
    )
    setup_parser = subparsers.add_parser(
        "setup", help="Install all configured tools with their overlay packages."
    )
    setup_parser.add_argument(
        "--init", action="store_true", help="Create a starter config file."
    )
    setup_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show commands without running them.",
    )
    setup_parser.add_argument(
        "tool", nargs="?", help="Install only this tool (by name from config)."
    )
    settings_parser = subparsers.add_parser(
        "settings",
        help="Print the config file's tools, plugins and settings, and its errors.",
    )
    settings_parser.add_argument(
        "--check",
        action="store_true",
        help="Print the config even in a terminal, without the tui extra.",
    )
    update_parser = subparsers.add_parser(
        "update",
        help="Check for and list updates, then update all installed agents and restart services.",
    )
    update_parser.add_argument(
        "--check",
        action="store_true",
        help="Report available updates without applying them.",
    )
    update_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show every file changed."
    )
    update_parser.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    update_parser.add_argument(
        "--only",
        type=Path,
        metavar="PATH",
        help="Reinstall only the prompt or pi extension (.ts file) built from this edited file.",
    )
    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Remove installed rules, workflows, skills, and agent config patches.",
    )
    uninstall_parser.add_argument(
        "agent",
        choices=[*_AGENTS, *REMOVED_AGENTS, "all"],
        help="Agent to uninstall, or 'all'.",
    )
    uninstall_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show debug output."
    )
    subparsers.add_parser(
        "check",
        help="Check prompt sizes against size_limits.py's thresholds and pi extensions for default factories and summary headers.",
    )
    session_telemetry_parser = subparsers.add_parser(
        "session-telemetry",
        help="Send one pi session's anonymous numbers. The session-telemetry pi extension runs it.",
    )
    session_telemetry_parser.add_argument(
        "stats", type=json.loads, help="The session's totals as JSON."
    )
    size_report_parser = subparsers.add_parser(
        "size-report",
        help="Print a markdown report of prompt size changes against a base.",
    )
    size_report_parser.add_argument(
        "--base-root",
        type=Path,
        required=True,
        help="Base revision's prompts directory to compare against.",
    )
    _add_watch_parser(subparsers)

    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="Run agents through scenarios on two llm-prompts refs and compare the results.",
    )
    add = benchmark_parser.add_argument
    add("--a", metavar="REF", help="First ref to run (default: origin/main).")
    add("--b", metavar="REF", help="Second ref to run (default: :worktree).")
    for label in ("a", "b"):
        add(
            f"--{label}-tool",
            action="append",
            metavar="NAME=SOURCE",
            help=f"Use this source for a configured tool in ref {label.upper()}. Repeatable.",
        )
    add(
        "--b-env",
        action="append",
        metavar="NAME=VALUE",
        help="Set this environment variable for the agents of ref B only. Repeatable.",
    )
    add(
        "--b-drop",
        action="append",
        metavar="RULE",
        help="Leave this shared rule out of ref B's build. Repeatable.",
    )
    add(
        "--feature",
        action="append",
        metavar="NAME",
        help="Measure a pi feature (cache-warming, consult, context-fold, ghost, test-output-fold, warm-fork, shared-tasks or delegate-checkpoint-nudge): A runs without it and B with it. Repeatable.",
    )
    add(
        "--no-reuse",
        dest="reuse",
        action="store_false",
        help="Run A and B again instead of reusing finished runs whose build, scenario and settings match.",
    )
    add("--level", metavar="LEVEL", help="light, medium or heavy (default: light).")
    add("--agents", metavar="LIST", help="Comma separated agents (default: claude,pi).")
    add(
        "--model",
        action="append",
        metavar="AGENT=ID",
        help="Model id for an agent. Repeatable.",
    )
    add(
        "--repeats",
        type=int,
        metavar="N",
        help="Run every scenario this many times per agent and ref (default: one, then more while A and B differ).",
    )
    add(
        "--max-repeats",
        type=int,
        metavar="N",
        help="Most runs per scenario, agent and ref when --repeats is not given (default: 3).",
    )
    add(
        "--overlays",
        action="store_true",
        help="Install every configured overlay (default: only the core tools and the overlays that set up an agent's model provider).",
    )
    add(
        "--overlay",
        action="append",
        metavar="NAME",
        help="Install this configured overlay. Repeatable.",
    )
    add(
        "-j",
        "--jobs",
        type=int,
        metavar="N",
        help="Parallel cells (default: [benchmark] jobs in config.toml, else 4).",
    )
    add(
        "--scenario",
        action="append",
        metavar="ID",
        help="Run only this scenario. Repeatable.",
    )
    add(
        "--fail-fast",
        action="store_true",
        help="Stop the whole run at the first setup error (auth, disk full, agent crash, harness error). Skip the rest of a side's repeats of a scenario once its first N runs fail the same check.",
    )
    add(
        "--fail-fast-after",
        type=int,
        metavar="N",
        help="With --fail-fast, runs that must fail the same check before the rest are skipped (default: 3).",
    )
    add(
        "--no-os-sandbox",
        dest="os_sandbox",
        action="store_false",
        help="Run without the OS sandbox.",
    )
    add(
        "--judge",
        choices=("auto", "pi", "claude"),
        help="Harness for judge checks (default: auto, pi if on PATH, else claude).",
    )
    contribute_parser = subparsers.add_parser(
        "contribute", help="Manage derived PR branches for prompt-source commits."
    )
    contribute_sub = contribute_parser.add_subparsers(
        dest="contribute_command", required=True
    )
    tool_parser = argparse.ArgumentParser(add_help=False)
    tool_parser.add_argument(
        "--tool",
        metavar="NAME",
        help="Only contribute to this configured tool (default: every locally-cloned tool).",
    )
    contribute_sub.add_parser(
        "list",
        help="Show every derived contribution branch and its state.",
        parents=[tool_parser],
    )
    sync_parser = contribute_sub.add_parser(
        "sync",
        help="Sync recorded worktrees with main and GitHub (dry run unless --apply).",
        parents=[tool_parser],
    )
    sync_parser.add_argument(
        "--apply", action="store_true", help="Actually copy, pull, push and remove."
    )
    sync_parser.add_argument(
        "--branch", metavar="BRANCH", help="Record the worktree on this branch."
    )
    sync_parser.add_argument(
        "--forget", metavar="BRANCH", help="Stop managing this recorded branch."
    )
    sync_parser.add_argument(
        "--ready",
        metavar="BRANCH",
        help="Let sync push this branch and open its draft PR.",
    )
    sync_parser.add_argument(
        "--local",
        metavar="BRANCH",
        help="Stop sync pushing this branch or touching its PR.",
    )
    sync_parser.add_argument(
        "--depends-on",
        nargs=2,
        metavar=("BRANCH", "TOOL:BRANCH|OWNER/REPO#N"),
        help="Make BRANCH depend on TOOL:BRANCH in another repo, or on a PR in any repo.",
    )
    sync_parser.add_argument(
        "--no-depends-on",
        nargs=2,
        metavar=("BRANCH", "TOOL:BRANCH|OWNER/REPO#N"),
        help="Remove the dependency of BRANCH on TOOL:BRANCH or a PR.",
    )
    sync_parser.add_argument(
        "--why",
        nargs=2,
        metavar=("BRANCH", "TEXT"),
        help="Record the text sync puts under Why in BRANCH's PR.",
    )
    sync_parser.add_argument(
        "--title",
        nargs=2,
        metavar=("BRANCH", "TEXT"),
        help="Record the title sync gives BRANCH's PR instead of its first commit's subject.",
    )
    sync_parser.add_argument(
        "--rescan",
        action="store_true",
        help="Record your open PRs whose branch is checked out in a worktree.",
    )
    sync_parser.add_argument(
        "--only",
        metavar="BRANCH",
        help="Sync only this recorded branch. Main copies of other branches above "
        "its replaced copy keep their content but may get new commit SHAs.",
    )

    check_body_parser = contribute_sub.add_parser(
        "check-body",
        help="Check a PR body file against the PR template, as CI does.",
    )
    check_body_parser.add_argument("body_file", type=Path, metavar="FILE")

    update_parser = contribute_sub.add_parser(
        "update",
        help="Rebase your open PRs that are behind main onto it (dry run unless --apply).",
        parents=[tool_parser],
    )
    update_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually run gh pr update-branch --rebase.",
    )
    update_parser.add_argument(
        "--pr",
        dest="numbers",
        action="append",
        type=int,
        metavar="NUMBER",
        help="Only update this PR; repeatable.",
    )
    update_parser.add_argument(
        "--include-auto-merge",
        action="store_true",
        help="Also update PRs with auto-merge on, which are otherwise left to the rebase queue.",
    )

    ready_parser = contribute_sub.add_parser(
        "ready",
        help="Mark a PR ready, labelling it owner-reviewed first when it needs the owner, and enable squash auto-merge.",
        parents=[tool_parser],
    )
    ready_parser.add_argument("number", type=int, help="The PR number.")

    pr_parser = subparsers.add_parser(
        "pr",
        help="Check the size of a PR's prompts, rebase it onto main, mark it ready and set auto-merge.",
    )
    pr_parser.add_argument("number", type=int, help="The PR number.")
    pr_parser.add_argument(
        "--tool",
        metavar="NAME",
        required=True,
        help="The configured tool the PR is in.",
    )

    args = parser.parse_args()

    if (
        args.command == "contribute"
        and args.contribute_command == "ready"
        and args.tool is None
    ):
        ready_parser.error("ready requires --tool NAME.")

    if (
        args.command == "contribute"
        and args.contribute_command == "update"
        and args.numbers
        and args.tool is None
    ):
        update_parser.error("--pr requires --tool NAME.")

    if (
        args.command == "contribute"
        and args.contribute_command == "sync"
        and _sync_options(args).record_edits + args.rescan > 1
    ):
        sync_parser.error(
            "Pass only one of --branch, --forget, --ready, --local, "
            "--depends-on, --no-depends-on, --why, --title and --rescan."
        )

    if (
        args.command == "contribute"
        and args.contribute_command == "sync"
        and args.only
        and (_sync_options(args).edits_record or args.rescan)
    ):
        sync_parser.error("--only cannot be used with a record edit or --rescan.")

    if (
        args.command == "contribute"
        and args.contribute_command == "sync"
        and _sync_options(args).edits_record
        and args.tool is None
    ):
        sync_parser.error(
            "--branch, --forget, --ready, --local, --depends-on, "
            "--no-depends-on, --why and --title require --tool NAME."
        )

    if args.command == "install" and args.root:
        set_root(args.root)

    if args.command == "session-telemetry":
        telemetry.send_session(args.stats)
        return None

    if args.command:
        run.begin(
            args.command,
            _flag_names(parser, sys.argv[1:]),
            installs=args.command in _INSTALLING_COMMANDS,
        )

    if _changes_installed_versions(args):
        from .auto_update import LOCK_FD_ENV, UPDATE_RUNNING, lock

        if not stack.enter_context(lock()):
            raise ExitReason("update_running", UPDATE_RUNNING)

    if args.command == "install":
        if args.root:
            log(
                "info",
                "[root] Skipping setup, hook and memory installs: they cannot target --root.",
            )
        if not args.no_update and not args.root:
            from .setup import (
                config_path,
                detect_stale_local_tools,
                run_setup,
            )

            stale = detect_stale_local_tools()
            if config_path().exists():
                run_setup(force_reinstall=stale or None)
                child_env = {
                    **os.environ,
                    telemetry.RESUME_ENV: json.dumps(run.hand_over()),
                }
                result = subprocess.run(
                    [sys.argv[0], "install", args.agent]
                    + (["--verbose"] if args.verbose else [])
                    + (
                        ["--agent-config", args.agent_config]
                        if args.agent_config
                        else []
                    )
                    + ["--no-update"],
                    check=False,
                    env=child_env,
                    pass_fds=(int(os.environ[LOCK_FD_ENV]),),
                )
                sys.exit(result.returncode)

        from .install import main as install_main

        agent_names = list(_AGENTS) if args.agent == "all" else [args.agent]
        install_failure = install_main(
            agent_names, verbose=args.verbose, root=args.root
        )

        if "claude-code" in agent_names:
            from .install import (
                try_allow_update_claude_code,
                try_enable_task_tools_claude_code,
                try_install_hooks_claude_code,
                try_install_memory_claude_code,
            )

            if not args.root:
                try_install_hooks_claude_code()
                try_install_memory_claude_code()
            try_allow_update_claude_code()
            try_enable_task_tools_claude_code()

        if "codex" in agent_names and not args.root:
            from .install import try_install_memory_codex

            try_install_memory_codex()

        if "antigravity" in agent_names and not args.root:
            from .install import (
                try_install_hooks_antigravity,
                try_install_memory_antigravity,
            )

            try_install_hooks_antigravity()
            try_install_memory_antigravity()

        if "opencode" in agent_names and not args.root:
            from .install import (
                try_install_hooks_opencode,
                try_install_memory_opencode,
            )

            try_install_hooks_opencode()
            try_install_memory_opencode()

        if "pi" in agent_names and not args.root:
            from .install import try_install_memory_pi

            try_install_memory_pi()

        if args.agent_config:
            from .install import (
                patch_kiro_agent_config,
                try_install_hooks,
                try_install_memory,
            )
            from .manifest import read_manifest, write_manifest

            patch_kiro_agent_config(args.agent_config)
            if not args.root:
                try_install_hooks(args.agent_config)
                try_install_memory(args.agent_config)

            for name in agent_names:
                existing = read_manifest().get(name, {})
                write_manifest(
                    name,
                    existing.get("files", []),
                    agent_config=args.agent_config,
                )

        if install_failure:
            run.outcome = install_failure
            sys.exit(1)
    elif args.command == "source":
        _print_sources(args.agent)
    elif args.command == "setup":
        from .setup import init_config, run_setup

        if args.init:
            init_config()
        else:
            standalone_before_setup = _standalone_tool_envs()
            run_setup(args.tool, dry_run=args.dry_run)
            moved = standalone_before_setup - _standalone_tool_envs()
            if moved:
                from .manifest import read_manifest

                manifest = read_manifest()
                if manifest:
                    _reconfigure_agents(manifest, memory_changed=_MEMORY_TOOL in moved)
                if _MEMORY_TOOL in moved:
                    _restart_memory_service()
    elif args.command == "update":
        if args.check:
            _check_for_updates()
            sys.exit(0)

        from .manifest import read_manifest
        from .setup import (
            config_path,
            detect_changed_configured_tools,
            detect_stale_local_tools,
            run_setup,
        )

        manifest = read_manifest()
        for name in REMOVED_AGENTS:
            if manifest.pop(name, None) is not None:
                log(
                    "warn",
                    f"[{name}] no longer supported. Run `llm-prompts uninstall {name}`.",
                )
        if not manifest:
            raise ExitReason(
                "no_installed_agents",
                "No installed agents found. Run `llm-prompts install <agent>` first.",
            )

        from .install import main as install_main
        from .install import partial_source

        only_source = partial_source(args.only) if args.only else None
        if only_source is not None:
            if failure := install_main(
                list(manifest), only=only_source, verbose=args.verbose
            ):
                run.outcome = failure
                sys.exit(1)
            sys.exit(0)
        if args.only and args.only.suffix == ".ts":
            raise ExitReason(
                "other",
                f"{args.only} is not a source an extension can be reinstalled from alone.",
            )

        resumed = os.environ.pop(_UPDATE_RESUME_ENV, None)
        if resumed is None:
            from .size_guard import snapshot_sources

            _print_update_status()
            size_baseline = snapshot_sources(_size_guard_roots())
            failed_sources: dict[str, Reason] = {}
            changed_sources = _pull_local_sources(failed_sources)
            if failed_sources:
                print(
                    f"Update stopped: {', '.join(sorted(failed_sources))} "
                    "could not be updated, so the installed versions would not match. "
                    "Fix the errors above, then rerun `llm-prompts update`."
                )
                reasons = [failed_sources[name] for name in sorted(failed_sources)]
                if set(reasons) == {"copy_failed"}:
                    raise ExitReason("copy_failed")
                run.outcome = "source_sync_failed"
                raise ExitReason(next(r for r in reasons if r != "copy_failed"))

            from .plugins import pull_plugin_sources

            pull_plugin_sources()

            dists_before_setup = {
                name: _get_installed_dist(name) for name in _RUN_SETUP_TRACKED_TOOLS
            }
            standalone_before_setup = _standalone_tool_envs()
            stale = detect_stale_local_tools()
            changed_sources |= detect_changed_configured_tools()
            upgraded = config_path().exists() and run_setup(
                force_reinstall=stale or None
            )
            for name in _RUN_SETUP_TRACKED_TOOLS:
                if _get_installed_dist(name) != dists_before_setup[name]:
                    changed_sources.add(name)
            changed_sources |= standalone_before_setup - _standalone_tool_envs()
            if upgraded:
                _reexec_update(changed_sources, size_baseline, run)
        else:
            state = json.loads(resumed)
            run.restore(state.get("telemetry"))
            changed_sources = set(state["changed_sources"])
            size_baseline = {
                Path(path): h for path, h in state["size_baseline"].items()
            }

        install_failure = install_main(
            list(manifest), size_baseline=size_baseline, verbose=args.verbose
        )

        memory_changed = _MEMORY_TOOL in changed_sources
        if changed_sources:
            _reconfigure_agents(manifest, memory_changed=memory_changed)
        if "claude-code" in manifest:
            from .install import try_enable_task_tools_claude_code

            try_enable_task_tools_claude_code()
        if memory_changed:
            _flush_memory_telemetry()
            _auto_migrate_memory_db()
            _restart_memory_service()

        if install_failure:
            run.outcome = install_failure
            sys.exit(1)
    elif args.command == "settings":
        from .settings import run as run_settings

        run_settings(check=args.check)
    elif args.command == "uninstall":
        from .install import uninstall

        uninstall(None if args.agent == "all" else [args.agent], verbose=args.verbose)
    elif args.command == "check":
        with run.exit_outcome("check_failed"):
            _run_size_check()
            _run_extension_factory_check()
    elif args.command == "size-report":
        from .size_report import build_report

        print(build_report(args.base_root))
    elif args.command == "watch":
        from .watch.core.condition import expand
        from .watch.core.registry import sources
        from .watch.core.runner import watch
        from .watch.core.source import WatchError

        source_type = sources()[args.source]
        try:
            expand(args.until, source_type.aliases, getattr(source_type, "values", {}))
        except WatchError as error:
            print(f"watch: {error}", file=sys.stderr)
            return 1
        built = source_type.from_args(args)
        discoverer = getattr(source_type, "discoverer", None)
        return watch(
            built if isinstance(built, Sequence) else [built],
            args.until,
            interval=source_type.default_interval
            if args.interval is None
            else args.interval,
            discover=discoverer(args) if discoverer else None,
            timeout=args.timeout,
            require_all=args.all,
            follow=args.follow,
        )
    elif args.command == "benchmark":
        from .benchmark.command import RunOptions
        from .benchmark.command import run as run_benchmark

        try:
            options = RunOptions.from_args(args)
        except ValueError as error:
            benchmark_parser.error(str(error))
        return run_benchmark(options)
    elif args.command == "contribute":
        from .contribute import (
            check_body,
            list_targets,
            run_ready,
            sync_targets,
            update_targets,
        )

        if args.contribute_command == "check-body":
            return check_body(args.body_file, Path.cwd())
        with run.exit_outcome("usage_error"):
            if args.tool is not None:
                repo, prefix = _contribute_target(args.tool)
                targets = [_ContributeTarget(args.tool, repo, prefix)]
            else:
                targets = _contribute_targets()
        if args.contribute_command == "list":
            return list_targets(targets)
        if args.contribute_command == "ready":
            return run_ready(targets[0].repo, args.number)
        if args.contribute_command == "update":
            return update_targets(
                targets, args.apply, args.numbers or (), args.include_auto_merge
            )
        sync_options = _sync_options(args)
        linking = sync_options.depends_on or sync_options.no_depends_on
        return sync_targets(
            targets,
            "" if sync_options.edits_record else _get_gh_login(),
            sync_options,
            _contribute_targets() if linking else targets,
        )
    elif args.command == "pr":
        from .pr import run_pr

        with run.exit_outcome("usage_error"):
            repo, prefix = _contribute_target(args.tool)
        return run_pr(repo, prefix, args.number)
    else:
        parser.print_help()
        sys.exit(1)
    return None


if __name__ == "__main__":
    main()
