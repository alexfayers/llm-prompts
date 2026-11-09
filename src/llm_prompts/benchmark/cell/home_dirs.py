"""Home folders that overlays declare for cell homes."""

from __future__ import annotations

import functools
import json
import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from llm_prompts.benchmark.paths import live_home
from llm_prompts.install import _discover_overlay_paths

HOME_DIRS_FILENAME = "benchmark_home.json"
KINDS = ("link", "empty", "copy")


@dataclass(frozen=True)
class HomeDir:
    link: tuple[str, ...] = ()
    empty: tuple[str, ...] = ()
    copy: tuple[str, ...] = ()


def _is_plain_name(name: object) -> bool:
    return (
        isinstance(name, str)
        and name not in ("", ".", "..")
        and Path(name).name == name
    )


def _parse_home_dir(name: str, spec: object) -> HomeDir | str:
    if not _is_plain_name(name):
        return f"folder name must be one plain path part, got {name!r}"
    if not isinstance(spec, dict):
        return "must map to an object"
    lists: dict[str, tuple[str, ...]] = {}
    for kind in KINDS:
        names = spec.get(kind, [])
        if not isinstance(names, list) or not all(map(_is_plain_name, names)):
            return f"'{kind}' must list single plain path parts"
        lists[kind] = tuple(names)
    listed = [sub for kind in KINDS for sub in lists[kind]]
    if repeated := sorted({sub for sub in listed if listed.count(sub) > 1}):
        return f"{repeated} listed under more than one kind"
    return HomeDir(**lists)


def _declared_home_dirs(root: Path) -> dict[str, HomeDir]:
    path = root / HOME_DIRS_FILENAME
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("top level must be an object")
    except (OSError, ValueError, TypeError) as e:
        print(f"benchmark: {path}: could not parse JSON: {e}", file=sys.stderr)
        return {}
    declared: dict[str, HomeDir] = {}
    for name, spec in raw.items():
        parsed = _parse_home_dir(name, spec)
        if isinstance(parsed, str):
            print(f"benchmark: {path}: '{name}': {parsed}", file=sys.stderr)
            continue
        declared[name] = parsed
    return declared


@functools.cache
def declared_home_dirs() -> dict[str, HomeDir]:
    """Return the home directories that overlays declare, merged by name."""
    merged: dict[str, HomeDir] = {}
    for root in _discover_overlay_paths(quiet=True):
        for name, spec in _declared_home_dirs(root).items():
            known = merged.get(name, HomeDir())
            merged[name] = HomeDir(
                tuple(sorted({*known.link, *spec.link})),
                tuple(sorted({*known.empty, *spec.empty})),
                tuple(sorted({*known.copy, *spec.copy})),
            )
    return merged


def link_home_dirs(home: Path, declared: Mapping[str, HomeDir]) -> tuple[Path, ...]:
    """Recreate the declared live home directories under ``home`` and return the links into the live home."""
    links: list[Path] = []
    for name, spec in declared.items():
        live = live_home() / name
        if not live.is_dir() or os.path.lexists(home / name):
            continue
        (home / name).mkdir()
        for sub in spec.link:
            if os.path.lexists(live / sub):
                (home / name / sub).symlink_to(live / sub)
                links.append(home / name / sub)
        for sub in spec.empty:
            (home / name / sub).mkdir()
        for sub in spec.copy:
            if (live / sub).is_dir():
                shutil.copytree(
                    live / sub, home / name / sub, ignore_dangling_symlinks=True
                )
            elif (live / sub).is_file():
                shutil.copy2(live / sub, home / name / sub)
    return tuple(links)
