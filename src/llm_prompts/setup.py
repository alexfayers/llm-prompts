"""Setup command for installing llm-prompts and related tools."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlparse

from . import home
from .exit_reason import ExitReason
from .network import run_with_retries
from .squash_subject import squash_pr_number


def config_path() -> Path:
    """Return the path of the llm-prompts config file."""
    return home.config_dir() / "config.toml"


GIT_TIMEOUT = 30
_OWN_PACKAGE = "llm-prompts"
_STARTUP_CHECK = "import llm_prompts.cli, cline_hooks.core.user_install"
TEST_TIMEOUT = 600

_DEFAULT_CONFIG = """\
# llm-prompts setup configuration
# Run `llm-prompts setup` to install all tools into one shared environment.

# Each [[tools]] entry is a package to install.
# `source` can be:
#   - A git URL (e.g. "git+https://github.com/user/repo.git")
#   - A local path (~/git/pkg or /abs/path) - installed from the checkout
#
# A git source installs its latest stable release tag (vX.Y.Z), or HEAD if it has
# none. Set `ref = "main"` (a branch, tag or commit) on an entry to follow that instead.
#
# A local-path entry can set `test = "just test"`. `llm-prompts update` runs it in
# the checkout after rebasing or replaying local commits or changing main by copying
# recorded worktrees, and only warns if it fails.
#
# The first entry owns the environment; the others are installed alongside it.
# Each tool's commands are taken from its pyproject.toml scripts.
#
# Agent sessions run `llm-prompts update` in the background when updates exist.
# Add `[update]` with `auto = false` to turn that off.

[[tools]]
name = "llm-prompts"
source = "git+https://github.com/alexfayers/llm-prompts.git"

[[tools]]
name = "cline-hooks"
source = "git+https://github.com/alexfayers/cline-hooks.git"

