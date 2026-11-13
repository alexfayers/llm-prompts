"""Build the cached llm-prompts variants a benchmark compares."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import replace
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Literal

from llm_prompts import setup
from llm_prompts.benchmark import paths
from llm_prompts.benchmark.agents import AGENTS
from llm_prompts.benchmark.agents.adapter import VariantBuildError
from llm_prompts.benchmark.cell.audit import audit, cell_paths
from llm_prompts.benchmark.cell.env import isolated_env
from llm_prompts.benchmark.types import WORKTREE, Agent, Variant
from llm_prompts.install import prompts_dir

SRC_COMPLETE = ".src-complete"
BUILD_COMPLETE = ".complete"
REF_MARKER = ".ref"
PLACEHOLDER_MEMORY_URL = "http://127.0.0.1:1/mcp"
REQUIRED_TOOLS = ("cline-hooks", "mcp-memory")
CORE_TOOLS = ("llm-prompts", *REQUIRED_TOOLS)
VENV_TOOLS = ("pytest",)
PROMPTS = Path("src/llm_prompts/prompts")
ORIGIN_REFS = ("origin/HEAD", "origin/main")
SCP_URL = re.compile(r"^(?P<user>[^@/:]+@)?(?P<host>[^:/]+):(?P<path>[^/].*)$")
PINNED_SOURCE = re.compile(r"@[0-9a-f]{40}$")
VENV_UNUSED_DIRS = frozenset({"__pycache__", "prompts"})
TEMPLATE_UNUSED_DIRS = frozenset({"__pycache__", ".npm"})
UNUSED_FILES = frozenset({"installed.json"})


NOT_IN_CHECKOUT = "Run llm-prompts benchmark from inside an llm-prompts checkout."


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _run(ref: str, argv: list[str], env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, check=False, env=env
        )
    except OSError as error:
        raise VariantBuildError(ref, f"{' '.join(argv)} failed: {error}") from error
    if result.returncode != 0:
        raise VariantBuildError(
            ref, f"{' '.join(argv)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def _fresh_src(key: str) -> Path | None:
    src = paths.variant_dir(key) / "src"
    if (src / SRC_COMPLETE).exists():
        return None
    shutil.rmtree(src, ignore_errors=True)
    src.mkdir(parents=True)
    return src


def _worktree_files(ref: str, repo: Path) -> list[str]:
    listing = _run(
        ref,
        [
            "git",
            "-C",
            str(repo),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
    )
    return sorted(
        name for name in listing.split("\0") if name and (repo / name).is_file()
    )


def _source_worktree(repo: Path) -> tuple[str, Path]:
    files = _worktree_files(WORKTREE, repo)
    digest = hashlib.sha256()
    for name in files:
        digest.update(name.encode() + b"\0" + (repo / name).read_bytes() + b"\0")
    key = f"worktree-{digest.hexdigest()[:12]}"
    src = _fresh_src(key)
    if src is None:
        return key, paths.variant_dir(key) / "src"
    for name in files:
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / name, src / name)
    (src / SRC_COMPLETE).touch()
    return key, src


def source(ref: str, repo: Path) -> tuple[str, Path]:
    """Return the cache key and a source tree for ``ref``."""
    if ref == WORKTREE:
        return _source_worktree(repo)
    try:
        key = _run(
            ref, ["git", "-C", str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}"]
        ).strip()
    except VariantBuildError as error:
        raise VariantBuildError(ref, "ref not found") from error
    src = _fresh_src(key)
    if src is None:
        return key, paths.variant_dir(key) / "src"
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "src.tar"
        _run(ref, ["git", "-C", str(repo), "archive", "-o", str(archive), key])
        _run(ref, ["tar", "-x", "-f", str(archive), "-C", str(src)])
    (src / SRC_COMPLETE).touch()
    return key, src


def _with_tool_sources(
    config: Mapping[str, Any], tool_sources: Mapping[str, str]
) -> dict[str, Any]:
    tools = [
        {**tool, "source": tool_sources.get(tool["name"], tool["source"])}
        for tool in config.get("tools", [])
    ]
    return {**config, "tools": tools}


def _pip_git_url(url: str) -> str:
    if "://" in url:
        return f"git+{url}"
    if match := SCP_URL.match(url):
        return f"git+ssh://{match['user'] or ''}{match['host']}/{match['path']}"
    raise ValueError(f"unsupported remote URL: {url}")


def _origin_source(name: str, checkout: Path) -> str:
    """Return the pip source of the checkout's remote default branch tip."""
    for origin_ref in ORIGIN_REFS:
        try:
            sha = _run(
                name,
                [
                    "git",
                    "-C",
                    str(checkout),
                    "rev-parse",
                    "--verify",
                    f"{origin_ref}^{{commit}}",
                ],
            ).strip()
        except VariantBuildError:
            continue
        url = _run(
            name, ["git", "-C", str(checkout), "remote", "get-url", "origin"]
        ).strip()
        try:
            return f"{_pip_git_url(url)}@{sha}"
        except ValueError as error:
            raise VariantBuildError(name, str(error)) from error
    raise VariantBuildError(
        name,
        f"{checkout} has no origin/main. Pin it with --a-tool {name}=<source>@<sha>",
    )


