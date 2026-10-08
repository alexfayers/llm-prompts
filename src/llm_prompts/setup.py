"""Setup command for installing llm-prompts and related tools."""

from __future__ import annotations

import functools
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, NamedTuple

from .squash_subject import squash_pr_number

_CONFIG_DIR = Path.home() / ".config" / "llm-prompts"
CONFIG_PATH = _CONFIG_DIR / "config.toml"
GIT_TIMEOUT = 30

_DEFAULT_CONFIG = """\
# llm-prompts setup configuration
# Run `llm-prompts setup` to install all tools into one shared environment.

# Each [[tools]] entry is a package to install.
# `source` can be:
#   - A git URL (e.g. "git+https://github.com/user/repo.git")
#   - A local path (~/git/pkg or /abs/path) - installed from the checkout
#
# The first entry owns the environment; the others are installed alongside it.
# Each tool's commands are taken from its pyproject.toml scripts.

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


def _format_update_message(
    name: str,
    subjects: list[str] | None,
    local: str | None = None,
    remote: str | None = None,
    cap: int = 20,
) -> list[str]:
    """Build an update-availability message, listing commit messages when known.

    Args:
        name: The source name, used in the header.
        subjects: Commit messages newer than the local commit, each a subject
            optionally followed by body lines, or ``None`` when the commit list
            could not be determined.
        local: The local commit SHA, used only for the bare fallback message.
        remote: The remote commit SHA, used only for the bare fallback message.
        cap: Maximum number of commits to list before truncating.

    Returns:
        A single multi-line message listing the commits, body lines indented
        under their subject, or the bare "update available" fallback when
        ``subjects`` is empty/``None``.
    """
    if not subjects:
        if local and remote:
            return [f"[{name}] update available ({local[:8]} -> {remote[:8]})"]
        return [f"[{name}] update available"]

    lines = [f"[{name}] update available:"]
    lines.extend("- " + subject.replace("\n", "\n  ") for subject in subjects[:cap])
    if len(subjects) > cap:
        lines.append(f"... and {len(subjects) - cap} more")
    return ["\n".join(lines)]


def _remote_head(git_url: str, ref: str | None) -> str | None:
    """Return the commit SHA a remote git ref points at, via ls-remote.

    Args:
        git_url: The remote git URL to query.
        ref: The remote ref to resolve; defaults to ``HEAD``.

    Returns:
        The remote commit SHA, or ``None`` if the query fails or is empty.
    """
    result = subprocess.run(
        ["git", "ls-remote", git_url, ref or "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=GIT_TIMEOUT,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.split()[0]


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


def _remote_commit_subjects(
    git_url: str, from_sha: str, to_sha: str
) -> list[str] | None:
    """Get commit subjects between two SHAs by cloning a remote into a temp dir.

    Uses a treeless, no-checkout partial clone to fetch history cheaply. Any
    failure (git missing, clone/log error, timeout) degrades to ``None`` rather
    than raising, so the caller can fall back to a bare message.

    Args:
        git_url: The remote git URL to clone.
        from_sha: The exclusive lower-bound commit.
        to_sha: The inclusive upper-bound commit.

    Returns:
        The subject lines newest-first, or ``None`` on any failure.
    """
    if not shutil.which("git"):
        print(
            f"Warning: git not available; skipping commit subjects for {git_url}",
            file=sys.stderr,
        )
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
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
                return None
            return _commit_subjects_between(Path(tmp), from_sha, to_sha)
    except subprocess.TimeoutExpired:
        print(
            f"Warning: timed out cloning {git_url} for commit subjects",
            file=sys.stderr,
        )
        return None
    except Exception:
        return None


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
            result = subprocess.run(
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
    if not CONFIG_PATH.exists():
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


def _checkout_state(repo: Path) -> str | None:
    """Return a digest of a checkout's files, status and uncommitted diff outside prompts.

    Args:
        repo: The checkout directory.

    Returns:
        The hex digest, or ``None`` if git fails.
    """
    digest = hashlib.sha256()
    for args in (["ls-files", "-s"], ["status", "--porcelain"], ["diff", "HEAD"]):
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), *args, "--", _NOT_PROMPTS],
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
        sys.exit(1)


class SharedEnv(NamedTuple):
    """The commands and expected contents of the one uv tool env holding every tool."""

    name: str
    install_cmd: list[str]
    upgrade_cmd: list[str]
    members: list[str]
    scripts: list[str]


def _build_commands(tools: list[dict[str, Any]], changed_local: set[str]) -> SharedEnv:
    """Build the commands for the uv tool env owned by the first tool.

    Args:
        tools: The configured tools; the first owns the env and the rest are
            members installed alongside it.
        changed_local: Names of local tools whose upgrade must rebuild them.

    Returns:
        The install and upgrade commands, the member names and the script names
        the env must expose.
    """
    owner, *members = tools
    name = str(owner["name"])
    member_names = [str(member["name"]) for member in members]
    scripts = {str(tool["name"]): _script_names(tool) for tool in tools}
    return SharedEnv(
        name,
        _build_install_cmd(owner, members, [n for n in member_names if scripts[n]]),
        _build_upgrade_cmd(name, member_names, changed_local),
        member_names,
        [script for names in scripts.values() for script in names],
    )


def _build_install_cmd(
    owner: dict[str, Any], members: list[dict[str, Any]], executable_members: list[str]
) -> list[str]:
    """Build a full install command."""
    cmd = ["uv", "tool", "install", _install_source(str(owner["source"]))]
    for member in members:
        cmd.extend(["--with", _install_source(str(member["source"]))])
    if executable_members:
        cmd.extend(["--with-executables-from", ",".join(executable_members)])
    for package in [owner, *members]:
        if _is_local_path(str(package["source"])):
            cmd.extend(["--no-sources-package", str(package["name"])])
    cmd.extend(["--reinstall", "--force"])
    return cmd


def _install_source(source: str) -> str:
    """Return the expanded path of a local source, or the source itself."""
    return str(_expand(source)) if _is_local_path(source) else source


def _build_upgrade_cmd(
    name: str, member_names: list[str], changed_local: set[str]
) -> list[str]:
    """Build a targeted upgrade command that reinstalls only changed local packages."""
    cmd = ["uv", "tool", "upgrade", name]
    for package_name in [name, *member_names]:
        if package_name in changed_local:
            cmd.extend(["--reinstall-package", package_name])
    return cmd


def _script_names(tool: dict[str, Any]) -> list[str]:
    """Return the script names a tool declares in its pyproject.toml."""
    data = _read_pyproject(tool)
    if data is None:
        return []
    return list(data.get("project", {}).get("scripts", {}))


def _uv_tools_dir() -> Path:
    """Return the directory holding one uv tool env per installed tool."""
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


def _load_config() -> list[dict[str, Any]]:
    """Load and return the tools list from config."""
    if not CONFIG_PATH.exists():
        print(
            f"Config not found at {CONFIG_PATH}\n"
            f"Run `llm-prompts setup --init` to create one.",
            file=sys.stderr,
        )
        sys.exit(1)
    config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    tools = config.get("tools", [])
    if not isinstance(tools, list) or not tools:
        print("Config must contain at least one [[tools]] entry.", file=sys.stderr)
        sys.exit(1)
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
    if CONFIG_PATH.exists():
        print(f"Config already exists at {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_DEFAULT_CONFIG, encoding="utf-8")
    print(f"Created {CONFIG_PATH}")
    print("Edit it to add your tools and overlay paths, then run `llm-prompts setup`.")


def _run_install(env: SharedEnv) -> None:
    """Run the shared env's install command, exiting on failure."""
    result = subprocess.run(
        env.install_cmd, check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(result.stderr, end="")
        print(f"\nFailed: {env.name}", file=sys.stderr)
        sys.exit(1)


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
        sys.exit(1)

    _require_uv()
    if tool_filter:
        if tool_filter not in {str(tool["name"]) for tool in tools}:
            print(f"No tool named '{tool_filter}' in config.", file=sys.stderr)
            sys.exit(1)
        force_reinstall = {str(tools[0]["name"])}

    env = _build_commands(tools, detect_changed_local_tools(tools))
    name = env.name

    changed = False
    needs_install = name in force_reinstall or any(
        member in force_reinstall for member in env.members
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
            if "Nothing to upgrade" not in result.stdout:
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
        print("\nAll tools installed successfully.")
        write_pyproject_stamp()
        write_checkout_stamp(tools)
    return changed