[[tools]]
name = "mcp-memory"
source = "git+https://github.com/alexfayers/mcp-memory.git"
"""


def _is_local_path(source: str) -> bool:
    """Check if a source string refers to a local path."""
    return source.startswith(("~/", "/", "./", "../"))


def _extract_git_url(source: str) -> str | None:
    """Extract a usable git URL from a source string."""
    if source.startswith("git+"):
        return source[4:]
    if source.startswith(("https://", "git://", "ssh://")):
        return source
    return None


# Update prompts/shared/rules/hooks-llm-prompts.md if this message text changes.
_UPDATE_INSTRUCTION = (
    "Summarize these changes for the user in plain language, and flag "
    "anything that looks like a breaking change."
)

_CHANGELOG_PREFIX = "Changelog: "

SHIPPED_PATHS = [
    "src",
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "pnpm-lock.yaml",
]


def _format_update_message(
    name: str,
    subjects: list[str] | None,
    local: str | None = None,
    remote: str | None = None,
    cap: int = 20,
    release: tuple[str, str] | None = None,
    changelog: str | None = None,
    sections: list[str] | None = None,
) -> list[str]:
    """Build an update-availability message, listing commit messages when known.

    Args:
        name: The source name, used in the header.
        subjects: Commit messages newer than the local commit, each a subject
            optionally followed by body lines, or ``None`` when the commit list
            could not be determined.
        local: The local commit label, used only for the bare fallback message.
        remote: The remote commit label, used only for the bare fallback message.
        cap: Maximum number of commits to list before truncating.
        release: The installed and available versions, shown in the header.
        changelog: The changelog URL, shown under the header.
        sections: CHANGELOG sections, all listed in place of ``subjects`` when given.

    Returns:
        A single multi-line message listing the commits, body lines indented
        under their subject, or the bare "update available" fallback when
        ``subjects`` is empty/``None``.
    """
    if release:
        local, remote = release
    versions = f" ({local} -> {remote})" if local and remote else ""
    links = [f"{_CHANGELOG_PREFIX}{changelog}"] if changelog else []
    entries = sections or subjects
    if not entries:
        return ["\n".join([f"[{name}] update available{versions}", *links])]

    shown = sections or entries[:cap]
    lines = [f"[{name}] update available{versions if release else ''}:", *links]
    lines.extend("- " + subject.replace("\n", "\n  ") for subject in shown)
    if len(entries) > len(shown):
        lines.append(f"... and {len(entries) - len(shown)} more")
    return ["\n".join(lines)]


def _remote_head(git_url: str, ref: str | None) -> str | None:
    """Return the commit SHA a remote git ref points at, via ls-remote.

    Args:
        git_url: The remote git URL to query.
        ref: The remote ref to resolve; defaults to ``HEAD``.

    Returns:
        The remote commit SHA, or ``None`` if the ref resolves to nothing.

    Raises:
        subprocess.CalledProcessError: If ``git ls-remote`` exits non-zero.
    """
    result = run_with_retries(
        ["git", "ls-remote", git_url, ref or "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_TIMEOUT,
    )
    if not result.stdout.strip():
        return None
    return result.stdout.split()[0]


_RELEASE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def _latest_release_tag(git_url: str) -> tuple[str, str] | None:
    """Return the highest stable ``vX.Y.Z`` tag of a remote and its commit, via ls-remote.

    Args:
        git_url: The remote git URL to query.

    Returns:
        The tag name and the commit it points at (the peeled commit for an
        annotated tag), or ``None`` if the remote has no stable ``v*`` tag.

    Raises:
        subprocess.CalledProcessError: If ``git ls-remote`` exits non-zero.
    """
    result = run_with_retries(
        ["git", "ls-remote", "--tags", git_url, "v*"],
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_TIMEOUT,
    )
    releases: dict[str, str] = {}
    for line in result.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        tag = ref.removeprefix("refs/tags/")
        if tag.endswith("^{}"):
            releases[tag.removesuffix("^{}")] = sha
        else:
            releases.setdefault(tag, sha)
    versions = {
        tuple(map(int, match.groups())): tag
        for tag in releases
        if (match := _RELEASE_TAG.fullmatch(tag))
    }
    if not versions:
        return None
    tag = versions[max(versions)]
    return tag, releases[tag]


def release_version(tag: str) -> tuple[int, ...] | None:
    """Return the version numbers of a stable ``vX.Y.Z`` tag, or ``None`` for any other tag."""
    match = _RELEASE_TAG.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


_CHANGELOG_SECTION = re.compile(r"^## \[(\d+)\.(\d+)\.(\d+)\]", re.MULTILINE)


def release_notes(changelog: str, old: str, new: str) -> list[str]:
    """Return the CHANGELOG sections of the releases after tag ``old`` up to tag ``new``, newest first, without blank lines."""
    low, high = release_version(old), release_version(new)
    if low is None or high is None:
        return []
    starts = list(_CHANGELOG_SECTION.finditer(changelog))
    ends = [start.start() for start in starts[1:]] + [len(changelog)]
    return [
        "\n".join(
            line for line in changelog[start.start() : end].splitlines() if line.strip()
        )
        for start, end in zip(starts, ends, strict=False)
        if low < tuple(map(int, start.groups())) <= high
    ]


_SQUASHED_MERGE_PREFIX = "* Merge "
_SQUASHED_COMMIT_PREFIX = "* "
_MORE_SUFFIX = re.compile(r" \(\+\d+ more\)(?= \(#\d+\)$|$)")


def _commit_entry(lines: list[str]) -> str:
    """Return a commit's subject and the squashed commits its body lists, minus merge commits.

    A squash commit whose body lists its squashed commits is headed by its PR
    number instead of its subject; any other subject loses its "(+N more)" count.
    """
    subject, *rest = lines
    body = [
        line.rstrip()
        for line in rest
        if line.startswith(_SQUASHED_COMMIT_PREFIX)
        and not line.startswith(_SQUASHED_MERGE_PREFIX)
    ]
    if (pr := squash_pr_number(subject)) is not None and body:
        subject = f"PR #{pr}"
    else:
        subject = _MORE_SUFFIX.sub("", subject.rstrip())
    return "\n".join([subject, *body])


def _commit_subjects_between(
    repo: Path, from_sha: str, to_sha: str, paths: list[str] | None = None
) -> list[str] | None:
    """Return the commit messages in ``from_sha..to_sha`` within a local repo.

    Args:
        repo: A local git checkout to run ``git log`` against.
        from_sha: The exclusive lower-bound commit.
        to_sha: The inclusive upper-bound commit.
        paths: Optional git pathspecs; only commits touching them are listed.

    Returns:
        One entry per non-merge commit, newest-first, holding its subject or
        squash PR number followed by its kept body lines, or ``None`` if the log
        command fails.
    """
    pathspec = ["--", *paths] if paths else []
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "log",
            "--pretty=format:%s%n%b%x1e",
            "--no-merges",
            f"{from_sha}..{to_sha}",
            *pathspec,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=GIT_TIMEOUT,
    )
    if result.returncode != 0:
        return None
    messages = (
        record.strip("\n").splitlines() for record in result.stdout.split("\x1e")
    )
    return [_commit_entry(lines) for lines in messages if lines]


def _remote_changes(
    git_url: str, from_sha: str, to_sha: str, read_changelog: bool = False
) -> tuple[list[str] | None, str]:
    """Get commit subjects between two SHAs, and the CHANGELOG at ``to_sha``, by cloning a remote into a temp dir.

    Uses a treeless, no-checkout partial clone to fetch history cheaply. Any
    failure (git missing, clone/log error, timeout) degrades to ``None`` rather
    than raising, so the caller can fall back to a bare message.

    Args:
        git_url: The remote git URL to clone.
        from_sha: The exclusive lower-bound commit.
        to_sha: The inclusive upper-bound commit.
        read_changelog: Whether to read CHANGELOG.md at ``to_sha``.

    Returns:
        The subject lines newest-first, or ``None`` on any failure, and the
        CHANGELOG text, or "" when not read or missing.
    """
    if not shutil.which("git"):
        print(
            f"Warning: git not available; skipping commit subjects for {git_url}",
            file=sys.stderr,
        )
        return None, ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_with_retries(
                ["git", "clone", "--filter=tree:0", "--no-checkout", git_url, tmp],
                capture_output=True,
                text=True,
                check=False,
                timeout=GIT_TIMEOUT,
            )
            if result.returncode != 0:
                print(
                    f"Warning: could not clone {git_url} for commit subjects",
                    file=sys.stderr,
                )
                return None, ""
            subjects = _commit_subjects_between(
                Path(tmp), from_sha, to_sha, SHIPPED_PATHS
            )
            if not read_changelog:
                return subjects, ""
            changelog = subprocess.run(
                ["git", "-C", tmp, "show", f"{to_sha}:CHANGELOG.md"],
                capture_output=True,
                text=True,
                check=False,
                timeout=GIT_TIMEOUT,
            )
            return subjects, changelog.stdout
    except subprocess.TimeoutExpired:
        print(
            f"Warning: timed out cloning {git_url} for commit subjects",
            file=sys.stderr,
        )
        return None, ""
    except Exception:
        return None, ""


def _run_parallel_ordered[T](callables: list[Callable[[], T]]) -> list[T]:
    """Run each callable concurrently, preserving submission order in the result.

    Args:
        callables: Zero-arg functions.

    Returns:
        One result per callable, in the same order as ``callables``.
    """
    if not callables:
        return []
    with ThreadPoolExecutor(max_workers=len(callables)) as executor:
        return list(executor.map(lambda fn: fn(), callables))


@functools.cache
def _fetch_remote_pyproject(git_url: str) -> dict[str, Any] | None:
    """Shallow-clone a remote git source and return its parsed pyproject.toml, or None."""
    if not shutil.which("git"):
        print(
            f"Warning: git not available; skipping overlay inference for {git_url}",
            file=sys.stderr,
        )
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_with_retries(
                ["git", "clone", "--depth", "1", git_url, tmp],
                capture_output=True,
                text=True,
                check=False,
                timeout=GIT_TIMEOUT,
            )
            if result.returncode != 0:
                print(
                    f"Warning: could not clone {git_url} for overlay inference",
                    file=sys.stderr,
                )
                return None
            pyproject = Path(tmp) / "pyproject.toml"
            if not pyproject.exists():
                return None
            return tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        print(
            f"Warning: timed out cloning {git_url} for overlay inference",
            file=sys.stderr,
        )
        return None
    except Exception:
        return None


def _read_pyproject(tool: dict[str, Any]) -> dict[str, Any] | None:
    """Return the parsed pyproject.toml for a tool's source, local or remote."""
    source = str(tool.get("source", ""))
    if _is_local_path(source):
        pyproject = _expand(source) / "pyproject.toml"
        if not pyproject.exists():
            return None
        try:
            return tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except Exception:
            return None
    git_url = _extract_git_url(source)
    if git_url:
        return _fetch_remote_pyproject(git_url)
    return None  # unrecognised source: inference not supported, use explicit fields