def _with_origin_tools(
    config: Mapping[str, Any],
    overlays: Collection[str],
    ref: str,
    kept: Collection[str],
) -> dict[str, Any]:
    installed = _tool_sources(config, overlays, ref)
    tools = []
    for tool in config.get("tools", []):
        checkout = setup.local_source_path(tool["source"])
        if tool["name"] in installed and tool["name"] not in kept and checkout:
            tool = {**tool, "source": _origin_source(tool["name"], checkout)}
        tools.append(tool)
    return {**config, "tools": tools}


def _tool_sources(
    config: Mapping[str, Any], overlays: Collection[str], ref: str
) -> dict[str, str]:
    sources = {tool["name"]: tool["source"] for tool in config.get("tools", [])}
    for name in REQUIRED_TOOLS:
        if name not in sources:
            raise VariantBuildError(ref, f"{name} is not in config.toml")
    chosen = [name for name in sources if name in overlays and name not in CORE_TOOLS]
    return {name: sources[name] for name in (*REQUIRED_TOOLS, *chosen)}


def overlay_names(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the configured tools that are not core tools."""
    return tuple(
        tool["name"]
        for tool in config.get("tools", [])
        if tool["name"] not in CORE_TOOLS
    )


def provider_overlays(
    config: Mapping[str, Any], agents: Iterable[Agent]
) -> tuple[str, ...]:
    """Return the configured overlays that set up the model provider of one of ``agents``.

    An overlay is read from the prompts of its installed package, matched to the configured tool by name.
    """
    prompts = {
        _canonical(entry.dist.name): prompts_dir(entry.value)
        for entry in entry_points(group="llm_prompts")
        if entry.dist
    }
    return tuple(
        name
        for name in overlay_names(config)
        if (found := prompts.get(_canonical(name)))
        and any(AGENTS[agent].sets_up_provider(found) for agent in agents)
    )


def _pin_summary(config: Mapping[str, Any], overlays: Collection[str], ref: str) -> str:
    pins = [
        f"{name}@{pin.group()[1:9]}"
        for name, source in _tool_sources(config, overlays, ref).items()
        if (pin := PINNED_SOURCE.search(source))
    ]
    return f" ({', '.join(pins)})" if pins else ""


def _cache_suffix(
    config: Mapping[str, Any], overlays: Collection[str], ref: str
) -> str:
    digest = hashlib.sha256(sys.executable.encode())
    digest.update("\0".join(VENV_TOOLS).encode())
    for name, location in _tool_sources(config, overlays, ref).items():
        digest.update(f"{name}\0{location}\0".encode())
        digest.update(setup.source_state(location).encode())
    return f"{'overlays' if overlays else 'plain'}-{digest.hexdigest()[:8]}"


def _tree_entries(
    cache: Path, root: Path, skipped_dirs: Collection[str]
) -> Iterator[bytes]:
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in skipped_dirs and not name.endswith(".dist-info")
        )
        for name in sorted(files):
            if name in UNUSED_FILES or name.endswith(".log"):
                continue
            file = Path(directory) / name
            body = (
                os.readlink(file).encode() if file.is_symlink() else file.read_bytes()
            )
            yield str(file.relative_to(cache)).encode()
            yield body.replace(str(cache).encode(), b"<cache>")


def _content_digest(cache: Path, template: Path) -> str:
    digest = hashlib.sha256()
    for entry in (
        *_tree_entries(cache, cache / "venv" / "lib", VENV_UNUSED_DIRS),
        *_tree_entries(cache, template, TEMPLATE_UNUSED_DIRS),
    ):
        digest.update(entry + b"\0")
    return digest.hexdigest()


def _is_pinned(config: Mapping[str, Any], overlays: Collection[str], ref: str) -> bool:
    return all(
        setup.source_state(location) not in ("", "unreadable")
        or PINNED_SOURCE.search(location)
        for location in _tool_sources(config, overlays, ref).values()
    )


def venv(
    src: Path,
    venv_dir: Path,
    config: Mapping[str, Any],
    overlays: Collection[str],
    ref: str = "",
) -> Path:
    """Create a virtualenv in ``venv_dir`` holding the source and its tools."""
    tools = _tool_sources(config, overlays, ref)
    _run(ref, ["uv", "venv", str(venv_dir)])
    _run(
        ref,
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(venv_dir / "bin" / "python"),
            str(src),
            *VENV_TOOLS,
            *setup.install_args(tools),
        ],
    )
    return venv_dir


def install_tools(tools: Mapping[str, str]) -> None:
    """Install ``tools`` (name to source) into the Python running this process."""
    _run(
        "tools",
        [
            "uv",
            "pip",
            "install",
            "--python",
            sys.executable,
            *setup.install_args(tools),
        ],
    )


def template(venv_dir: Path, agent: Agent, template_dir: Path) -> Path:
    """Install the agent prompts and hooks into ``template_dir`` and return it."""
    template_dir.mkdir(parents=True, exist_ok=True)
    env = isolated_env(template_dir, venv_dir)
    name = AGENTS[agent].template_name
    bin_dir = venv_dir / "bin"
    _run(
        name,
        [
            str(bin_dir / "llm-prompts"),
            "install",
            name,
            "--root",
            str(template_dir),
            "--no-update",
        ],
        env,
    )
    _run(name, [str(bin_dir / "cline-hook"), "install", name], env)
    try:
        AGENTS[agent].point_memory(template_dir, PLACEHOLDER_MEMORY_URL)
    except (ValueError, TypeError) as error:
        raise VariantBuildError(name, str(error)) from error
    return template_dir


OVERLAY_PROBE = """
import contextlib, io, json
from llm_prompts.install import _discover_overlay_paths
with contextlib.redirect_stderr(io.StringIO()):
    found = _discover_overlay_paths()
print(json.dumps([str(path) for path in found]))
"""


def overlay_prompts(variant: Variant) -> list[Path]:
    """Return the prompts directory of every overlay installed in the variant's virtualenv."""
    output = _run(
        variant.ref, [str(variant.venv / "bin" / "python"), "-c", OVERLAY_PROBE]
    )
    return [Path(path) for path in json.loads(output)]


def prune(current: Iterable[Variant]) -> None:
    """Delete every cached build and source except the newest build of each ref and the ``current`` variants."""
    root = paths.variants_dir()
    if not root.is_dir():
        return
    kept = {variant.venv.parent for variant in current}
    newest: dict[str, Path] = {}
    for marker in sorted(root.glob(f"*/{REF_MARKER}"), key=lambda m: m.stat().st_mtime):
        newest[marker.read_text()] = marker.parent
    kept |= set(newest.values())
    kept_keys = {build.name.rsplit("-", 2)[0] for build in kept}
    for directory in root.iterdir():
        if directory not in kept and directory.name not in kept_keys:
            shutil.rmtree(directory, ignore_errors=True)


def build(
    label: Literal["a", "b"],
    ref: str,
    agents: Sequence[Agent],
    overlays: Collection[str],
    tool_sources: Mapping[str, str] | None = None,
    repo: Path | None = None,
) -> Variant:
    """Build, or reuse from cache, the variant for ``ref``.

    Both variants install the core tools and the named ``overlays``. Variant ``a`` installs every local tool at its origin default-branch commit. ``tool_sources`` replaces configured tool sources.
    """
    if repo is None:
        try:
            repo = Path(_run(ref, ["git", "rev-parse", "--show-toplevel"]).strip())
        except VariantBuildError as error:
            raise VariantBuildError(ref, NOT_IN_CHECKOUT) from error
    if not (repo / PROMPTS).is_dir():
        raise VariantBuildError(
            ref, f"{repo} is not an llm-prompts checkout. {NOT_IN_CHECKOUT}"
        )
    key, src = source(ref, repo)
    config = setup.read_config()
    overlays = tuple(dict.fromkeys((*overlays, *provider_overlays(config, agents))))
    if label == "a":
        config = _with_origin_tools(config, overlays, ref, tool_sources or {})
    config = _with_tool_sources(config, tool_sources or {})
    build_id = f"{key}-{_cache_suffix(config, overlays, ref)}"
    cache = paths.variant_dir(build_id)
    templates: dict[Agent, Path] = {
        agent: cache / "templates" / agent for agent in agents
    }
    variant = Variant(
        label,
        ref,
        key,
        src,
        cache / "venv",
        templates,
    )
    pins = _pin_summary(config, overlays, ref)
    if not (
        (cache / BUILD_COMPLETE).exists()
        and all(path.is_dir() and not cell_paths(path) for path in templates.values())
    ):
        print(f"benchmark: building {label} {ref}{pins}", file=sys.stderr)
        shutil.rmtree(cache, ignore_errors=True)
        venv(src, variant.venv, config, overlays, ref)
        for agent, template_dir in templates.items():
            template(variant.venv, agent, template_dir)
            AGENTS[agent].install_guard(template_dir)
            if hits := audit(template_dir):
                raise VariantBuildError(
                    ref, f"live path {hits[0].marker} in {hits[0].path}"
                )
            if hits := cell_paths(template_dir):
                raise VariantBuildError(
                    ref, f"cell home path {hits[0].marker} in {hits[0].path}"
                )
        (cache / BUILD_COMPLETE).touch()
        print(f"benchmark: built {label} {ref}{pins}", file=sys.stderr)
    else:
        print(f"benchmark: using cached build of {label} {ref}{pins}", file=sys.stderr)
    (cache / REF_MARKER).write_text(ref)
    if not _is_pinned(config, overlays, ref):
        return variant
    return replace(
        variant,
        build={
            agent: _content_digest(cache, template_dir)
            for agent, template_dir in templates.items()
        },
    )