def _pyproject_stamp_path() -> Path:
    """Return the path of the local-tool pyproject hash stamp file."""
    from platformdirs import user_data_dir

    return Path(user_data_dir("llm-prompts")) / ".llm-prompts-pyproject-stamp"


def _hash_local_pyprojects() -> dict[str, str]:
    """Return a name -> sha256 map of each local tool's pyproject.toml.

    Tools whose source is non-local or whose pyproject.toml is missing are
    skipped.

    Returns:
        A mapping of tool name to the hex digest of its pyproject.toml bytes.
    """
    hashes: dict[str, str] = {}
    for tool in _load_config():
        source = str(tool.get("source", ""))
        if not _is_local_path(source):
            continue
        pyproject = _expand(source) / "pyproject.toml"
        if not pyproject.exists():
            continue
        hashes[str(tool.get("name", ""))] = hashlib.sha256(
            pyproject.read_bytes()
        ).hexdigest()
    return hashes


def detect_stale_local_tools() -> set[str]:
    """Return the names of local tools whose pyproject.toml differs from the stamp.

    Returns:
        An empty set if there is no config or no stamp file yet; otherwise the
        names whose current hash is missing from or differs from the stamp.
    """
    if not config_path().exists():
        return set()
    stamp = _pyproject_stamp_path()
    if not stamp.exists():
        return set()
    try:
        recorded = json.loads(stamp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return set()
    current = _hash_local_pyprojects()
    return {name for name, digest in current.items() if recorded.get(name) != digest}


def write_pyproject_stamp() -> None:
    """Write the current local-tool pyproject hashes to the stamp file."""
    stamp = _pyproject_stamp_path()
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps(_hash_local_pyprojects()), encoding="utf-8")


def _checkout_stamp_path() -> Path:
    """Return the path of the local-checkout state stamp file."""
    return _pyproject_stamp_path().with_name(".llm-prompts-checkout-stamp")


_NOT_PROMPTS = ":(exclude,glob)**/prompts/**"


def _checkout_state(repo: Path, include_prompts: bool = False) -> str | None:
    """Return a digest of a checkout's files, status and uncommitted diff, outside prompts unless asked.

    Args:
        repo: The checkout directory.
        include_prompts: Whether prompt files count towards the digest.

    Returns:
        The hex digest, or ``None`` if git fails.
    """
    digest = hashlib.sha256()
    for args in (["ls-files", "-s"], ["status", "--porcelain"], ["diff", "HEAD"]):
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    *args,
                    *(() if include_prompts else ("--", _NOT_PROMPTS)),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=GIT_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        digest.update(result.stdout.encode())
    return digest.hexdigest()


def _hash_local_checkouts(tools: list[dict[str, Any]]) -> dict[str, str | None]:
    """Return a name -> state digest map of each local tool's checkout.

    Args:
        tools: The configured tools.

    Returns:
        A mapping of local tool name to its checkout state, ``None`` if unreadable.
    """
    return {
        str(tool.get("name", "")): _checkout_state(_expand(str(tool["source"])))
        for tool in tools
        if _is_local_path(str(tool.get("source", "")))
    }


def detect_changed_local_tools(tools: list[dict[str, Any]]) -> set[str]:
    """Return the names of local tools whose checkout differs from the stamp.

    Args:
        tools: The configured tools.

    Returns:
        The local tool names whose checkout state is unreadable or differs from
        the stamp; every local tool if the stamp is missing or unreadable.
    """
    try:
        recorded = json.loads(_checkout_stamp_path().read_text(encoding="utf-8"))
    except (ValueError, OSError):
        recorded = {}
    return {
        name
        for name, state in _hash_local_checkouts(tools).items()
        if state is None or recorded.get(name) != state
    }


def detect_changed_configured_tools() -> set[str]:
    """Return the names of configured local tools whose checkout differs from the stamp.

    Returns:
        An empty set if there is no config; otherwise the changed local tool names.
    """
    if not config_path().exists():
        return set()
    return detect_changed_local_tools(_load_config())


def write_checkout_stamp(tools: list[dict[str, Any]]) -> None:
    """Write the current local-checkout states to the stamp file.

    Args:
        tools: The configured tools.
    """
    stamp = _checkout_stamp_path()
    stamp.parent.mkdir(parents=True, exist_ok=True)
    states = {
        name: state
        for name, state in _hash_local_checkouts(tools).items()
        if state is not None
    }
    stamp.write_text(json.dumps(states), encoding="utf-8")


def _expand(path_str: str) -> Path:
    """Expand ~ and resolve a path string."""
    return Path(path_str).expanduser().resolve()


def _require_uv() -> None:
    """Exit with an error if uv is not installed."""
    if not shutil.which("uv"):
        print("setup needs uv: https://docs.astral.sh/uv/", file=sys.stderr)
        raise ExitReason("uv_missing")


class SharedEnv(NamedTuple):
    """The commands and expected contents of the one uv tool env holding every tool."""

    name: str
    install_cmd: list[str]
    upgrade_cmd: list[str]
    members: list[str]
    scripts: list[str]


def _build_commands(
    tools: list[dict[str, Any]],
    changed_local: set[str],
    pins: Mapping[str, str] | None = None,
) -> SharedEnv:
    """Build the commands for the uv tool env owned by the first tool.

    Args:
        tools: The configured tools; the first owns the env and the rest are
            members installed alongside it.
        changed_local: Names of local tools whose upgrade must rebuild them.
        pins: Tool names mapped to the ref their install source is pinned to.

    Returns:
        The install and upgrade commands, the member names and the script names
        the env must expose.
    """
    owner, *members = tools
    name = package_name(owner)
    member_names = [package_name(member) for member in members]
    scripts = {package_name(tool): _script_names(tool) for tool in tools}
    return SharedEnv(
        name,
        _build_install_cmd(
            owner, members, [n for n in member_names if scripts[n]], pins or {}
        ),
        _build_upgrade_cmd(
            name,
            member_names,
            {package_name(t) for t in tools if str(t["name"]) in changed_local},
            _git_dependencies(tools),
        ),
        member_names,
        [script for names in scripts.values() for script in names],
    )


def _build_install_cmd(
    owner: dict[str, Any],
    members: list[dict[str, Any]],
    executable_members: list[str],
    pins: Mapping[str, str],
) -> list[str]:
    """Build a full install command."""

    def source(tool: dict[str, Any]) -> str:
        pin = pins.get(str(tool["name"]))
        return _install_source(str(tool["source"])) + (f"@{pin}" if pin else "")

    cmd = ["uv", "tool", "install", source(owner)]
    for member in members:
        cmd.extend(["--with", source(member)])
    if executable_members:
        cmd.extend(["--with-executables-from", ",".join(executable_members)])
    for package in [owner, *members]:
        cmd.extend(["--no-sources-package", package_name(package)])
    cmd.extend(["--reinstall", "--force"])
    return cmd


def _canonical_name(name: str) -> str:
    """Return the PEP 503 normalised form of a package name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def package_name(tool: dict[str, Any]) -> str:
    """Return the canonical package name of a tool, falling back to its config name."""
    project = (_read_pyproject(tool) or {}).get("project", {})
    return _canonical_name(str(project.get("name", tool["name"])))


def _install_source(source: str) -> str:
    """Return the expanded path of a local source, or the source itself."""
    return str(_expand(source)) if _is_local_path(source) else source


def install_args(tools: Mapping[str, str]) -> list[str]:
    """Return the ``uv pip install`` arguments for tools given as name to source.

    Args:
        tools: Tool names mapped to their configured sources. A remote source
            may name its package as a ``<package> @ <url>`` requirement.

    Returns:
        The expanded sources, then the flags that ignore ``tool.uv.sources`` for them.
    """
    return [
        *(_install_source(source) for source in tools.values()),
        *(
            arg
            for name, source in tools.items()
            for arg in (
                "--no-sources-package",
                package_name({"name": name, "source": source})
                if _is_local_path(source)
                else _canonical_name(
                    source.split(" @ ")[0] if " @ " in source else name
                ),
            )
        ),
    ]


def missing_tools() -> dict[str, str]:
    """Return the configured tools, as name to source, that this Python has not installed."""
    installed = {
        re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower()
        for dist in metadata.distributions()
    }
    return {
        str(tool["name"]): str(tool["source"])
        for tool in read_config().get("tools", [])
        if package_name(tool) not in installed
    }


def local_source_path(source: str) -> Path | None:
    """Return the expanded path of a local source, or None if the source is remote."""
    return _expand(source) if _is_local_path(source) else None


def source_state(source: str) -> str:
    """Return a digest of a local source's checkout with its prompts, or an empty string if remote."""
    if not _is_local_path(source):
        return ""
    return _checkout_state(_expand(source), include_prompts=True) or "unreadable"


def _install_pins(tools: list[dict[str, Any]]) -> dict[str, str]:
    """Return the ref each remote tool installs at: its configured ref, else its latest release tag.

    Tools without a ref and without release tags install the remote's HEAD, and
    are left out. So are local tools and sources that already name a ref.

    Args:
        tools: The configured tools.

    Returns:
        Tool names mapped to the ref to pin their install source to.
    """
    pins: dict[str, str] = {}
    for tool in tools:
        git_url = _extract_git_url(str(tool.get("source", "")))
        if not git_url or "@" in urlparse(git_url).path:
            continue
        if ref := tool.get("ref"):
            pins[str(tool["name"])] = str(ref)
            continue
        try:
            release = _latest_release_tag(git_url)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            print(f"[{tool['name']}] Could not list release tags.", file=sys.stderr)
            raise ExitReason("tool_release_lookup_failed") from None
        if release:
            pins[str(tool["name"])] = release[0]
    return pins


def _pins_drifted(pins: Mapping[str, str]) -> bool:
    """Check if any pinned tool is installed at a different ref."""
    from .cli import _get_installed_revision

    return any(_get_installed_revision(name) != ref for name, ref in pins.items())


def _git_dependencies(tools: list[dict[str, Any]]) -> list[str]:
    """Return the canonical names of the git-sourced dependencies the tools declare."""
    return sorted(
        {
            re.sub(r"[-_.]+", "-", dependency).lower()
            for tool in tools
            for dependency, source in (_read_pyproject(tool) or {})
            .get("tool", {})
            .get("uv", {})
            .get("sources", {})
            .items()
            if isinstance(source, dict) and "git" in source
        }
    )


def _build_upgrade_cmd(
    name: str,
    member_names: list[str],
    changed_local: set[str],
    git_dependencies: list[str],
) -> list[str]:
    """Build an upgrade command that reinstalls changed local packages and git dependencies."""
    configured = [name, *member_names]
    reinstalled = [
        *(package for package in configured if package in changed_local),
        *(package for package in git_dependencies if package not in configured),
    ]
    cmd = ["uv", "tool", "upgrade", name]
    for package in reinstalled:
        cmd.extend(["--reinstall-package", package])
    return cmd


def _script_names(tool: dict[str, Any]) -> list[str]:
    """Return the script names a tool declares in its pyproject.toml."""
    data = _read_pyproject(tool)
    if data is None:
        return []
    return list(data.get("project", {}).get("scripts", {}))


def _uv_tools_dir() -> Path:
    """Return the directory holding one uv tool env per installed tool."""
    return _query_uv_tools_dir() or _default_uv_tools_dir()


def _query_uv_tools_dir() -> Path | None:
    """Return the path printed by `uv tool dir`, or None if uv cannot report it."""
    try:
        result = subprocess.run(
            ["uv", "tool", "dir"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(result.stdout.strip()) if result.stdout.strip() else None


def _default_uv_tools_dir() -> Path:
    """Return uv's tool directory as resolved from the environment."""
    if tool_dir := os.environ.get("UV_TOOL_DIR"):
        return Path(tool_dir)
    if data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(data_home) / "uv" / "tools"
    return Path.home() / ".local" / "share" / "uv" / "tools"


def _has_drifted(env: SharedEnv) -> bool:
    """Check if the installed env lacks any expected member or script.

    Args:
        env: The shared env and what it must contain.

    Returns:
        True if the receipt is missing, a member is not in its requirements, or
        a script is not in its entrypoints.
    """
    receipt = _uv_tools_dir() / env.name / "uv-receipt.toml"
    if not receipt.exists():
        return True
    tool = tomllib.loads(receipt.read_text(encoding="utf-8")).get("tool", {})
    requirements = {str(r["name"]) for r in tool.get("requirements", [])}
    entrypoints = {str(e["name"]) for e in tool.get("entrypoints", [])}
    return not requirements.issuperset(env.members) or not entrypoints.issuperset(
        env.scripts
    )


def _startup_problem(env: SharedEnv) -> str | None:
    """Return why the installed env cannot start llm-prompts, or None if it can."""
    if _OWN_PACKAGE not in (env.name, *env.members):
        return None
    python = _uv_tools_dir() / env.name / "bin" / "python"
    try:
        result = subprocess.run(
            [str(python), "-c", _STARTUP_CHECK],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        return str(error)
    if result.returncode == 0:
        return None
    return (result.stderr.strip().splitlines() or [f"exit {result.returncode}"])[-1]


def _repair_unstartable(env: SharedEnv) -> bool:
    """Refresh every dependency of an env that cannot start, exiting if it still cannot.

    Args:
        env: The shared env just upgraded.

    Returns:
        True if the env failed to start and the refresh repaired it.
    """
    problem = _startup_problem(env)
    if problem is None:
        return False
    print(f"[{env.name}] Upgraded env cannot start ({problem}), refreshing it...")
    subprocess.run(
        ["uv", "tool", "upgrade", env.name, "--reinstall"],
        check=False,
        capture_output=True,
        text=True,
    )
    problem = _startup_problem(env)
    if problem is not None:
        print(
            f"[{env.name}] Still cannot start: {problem}\n"
            "A configured tool source may be out of date. "
            "Update every source checkout, then rerun `llm-prompts update`.",
            file=sys.stderr,
        )
        raise ExitReason("tool_unstartable")
    return True


def read_config() -> dict[str, Any]:
    """Return the parsed config file, or an empty dict when it does not exist."""
    if not config_path().exists():
        return {}
    try:
        config: dict[str, Any] = tomllib.loads(
            config_path().read_text(encoding="utf-8")
        )
    except tomllib.TOMLDecodeError as error:
        raise ExitReason(
            "config_invalid", f"{config_path()} is not valid TOML: {error}"
        ) from None
    return config


def _load_config() -> list[dict[str, Any]]:
    """Load and return the tools list from config."""
    if not config_path().exists():
        print(
            f"Config not found at {config_path()}\n"
            f"Run `llm-prompts setup --init` to create one.",
            file=sys.stderr,
        )
        raise ExitReason("config_missing")
    config = read_config()
    tools = config.get("tools", [])
    if not isinstance(tools, list) or not tools:
        print("Config must contain at least one [[tools]] entry.", file=sys.stderr)
        raise ExitReason("config_no_tools")
    return tools


def _validate_paths(tools: list[dict[str, Any]]) -> list[str]:
    """Validate that all local source paths exist. Returns list of errors."""
    errors: list[str] = []
    for tool in tools:
        source = str(tool.get("source", ""))
        if _is_local_path(source):
            if not _expand(source).is_dir():
                errors.append(f"[{tool.get('name')}] Path does not exist: {source}")
        elif _extract_git_url(source) is None:
            errors.append(
                f"[{tool.get('name')}] Source must be a local path or git URL "
                f"(PyPI sources are not currently supported): {source}"
            )
    return errors


def init_config() -> None:
    """Create a starter config file."""
    if config_path().exists():
        print(f"Config already exists at {config_path()}", file=sys.stderr)
        raise ExitReason("config_exists")
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(_DEFAULT_CONFIG, encoding="utf-8")
    print(f"Created {config_path()}")
    print("Edit it to add your tools and overlay paths, then run `llm-prompts setup`.")


def _run_install(env: SharedEnv) -> None:
    """Run the shared env's install command, exiting on failure."""
    result = subprocess.run(
        env.install_cmd, check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(result.stderr, end="")
        print(f"\nFailed: {env.name}", file=sys.stderr)
        raise ExitReason("tool_install_failed")


def _remove_member_envs(env: SharedEnv, *, dry_run: bool) -> bool:
    """Uninstall the standalone uv tool envs that members had before sharing one.

    Args:
        env: The shared env whose members' own envs are removed.
        dry_run: Print what would be removed without running it.

    Returns:
        True if any env was removed.
    """
    removed = False
    for member in env.members:
        if not (_uv_tools_dir() / member).is_dir():
            continue
        command = ["uv", "tool", "uninstall", member]
        if dry_run:
            print(f"[{member}] {' '.join(command)}")
            continue
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr, end="")
        else:
            print(f"[{member}] removed old tool env")
            removed = True
    return removed


def run_setup(
    tool_filter: str | None = None,
    *,
    dry_run: bool = False,
    force_reinstall: set[str] | None = None,
) -> bool:
    """Install all configured tools into one shared uv tool env.

    Args:
        tool_filter: Reinstall the whole env from scratch, if a configured tool
            with this name is given.
        dry_run: Print commands without running them.
        force_reinstall: Names of tools whose change must skip the upgrade path
            and run a full reinstall.

    Returns:
        True if any packages were upgraded or installed.
    """
    force_reinstall = force_reinstall or set()
    tools = _load_config()
    errors = _validate_paths(tools)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        raise ExitReason("invalid_tool_paths")

    _require_uv()
    if tool_filter:
        if tool_filter not in {str(tool["name"]) for tool in tools}:
            print(f"No tool named '{tool_filter}' in config.", file=sys.stderr)
            raise ExitReason("tool_not_configured")
        force_reinstall = {str(tools[0]["name"])}
    package_names = {str(tool["name"]): package_name(tool) for tool in tools}
    force_reinstall = {package_names.get(n, n) for n in force_reinstall}

    changed_local = detect_changed_local_tools(tools)
    pins = _install_pins(tools)
    env = _build_commands(tools, changed_local, pins)
    name = env.name

    changed = False
    needs_install = (
        name in force_reinstall
        or any(member in force_reinstall for member in env.members)
        or _pins_drifted(pins)
    )
    if not needs_install:
        print(f"\n[{name}] {' '.join(env.upgrade_cmd)}")
        if dry_run:
            print(f"[{name}] (fallback) {' '.join(env.install_cmd)}")
            return False
        result = subprocess.run(
            env.upgrade_cmd, check=False, capture_output=True, text=True
        )
        if result.returncode == 0:
            if changed_local or "Nothing to upgrade" not in result.stderr:
                print(result.stdout, end="")
                changed = True
            needs_install = _has_drifted(env)
            if needs_install:
                print(f"[{name}] Missing members or scripts, running full install...")
        else:
            print(result.stdout, end="")
            print(f"[{name}] Upgrade failed, falling back to full install...")
            needs_install = True

    if needs_install:
        print(f"\n[{name}] {' '.join(env.install_cmd)}")
        if not dry_run:
            _run_install(env)
            changed = True

    if _remove_member_envs(env, dry_run=dry_run):
        _run_install(env)

    if not dry_run:
        changed = _repair_unstartable(env) or changed
        print("\nAll tools installed successfully.")
        write_pyproject_stamp()
        write_checkout_stamp(tools)
    return changed
