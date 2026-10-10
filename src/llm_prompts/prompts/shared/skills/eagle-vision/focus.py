"""Manage an eagle-vision plan directory."""

import argparse
import fcntl
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, redirect_stdout, suppress
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import combinations
from pathlib import Path
from typing import Any, NoReturn, TypedDict

SECTION_ORDER = [
    "Goal",
    "Approach",
    "Components",
    "Interfaces",
    "Graph",
    "Scope",
    "Nodes",
    "Constraints",
    "Checks",
    "Collect",
    "Later",
]
FRONT_MATTER_RE = re.compile(r"\A---\n((?:.*\n)*?)---\n")
STAGES: dict[str, str] = {
    "todo": "",
    "building": "building",
    "testing": "testing",
    "done": "done",
}
STAGE_STYLES: dict[str, str] = {
    "done": "fill:#9f9,stroke:#393",
    "testing": "fill:#ff9,stroke:#993",
    "building": "fill:#9cf,stroke:#369",
}
LINK_KEYS = ("depends", "scope", "inputs", "outputs", "deletes")
VIEW_PAGE = Path(__file__).resolve().parent / "view.html"
VIEW_SECTIONS = ("In", "Out", "Accept")


class FocusError(Exception):
    """Command error."""

    def __init__(self, message: str = "", problems: list[str] | None = None) -> None:
        """Store message and problems."""
        super().__init__(message)
        self.problems = problems


class Node(TypedDict):
    """Node record."""

    depends: list[str]
    scope: list[str]
    inputs: list[str]
    outputs: list[str]
    deletes: list[str]
    stage: str


Nodes = dict[str, Node]
Links = dict[str, list[str]]


def slugify(name: str) -> str:
    """Slug a node name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def node_path(base: Path, node_id: str, stage: str) -> Path:
    """Path to a node's file for a stage."""
    return base / "nodes" / STAGES[stage] / f"{node_id}.md"


def plan_path(base: Path) -> Path:
    """Path to PLAN.md."""
    return base / "PLAN.md"


def links_summary(links: Links) -> str:
    """Format a links summary."""
    lines = link_lines(links)
    return f" ({'; '.join(lines)})" if lines else ""


def link_lines(links: Links) -> list[str]:
    """Format non-empty link front-matter lines."""
    return [f"{key}: {', '.join(links[key])}" for key in LINK_KEYS if links.get(key)]


def render_node_file(links: Links, body: str) -> str:
    """Render a node file."""
    return "---\n" + "".join(f"{ln}\n" for ln in link_lines(links)) + f"---\n{body}"


def match_front_matter(text: str) -> re.Match[str]:
    """Match a node file's front matter, or raise."""
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise FocusError("malformed node file: missing front matter")
    return match


def parse_node_file(text: str) -> tuple[Links, str]:
    """Parse a node file."""
    match = match_front_matter(text)
    front: Links = {key: [] for key in LINK_KEYS}
    for fm_line in match.group(1).splitlines():
        key, _, value = fm_line.partition(":")
        key = key.strip()
        if key in front:
            front[key] = [v.strip() for v in value.split(",") if v.strip()]
    return front, text[match.end() :]


def replace_front_lines(text: str, keys: set[str], new_lines: list[str]) -> str:
    """Replace the front-matter lines for keys."""
    match = match_front_matter(text)
    kept = [
        ln
        for ln in match.group(1).splitlines()
        if ln.partition(":")[0].strip() not in keys
    ]
    return (
        text[: match.start(1)]
        + "".join(f"{ln}\n" for ln in [*kept, *new_lines])
        + text[match.end(1) :]
    )


def update_failed_line(text: str, reason: str | None) -> str:
    """Add, update, or remove the failed front-matter line."""
    return replace_front_lines(
        text, {"failed"}, [] if reason is None else [f"failed: {reason}"]
    )


def set_links(text: str, links: Links) -> str:
    """Replace the link front-matter lines."""
    return replace_front_lines(text, set(LINK_KEYS), link_lines(links))


def find_node_path(base: Path, node_id: str) -> Path:
    """Find a node's file, in a sibling plan dir for '<dir>/<node>'."""
    plan_name, _, name = node_id.rpartition("/")
    plan_dir = base.resolve().parent / plan_name if plan_name else base
    for stage in STAGES:
        path = node_path(plan_dir, name, stage)
        if path.exists():
            return path
    raise FocusError(f"unknown node '{node_id}'")


def load_nodes(base: Path) -> Nodes:
    """Load all nodes."""
    nodes: Nodes = {}
    for stage, suffix in STAGES.items():
        folder = base / "nodes" / suffix
        for path in sorted(folder.glob("*.md")):
            front, _ = parse_node_file(path.read_text())
            nodes[path.stem] = make_node(front, stage)
    return nodes


def sibling_dependency(dep: str, sibling_name: str, plan_name: str) -> str:
    """A sibling node's dependency, as seen from the plan dir named plan_name."""
    if "/" not in dep:
        return f"{sibling_name}/{dep}"
    dir_name, _, node_id = dep.partition("/")
    return node_id if dir_name == plan_name else dep


def load_siblings(base: Path) -> Nodes:
    """Load the nodes of sibling plan dirs, keyed '<dir>/<node>'."""
    plan_dir = base.resolve()
    siblings: Nodes = {}
    for sibling in sorted(plan_dir.parent.iterdir()):
        if sibling != plan_dir and plan_path(sibling).is_file():
            for node_id, node in load_nodes(sibling).items():
                node["depends"] = [
                    sibling_dependency(dep, sibling.name, plan_dir.name)
                    for dep in node["depends"]
                ]
                siblings[f"{sibling.name}/{node_id}"] = node
    return siblings


def with_siblings(base: Path, nodes: Nodes) -> Nodes:
    """The nodes together with those of sibling plan dirs."""
    return {**load_siblings(base), **nodes}


def find_cycle(nodes: Nodes, all_nodes: Nodes) -> list[str] | None:
    """Find a dependency cycle reachable from nodes."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(all_nodes, WHITE)
    path: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        if node_id not in color or color[node_id] == BLACK:
            return None
        if color[node_id] == GRAY:
            return [*path[path.index(node_id) :], node_id]
        color[node_id] = GRAY
        path.append(node_id)
        for dep in all_nodes[node_id]["depends"]:
            cycle = visit(dep)
            if cycle:
                return cycle
        path.pop()
        color[node_id] = BLACK
        return None

    for node_id in nodes:
        cycle = visit(node_id)
        if cycle:
            return cycle
    return None


def scope_overlaps(a: str, b: str) -> bool:
    """Whether two scope entries overlap."""
    parts_a, parts_b = a.rstrip("/").split("/"), b.rstrip("/").split("/")
    shorter, longer = sorted((parts_a, parts_b), key=len)
    return longer[: len(shorter)] == shorter


def scope_file(entry: str) -> str:
    """A scope entry up to the first path segment that names a file."""
    parts = entry.rstrip("/").split("/")
    return "/".join(
        next(
            (parts[: i + 1] for i, p in enumerate(parts) if "." in p.lstrip(".")), parts
        )
    )


def shares_file(a: Node, b: Node) -> bool:
    """Whether two nodes have scope in the same file."""
    return any(
        scope_overlaps(scope_file(x), scope_file(y))
        for x in a["scope"]
        for y in b["scope"]
    )


def validate_or_raise(nodes: Nodes, all_nodes: Nodes) -> None:
    """Validate the graph."""
    problems = [
        f"{node_id}: unknown dependency '{dep}'"
        for node_id, node in nodes.items()
        for dep in node["depends"]
        if dep not in all_nodes
    ]
    cycle = find_cycle(nodes, all_nodes)
    if cycle:
        problems.append(f"dependency cycle: {' -> '.join(cycle)}")

    for (id_a, node_a), (id_b, node_b) in combinations(nodes.items(), 2):
        for entry_a in node_a["scope"]:
            for entry_b in node_b["scope"]:
                if scope_overlaps(entry_a, entry_b):
                    problems.append(
                        f"scope overlap: {id_a} '{entry_a}' and {id_b} '{entry_b}'"
                    )
    if problems:
        raise FocusError(problems=problems)


def compute_waves(nodes: Nodes, all_nodes: Nodes) -> dict[str, int]:
    """Compute each node's wave number, spreading same-file nodes over spare waves."""
    earliest: dict[str, int] = {}

    def earliest_wave(node_id: str) -> int:
        if node_id not in earliest:
            earliest[node_id] = 1 + max(
                (
                    earliest_wave(dep)
                    for dep in all_nodes[node_id]["depends"]
                    if dep in all_nodes
                ),
                default=0,
            )
        return earliest[node_id]

    for node_id in nodes:
        earliest_wave(node_id)
    last = max((earliest[node_id] for node_id in nodes), default=0)
    latest: dict[str, int] = {}

    def latest_wave(node_id: str) -> int:
        if node_id not in latest:
            latest[node_id] = min(
                (
                    latest_wave(other) - 1
                    for other, node in nodes.items()
                    if node_id in node["depends"]
                ),
                default=last,
            )
        return latest[node_id]

    waves: dict[str, int] = {}
    for node_id in sorted(nodes, key=lambda n: (earliest[n], n)):
        start = 1 + max(
            (
                waves.get(dep, earliest[dep])
                for dep in nodes[node_id]["depends"]
                if dep in all_nodes
            ),
            default=0,
        )
        plan_dir = node_id.rpartition("/")[0]
        clashing = {
            waves[other]
            for other in waves
            if other.rpartition("/")[0] == plan_dir
            and shares_file(nodes[node_id], nodes[other])
        }
        waves[node_id] = next(
            (w for w in range(start, latest_wave(node_id) + 1) if w not in clashing),
            start,
        )
    return waves


def is_done(all_nodes: Nodes, node_id: str) -> bool:
    """Whether a node exists and is done."""
    return node_id in all_nodes and all_nodes[node_id]["stage"] == "done"


def render_waves(nodes: Nodes, all_nodes: Nodes) -> str:
    """Render nodes grouped by wave."""
    waves = compute_waves(nodes, all_nodes)
    by_wave: dict[int, list[str]] = {}
    for node_id in sorted(nodes):
        by_wave.setdefault(waves[node_id], []).append(node_id)
    blocks = []
    for wave_num in sorted(by_wave):
        lines = [f"### Wave {wave_num}"]
        for node_id in by_wave[wave_num]:
            node = nodes[node_id]
            if node["stage"] == "done":
                lines.append(f"- [x] {node_id}")
            elif node["stage"] in ("building", "testing"):
                lines.append(f"- [ ] {node_id} ({node['stage']})")
            else:
                ready = all(is_done(all_nodes, d) for d in node["depends"])
                lines.append(f"- [ ] {node_id}" + (" (ready)" if ready else ""))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def mermaid_id(node_id: str) -> str:
    """Mermaid-safe node id (hyphens can trigger reserved-word parsing, e.g. 'end')."""
    return re.sub(r"[-/]", "_", node_id)


def mermaid_node(node_id: str) -> str:
    """Mermaid node declaration: a safe id labelled with the original name."""
    return f'{mermaid_id(node_id)}["{node_id}"]'


def plan_sections(nodes: Nodes, all_nodes: Nodes) -> dict[str, str]:
    """Render generated sections."""
    referenced = {dep for node in nodes.values() for dep in node["depends"]}
    graph = ["```mermaid", "graph LR"]
    for node_id in sorted(nodes):
        depends = nodes[node_id]["depends"]
        if depends:
            graph.extend(
                f"{mermaid_node(dep)} --> {mermaid_node(node_id)}"
                for dep in sorted(depends)
            )
        elif node_id not in referenced:
            graph.append(mermaid_node(node_id))
    for stage, style in STAGE_STYLES.items():
        stage_ids = sorted(
            node_id for node_id in nodes if nodes[node_id]["stage"] == stage
        )
        if stage_ids:
            graph.append(f"classDef {stage} {style}")
            graph.extend(f"{mermaid_id(node_id)}:::{stage}" for node_id in stage_ids)
    graph.append("```")
    return {
        "Graph": "\n".join(graph),
        "Scope": "\n".join(
            f"- {node_id}: {', '.join(nodes[node_id]['scope'])}"
            for node_id in sorted(nodes)
            if nodes[node_id]["scope"]
        ),
        "Nodes": render_waves(nodes, all_nodes),
    }


def parse_sections(text: str) -> dict[str, str]:
    """Parse PLAN.md sections."""
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buffer).strip("\n")
            current = line[3:].strip()
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip("\n")
    return sections


def parse_checks(body: str) -> list[str]:
    """Parse a Checks section body into shell commands."""
    return [
        line[2:].strip().strip("`")
        for line in body.splitlines()
        if line.startswith("- ")
    ]


def node_test_command(text: str) -> str | None:
    """Read a node's plan-time test command from front matter, or None."""
    match = match_front_matter(text)
    for fm_line in match.group(1).splitlines():
        key, _, value = fm_line.partition(":")
        if key.strip() == "test":
            return value.strip()
    return None


def render_sections(sections: dict[str, str]) -> str:
    """Render present sections in SECTION_ORDER, joined by blank lines."""
    blocks = [
        f"## {name}" + (f"\n\n{sections[name]}" if sections[name] else "")
        for name in SECTION_ORDER
        if name in sections
    ]
    return "\n\n".join(blocks)


def render_plan(title: str, sections: dict[str, str]) -> str:
    """Render PLAN.md."""
    return "\n\n".join([f"# {title}", render_sections(sections)]) + "\n"


def write_atomic(path: Path, text: str) -> None:
    """Write a file via a temp file in the same dir, then replace."""
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(text)
    os.replace(temp_path, path)


@contextmanager
def plan_lock(base: Path) -> Iterator[None]:
    """Hold an exclusive lock on a plan dir."""
    with (base / ".focus.lock").open("a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield


def require_plan(base: Path) -> None:
    """Require a plan directory."""
    if not plan_path(base).is_file():
        raise FocusError(f"no PLAN.md found in {base}")


def require_known_node(base: Path, node_id: str) -> Nodes:
    """Require a plan directory and that the node exists, returning all nodes."""
    require_plan(base)
    nodes = load_nodes(base)
    if node_id not in nodes:
        raise FocusError(f"unknown node '{node_id}'")
    return nodes


def regenerate_plan(base: Path, nodes: Nodes) -> None:
    """Regenerate PLAN.md."""
    path = plan_path(base)
    sections = parse_sections(path.read_text())
    sections.update(plan_sections(nodes, with_siblings(base, nodes)))
    write_atomic(path, render_plan(base.name, sections))


def make_node(links: Links, stage: str) -> Node:
    """Build a node, treating missing link keys as empty."""
    return Node(
        depends=links.get("depends", []),
        scope=links.get("scope", []),
        inputs=links.get("inputs", []),
        outputs=links.get("outputs", []),
        deletes=links.get("deletes", []),
        stage=stage,
    )


def node_links(node: Node) -> Links:
    """A node's links."""
    return {key: node[key] for key in LINK_KEYS}  # type: ignore[literal-required]


def merge_unique(existing: list[str], additions: list[str]) -> list[str]:
    """Append new items."""
    result = list(existing)
    result.extend(item for item in additions if item not in result)
    return result


def interface_id(name: str) -> str:
    """Node id of the interface node for an output name."""
    return f"interface-{slugify(name)}"


def join_edges(nodes: Nodes, prefix: str = "") -> list[str]:
    """Add interface nodes and ordering edges for outputs, inputs and deletes."""
    producers: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        for name in node["outputs"]:
            if node_id != interface_id(name):
                producers.setdefault(name, []).append(node_id)
    duplicates = [
        f"'{name}': output of {', '.join(ids)}"
        for name, ids in producers.items()
        if len(ids) > 1
    ]
    if duplicates:
        raise FocusError(problems=duplicates)
    consumers: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        for name in node["inputs"]:
            consumers.setdefault(name, []).append(node_id)
    lines: list[str] = []

    def add_edges(
        node_id: str, new_deps: list[str], verb: str, reason: str = ""
    ) -> None:
        added = [
            dep
            for dep in new_deps
            if dep != node_id and dep not in nodes[node_id]["depends"]
        ]
        nodes[node_id]["depends"] = merge_unique(nodes[node_id]["depends"], added)
        lines.extend(f"{prefix}{node_id} {verb} {prefix}{dep}{reason}" for dep in added)

    for name, (producer,) in producers.items():
        others = [c for c in consumers.get(name, []) if c != producer]
        if not others:
            continue
        if interface_id(name) not in nodes:
            nodes[interface_id(name)] = make_node({"outputs": [name]}, "todo")
        for node_id in [producer, *others]:
            add_edges(node_id, [interface_id(name)], "depends on")
    for node_id, node in list(nodes.items()):
        for name in node["deletes"]:
            add_edges(
                node_id,
                consumers.get(name, []),
                "after",
                f" (deletes '{name}')",
            )
    return lines


def ancestors(all_nodes: Nodes, node_id: str) -> set[str]:
    """Every node a node transitively depends on."""
    found: set[str] = set()
    pending = [node_id]
    while pending:
        for dep in all_nodes[pending.pop()]["depends"]:
            if dep in all_nodes and dep not in found:
                found.add(dep)
                pending.append(dep)
    return found


def unlinked_mentions(
    base: Path, nodes: Nodes, all_nodes: Nodes, prefix: str = ""
) -> list[str]:
    """Warn of backticked outputs of other nodes that a node has no depends path to."""
    lines: list[str] = []
    for node_id in nodes:
        _, body = parse_node_file(find_node_path(base, node_id).read_text())
        upstream = ancestors(all_nodes, node_id)
        names = dict.fromkeys(
            span.partition("(")[0].strip() for span in re.findall(r"`([^`\n]+)`", body)
        )
        for name in names:
            if name in nodes[node_id]["outputs"] or any(
                linked.rpartition("/")[2] == interface_id(name)
                for linked in (node_id, *upstream)
            ):
                continue
            lines.extend(
                f"warning: {prefix}{node_id} mentions `{name}`, output of {prefix if producer in nodes else ''}{producer}, with no depends path"
                for producer, other in all_nodes.items()
                if name in other["outputs"]
                and producer != interface_id(name)
                and producer != node_id
                and producer not in upstream
                and node_id not in ancestors(all_nodes, producer)
            )
    return lines


def cmd_join(base: Path, prefix: str = "") -> None:
    """Join outputs, inputs and deletes into interface nodes and ordering edges."""
    require_plan(base)
    nodes = load_nodes(base)
    before = {node_id: node_links(node) for node_id, node in nodes.items()}
    lines = join_edges(nodes, prefix)
    validate_or_raise(nodes, with_siblings(base, nodes))
    for node_id, node in nodes.items():
        links = node_links(node)
        if node_id not in before:
            body = (
                f"# Interface: {node['outputs'][0]}\n\n## In\n\n## Out\n\n## Accept\n"
            )
            write_atomic(
                node_path(base, node_id, "todo"), render_node_file(links, body)
            )
        elif links != before[node_id]:
            path = find_node_path(base, node_id)
            write_atomic(path, set_links(path.read_text(), links))
    regenerate_plan(base, nodes)
    print("\n".join(lines) or "nothing to join")
    for warning in unlinked_mentions(base, nodes, with_siblings(base, nodes), prefix):
        print(warning, file=sys.stderr)


def outside_scope(paths: list[str], scope: list[str]) -> list[str]:
    """Sorted paths that overlap no scope entry."""
    return sorted(
        path
        for path in paths
        if not any(scope_overlaps(path, entry) for entry in scope)
    )


def run_git(cwd: Path, *args: str) -> list[str]:
    """Run git in cwd, returning its output lines."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as exc:
        raise FocusError(exc.stderr.strip()) from exc
    return result.stdout.splitlines()


def changed_files(base: Path, git_base: str) -> list[str]:
    """Files changed since the merge-base with git_base, outside the plan dir."""
    (top,) = run_git(Path.cwd(), "rev-parse", "--show-toplevel")
    (merge_base,) = run_git(Path(top), "merge-base", git_base, "HEAD")
    paths = [
        *run_git(Path(top), "diff", "--name-only", merge_base),
        *run_git(
            Path(top), "ls-files", "--others", "--exclude-standard", "--full-name"
        ),
    ]
    plan_dir = base.resolve()
    return [p for p in paths if not (Path(top) / p).resolve().is_relative_to(plan_dir)]


def cmd_init(base: Path) -> None:
    """Create a plan."""
    if base.exists():
        raise FocusError(f"{base} already exists")
    for stage in ("building", "testing", "done"):
        (base / "nodes" / STAGES[stage]).mkdir(parents=True)
    sections = {name: "" for name in SECTION_ORDER} | plan_sections({}, {})
    write_atomic(plan_path(base), render_plan(base.name, sections))
    print(f"created {base}")


def cmd_add(base: Path, name: str, links: Links) -> None:
    """Add a node."""
    require_plan(base)
    node_id = slugify(name)
    path = node_path(base, node_id, "todo")
    if any(node_path(base, node_id, stage).exists() for stage in STAGES):
        raise FocusError(f"node '{node_id}' already exists")
    nodes = load_nodes(base)
    nodes[node_id] = make_node(links, "todo")
    validate_or_raise(nodes, with_siblings(base, nodes))
    body = f"# {name}\n\n## In\n\n## Out\n\n## Accept\n"
    write_atomic(path, render_node_file(links, body))
    regenerate_plan(base, nodes)
    print(f"added {path}{links_summary(links)}")


def edit_links(base: Path, node_id: str, links: Links, add: bool) -> None:
    """Link or unlink a node."""
    require_plan(base)
    nodes = load_nodes(base)
    path = find_node_path(base, node_id)
    front, _ = parse_node_file(path.read_text())
    new_links = {
        key: merge_unique(front[key], links.get(key, []))
        if add
        else [v for v in front[key] if v not in links.get(key, [])]
        for key in LINK_KEYS
    }
    nodes[node_id] = make_node(new_links, nodes[node_id]["stage"])
    validate_or_raise(nodes, with_siblings(base, nodes))
    write_atomic(path, set_links(path.read_text(), new_links))
    regenerate_plan(base, nodes)
    print(f"{node_id}{links_summary(new_links)}")


def move_node(
    base: Path,
    node_id: str,
    src_stages: tuple[str, ...],
    dst_stage: str,
    verb: str,
    note: str = "",
) -> None:
    """Move a node between stages."""
    require_plan(base)
    with plan_lock(base):
        nodes = require_known_node(base, node_id)
        src_stage = nodes[node_id]["stage"]
        if src_stage not in src_stages:
            expected = " or ".join(f"nodes/{STAGES[stage]}" for stage in src_stages)
            raise FocusError(f"'{node_id}' is not in {expected}")
        nodes[node_id]["stage"] = dst_stage
        validate_or_raise(nodes, with_siblings(base, nodes))
        dst_path = node_path(base, node_id, dst_stage)
        dst_path.parent.mkdir(exist_ok=True)
        node_path(base, node_id, src_stage).rename(dst_path)
        regenerate_plan(base, nodes)
    print(f"{verb} {node_id}" + (f": {note}" if note else ""))


def cmd_start(base: Path, node_id: str) -> None:
    """Mark a node's build started."""
    move_node(base, node_id, ("todo",), "building", "start")


def cmd_built(base: Path, node_id: str) -> None:
    """Mark a node built, awaiting acceptance tests."""
    move_node(base, node_id, ("todo", "building"), "testing", "built")
    path = node_path(base, node_id, "testing")
    write_atomic(path, update_failed_line(path.read_text(), None))


def cmd_pass(base: Path, node_id: str) -> None:
    """Mark a node's acceptance tests passing."""
    move_node(base, node_id, ("testing",), "done", "pass")


def cmd_fail(base: Path, node_id: str, reason: str) -> None:
    """Mark a node's acceptance tests failing."""
    move_node(base, node_id, ("testing",), "todo", "fail", reason)
    path = node_path(base, node_id, "todo")
    write_atomic(path, update_failed_line(path.read_text(), reason))


def fail_and_exit(base: Path, node_id: str, reason: str) -> NoReturn:
    """Fail a node, then exit 1."""
    cmd_fail(base, node_id, reason)
    sys.exit(1)


def cmd_set_test(base: Path, node_id: str, command: str) -> None:
    """Set a node's plan-time test command."""
    require_known_node(base, node_id)
    if "\n" in command:
        raise FocusError("test command must be one line")
    path = find_node_path(base, node_id)
    write_atomic(
        path, replace_front_lines(path.read_text(), {"test"}, [f"test: {command}"])
    )
    print(f"{node_id} test: {command}")


def plan_checks(base: Path) -> list[str]:
    """The plan's Checks commands."""
    return parse_checks(parse_sections(plan_path(base).read_text()).get("Checks", ""))


def failures(commands: list[str]) -> Iterator[tuple[str, int]]:
    """Run commands in order, lazily yielding each failing one with its exit code."""
    for cmd in commands:
        print(f"$ {cmd}", flush=True)
        returncode = subprocess.run(cmd, shell=True, check=False).returncode
        if returncode != 0:
            yield cmd, returncode


def cmd_check(
    base: Path,
    node_id: str,
    git_base: str | None = None,
    node_only: bool = False,
) -> None:
    """Run a node's test command and, unless node_only, the plan's Checks, then pass or fail it."""
    nodes = require_known_node(base, node_id)
    if nodes[node_id]["stage"] != "testing":
        raise FocusError(f"'{node_id}' is not in nodes/{STAGES['testing']}")
    command = node_test_command(find_node_path(base, node_id).read_text())
    if command is None:
        raise FocusError(f"'{node_id}' has no test command")
    if git_base:
        outside = outside_scope(changed_files(base, git_base), nodes[node_id]["scope"])
        if outside:
            fail_and_exit(base, node_id, f"outside scope: {', '.join(outside)}")
    failure = next(failures([command, *([] if node_only else plan_checks(base))]), None)
    if failure:
        fail_and_exit(base, node_id, f"`{failure[0]}` exited {failure[1]}")
    cmd_pass(base, node_id)


def plan_collect(base: Path) -> str:
    """The plan's Collect command template."""
    templates = parse_checks(
        parse_sections(plan_path(base).read_text()).get("Collect", "")
    )
    if not templates:
        raise FocusError("plan has no Collect command")
    if "{test}" not in templates[0]:
        raise FocusError("Collect command needs {test}")
    return templates[0]


def cmd_collect(base: Path, node_id: str) -> None:
    """Dry-run a node's test command selection, exiting 1 if it selects no tests."""
    require_known_node(base, node_id)
    command = node_test_command(find_node_path(base, node_id).read_text())
    if command is None:
        raise FocusError(f"'{node_id}' has no test command")
    failure = next(failures([plan_collect(base).replace("{test}", command)]), None)
    if failure:
        print(f"`{node_id}` selects no tests: `{failure[0]}` exited {failure[1]}")
        sys.exit(1)


def cmd_check_wave(base: Path) -> None:
    """Run every one of the plan's Checks, exiting 1 if any failed."""
    require_plan(base)
    failed = False
    for cmd, returncode in failures(plan_checks(base)):
        print(f"`{cmd}` exited {returncode}")
        failed = True
    if failed:
        sys.exit(1)


def cmd_remove(base: Path, node_id: str) -> None:
    """Remove a node."""
    nodes = require_known_node(base, node_id)
    dependents = sorted(
        other for other, node in nodes.items() if node_id in node["depends"]
    )
    if dependents:
        raise FocusError(
            f"cannot remove '{node_id}': depended on by {', '.join(dependents)}"
        )
    find_node_path(base, node_id).unlink()
    del nodes[node_id]
    regenerate_plan(base, nodes)
    print(f"removed {node_id}")


def cmd_rename(base: Path, node_id: str, name: str) -> None:
    """Rename a node, updating its dependents."""
    nodes = require_known_node(base, node_id)
    new_id = slugify(name)
    if new_id in nodes:
        raise FocusError(f"node '{new_id}' already exists")
    for other_id, node in nodes.items():
        if node_id in node["depends"]:
            node["depends"] = [
                new_id if dep == node_id else dep for dep in node["depends"]
            ]
            path = node_path(base, other_id, node["stage"])
            write_atomic(path, set_links(path.read_text(), node_links(node)))
    nodes[new_id] = nodes.pop(node_id)
    old_path = node_path(base, node_id, nodes[new_id]["stage"])
    new_path = node_path(base, new_id, nodes[new_id]["stage"])
    write_atomic(
        new_path,
        re.sub(
            r"^# .*$", f"# {name}", old_path.read_text(), count=1, flags=re.MULTILINE
        ),
    )
    old_path.unlink()
    regenerate_plan(base, nodes)
    print(f"renamed {node_id} -> {new_id}")


def plan_without_nodes(base: Path) -> dict[str, str]:
    """Parse PLAN.md's sections, excluding Nodes."""
    sections = parse_sections(plan_path(base).read_text())
    sections.pop("Nodes", None)
    return sections


def node_section(base: Path, node_id: str, name: str) -> str:
    """Read a named section from a node's file body."""
    _, body = parse_node_file(find_node_path(base, node_id).read_text())
    return parse_sections(body).get(name, "")


def node_brief(base: Path, nodes: Nodes, node_id: str) -> str:
    """A node's file followed by each dependency's Out section."""
    return find_node_path(base, node_id).read_text() + "".join(
        f"\n## {dep_id}\n\n{node_section(base, dep_id, 'Out')}\n"
        for dep_id in nodes[node_id]["depends"]
    )


def cmd_show(base: Path, node_id: str) -> None:
    """Print a node brief."""
    nodes = require_known_node(base, node_id)
    print(render_plan(base.name, plan_without_nodes(base)), end="")
    print(node_brief(base, nodes, node_id), end="")


def cmd_briefs(base: Path, out: Path | None = None) -> None:
    """Print every node's brief as JSON, or write one brief file per node to out."""
    sections = plan_without_nodes(base)
    sections.pop("Graph", None)
    nodes = load_nodes(base)
    plan = render_plan(base.name, sections)
    briefs = {node_id: node_brief(base, nodes, node_id) for node_id in sorted(nodes)}
    if out is None:
        print(json.dumps({"plan": plan, "nodes": briefs}))
        return
    out.mkdir(parents=True, exist_ok=True)
    for node_id, brief in briefs.items():
        (out / f"{node_id}.md").write_text(plan + brief)
        print(out / f"{node_id}.md")


def cmd_ready(base: Path, node_id: str) -> None:
    """Report whether a node is ready."""
    nodes = require_known_node(base, node_id)
    if node_test_command(find_node_path(base, node_id).read_text()) is None:
        raise FocusError(f"'{node_id}' has no test command")
    if not plan_checks(base):
        raise FocusError("plan has no Checks")
    all_nodes = with_siblings(base, nodes)
    waiting = [d for d in nodes[node_id]["depends"] if not is_done(all_nodes, d)]
    if waiting:
        print(f"waiting on: {', '.join(waiting)}")
        sys.exit(1)
    print("ready")


def cmd_waves(base: Path) -> None:
    """Print nodes grouped by wave."""
    require_plan(base)
    nodes = load_nodes(base)
    print(render_waves(nodes, with_siblings(base, nodes)))


COMMENT_INTRO = (
    "This change was planned with the eagle-vision skill, then built node by "
    "node from that plan. The eagle-vision plan and each node's acceptance "
    "criteria are below."
)


def details(summary: str, body: str) -> str:
    """Wrap body in a collapsible <details> block."""
    return f"<details><summary>{summary}</summary>\n\n{body}\n\n</details>"


def accept_text(base: Path, nodes: Nodes, all_nodes: Nodes) -> str:
    """Each node's acceptance criteria, in wave order."""
    waves = compute_waves(nodes, all_nodes)
    order = sorted(nodes, key=lambda n: (waves[n], n))
    return "\n\n".join(
        f"### {node_id}\n\n{node_section(base, node_id, 'Accept')}" for node_id in order
    )


def comment_text(plan: str, accept: str) -> str:
    """A PR comment with the plan and each node's acceptance criteria."""
    return "\n\n".join(
        [
            "## Eagle-vision plan",
            COMMENT_INTRO,
            details("Eagle-vision plan", plan),
            details("Eagle-vision acceptance criteria per node", accept),
        ]
    )


def cmd_comment(base: Path) -> None:
    """Print a PR comment with the plan and each node's acceptance criteria."""
    require_plan(base)
    nodes = load_nodes(base)
    plan = render_sections(plan_without_nodes(base))
    print(comment_text(plan, accept_text(base, nodes, with_siblings(base, nodes))))


def build_parser() -> argparse.ArgumentParser:
    """Build the parser."""
    parser = argparse.ArgumentParser(description="Manage a plan directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_cmd(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("dir", type=Path)
        return sub

    def add_links(sub: argparse.ArgumentParser) -> None:
        for key in LINK_KEYS:
            sub.add_argument(f"--{key}", nargs="*", default=[])

    add_cmd("init", "Create a new plan directory")

    add_parser = add_cmd(
        "add",
        "Add a node; --depends/--scope/--inputs/--outputs/--deletes set its links (--deletes: old outputs it removes)",
    )
    add_parser.add_argument("name")
    add_links(add_parser)

    for command, help_text in (
        ("link", "Add links to a node"),
        ("unlink", "Remove links from a node"),
    ):
        link_parser = add_cmd(command, help_text)
        link_parser.add_argument("id")
        add_links(link_parser)

    add_cmd(
        "join",
        "Add an interface node per output others input, which producer and consumers depend on, and order each deleter after the deleted output's consumers",
    )
    add_cmd("remove", "Remove a node with no dependents").add_argument("id")
    rename_parser = add_cmd("rename", "Rename a node")
    rename_parser.add_argument("id")
    rename_parser.add_argument("name")

    add_cmd("start", "Mark a node's build started").add_argument("id")
    add_cmd("built", "Mark a node built, awaiting check").add_argument("id")
    add_cmd("pass", "Mark a node's acceptance tests passing").add_argument("id")
    fail_parser = add_cmd(
        "fail",
        "Send a node back to to-do with a one-sentence reason; re-run built after fixing",
    )
    fail_parser.add_argument("id")
    fail_parser.add_argument("reason")
    set_test_parser = add_cmd(
        "set-test", "Set a node's one-line test command, with its criteria"
    )
    set_test_parser.add_argument("id")
    set_test_parser.add_argument("test_command")
    check_parser = add_cmd(
        "check",
        "Fail changes outside scope since --base, run the node's test and the plan's Checks (--node-only: not the Checks), then pass or fail it",
    )
    check_parser.add_argument("id")
    check_parser.add_argument("--base", default=None)
    check_parser.add_argument("--node-only", action="store_true")
    add_cmd("check-wave", "Run the plan's Checks once; exit 1 at the first failure")
    add_cmd("collect", "Dry-run a node's test command selection").add_argument("id")
    add_cmd(
        "show", "Print all a builder needs: plan, node, dependencies' Out"
    ).add_argument("id")
    briefs_parser = add_cmd(
        "briefs",
        "Print every node's brief as JSON, without build status; --out writes one file per node and prints the paths",
    )
    briefs_parser.add_argument("--out", type=Path, default=None)
    add_cmd("ready", "Check whether a node is ready").add_argument("id")
    add_cmd("waves", "Print nodes grouped by wave")
    add_cmd(
        "comment",
        "Print a PR comment with the plan and each node's acceptance criteria",
    )
    view_parser = add_cmd(
        "view",
        "Serve a live graph view of the plan on localhost (--port, default 8765)",
    )
    view_parser.add_argument("--port", type=int, default=8765)

    return parser


def links_arg(args: argparse.Namespace) -> Links:
    """Links given on the command line."""
    return {key: getattr(args, key) for key in LINK_KEYS}


COMMANDS: dict[str, Callable[[argparse.Namespace], None]] = {
    "init": lambda a: cmd_init(a.dir),
    "add": lambda a: cmd_add(a.dir, a.name, links_arg(a)),
    "link": lambda a: edit_links(a.dir, a.id, links_arg(a), add=True),
    "unlink": lambda a: edit_links(a.dir, a.id, links_arg(a), add=False),
    "join": lambda a: cmd_join(a.dir),
    "remove": lambda a: cmd_remove(a.dir, a.id),
    "rename": lambda a: cmd_rename(a.dir, a.id, a.name),
    "start": lambda a: cmd_start(a.dir, a.id),
    "built": lambda a: cmd_built(a.dir, a.id),
    "pass": lambda a: cmd_pass(a.dir, a.id),
    "fail": lambda a: cmd_fail(a.dir, a.id, a.reason),
    "set-test": lambda a: cmd_set_test(a.dir, a.id, a.test_command),
    "check": lambda a: cmd_check(a.dir, a.id, a.base, a.node_only),
    "check-wave": lambda a: cmd_check_wave(a.dir),
    "collect": lambda a: cmd_collect(a.dir, a.id),
    "show": lambda a: cmd_show(a.dir, a.id),
    "briefs": lambda a: cmd_briefs(a.dir, a.out),
    "ready": lambda a: cmd_ready(a.dir, a.id),
    "waves": lambda a: cmd_waves(a.dir),
    "comment": lambda a: cmd_comment(a.dir),
    "view": lambda a: cmd_view(a.dir, a.port),
}


def child_plans(parent: Path) -> list[Path]:
    """Plan dirs directly under a dir that has no nodes of its own."""
    if (parent / "nodes").is_dir() or not parent.is_dir():
        return []
    return sorted(child for child in parent.iterdir() if plan_path(child).is_file())


def load_children(plans: list[Path]) -> Nodes:
    """Load the nodes of plan dirs, keyed '<dir>/<node>'."""
    nodes: Nodes = {}
    for plan in plans:
        for node_id, node in load_nodes(plan).items():
            node["depends"] = [
                sibling_dependency(dep, plan.name, "") for dep in node["depends"]
            ]
            nodes[f"{plan.name}/{node_id}"] = node
    return nodes


def view_data(base: Path) -> dict[str, object]:
    """The plan graph for the view page: repos, wave count and nodes."""
    plans = child_plans(base)
    if plans:
        nodes = all_nodes = load_children(plans)
    else:
        plans = [base]
        nodes = load_nodes(base)
        all_nodes = with_siblings(base, nodes)
    waves = compute_waves(nodes, all_nodes)

    def entry(node_id: str) -> dict[str, object]:
        repo, separator, label = node_id.partition("/")
        if not separator:
            repo, label = base.resolve().name, node_id
        return {
            "id": node_id,
            "repo": repo,
            "label": label,
            "wave": waves[node_id],
            "stage": nodes[node_id]["stage"],
            "depends": nodes[node_id]["depends"],
            "sections": {
                name: node_section(plans[0], node_id, name) for name in VIEW_SECTIONS
            },
        }

    return {
        "repos": [plan.resolve().name for plan in plans],
        "waves": max(waves.values(), default=0),
        "nodes": [entry(node_id) for node_id in nodes],
    }


class ViewHandler(BaseHTTPRequestHandler):
    """Serve the view page and the plan graph rebuilt on every request."""

    def __init__(self, *args: Any, base: Path, **kwargs: Any) -> None:
        """Store the plan dir before the request is handled."""
        self.base = base
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        """Answer the page, or the plan graph as JSON."""
        if self.path == "/":
            body, content_type = VIEW_PAGE.read_bytes(), "text/html; charset=utf-8"
        elif self.path == "/data.json":
            body = json.dumps(view_data(self.base)).encode()
            content_type = "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep the console quiet."""


def make_view_server(base: Path, port: int) -> ThreadingHTTPServer:
    """A localhost server for the plan dir's view."""
    return ThreadingHTTPServer(("127.0.0.1", port), partial(ViewHandler, base=base))


def cmd_view(base: Path, port: int) -> None:
    """Serve a live graph view of the plan until interrupted."""
    if not child_plans(base):
        require_plan(base)
    with make_view_server(base, port) as server:
        print(f"http://127.0.0.1:{server.server_port}/", flush=True)
        with suppress(KeyboardInterrupt):
            server.serve_forever()


def merged_waves(plans: list[Path], args: argparse.Namespace) -> None:
    """Print the nodes of plan dirs grouped by wave."""
    nodes = load_children(plans)
    print(render_waves(nodes, nodes))


def output_of(command: Callable[[Path], None], plan: Path) -> str:
    """What a command prints for a plan dir."""
    with redirect_stdout(io.StringIO()) as buffer:
        command(plan)
    return buffer.getvalue()


def merged_briefs(plans: list[Path], args: argparse.Namespace) -> None:
    """Print the briefs of plan dirs as one JSON object, or write them under out."""
    if args.out:
        for plan in plans:
            cmd_briefs(plan, args.out / plan.name)
        return
    briefs = {plan.name: json.loads(output_of(cmd_briefs, plan)) for plan in plans}
    print(
        json.dumps(
            {
                "plan": "\n".join(brief["plan"] for brief in briefs.values()),
                "nodes": {
                    f"{name}/{node_id}": text
                    for name, brief in briefs.items()
                    for node_id, text in brief["nodes"].items()
                },
            }
        )
    )


def merged_comment(plans: list[Path], args: argparse.Namespace) -> None:
    """Print a PR comment covering plan dirs."""
    nodes = load_children(plans)
    plan = "\n".join(render_plan(plan.name, plan_without_nodes(plan)) for plan in plans)
    print(comment_text(plan, accept_text(plans[0], nodes, nodes)))


def merged_join(plans: list[Path], args: argparse.Namespace) -> None:
    """Join each plan dir, printing the added edges."""
    lines = [
        line
        for plan in plans
        for line in output_of(lambda p: cmd_join(p, f"{p.name}/"), plan).splitlines()
        if line != "nothing to join"
    ]
    print("\n".join(lines) or "nothing to join")


def merged_check_wave(plans: list[Path], args: argparse.Namespace) -> None:
    """Run each plan dir's Checks, exiting 1 at the first failure."""
    for plan in plans:
        cmd_check_wave(plan)


MERGED: dict[str, Callable[[list[Path], argparse.Namespace], None]] = {
    "waves": merged_waves,
    "briefs": merged_briefs,
    "comment": merged_comment,
    "join": merged_join,
    "check-wave": merged_check_wave,
}


def run_command(args: argparse.Namespace) -> None:
    """Run a command, resolving '<child>/<node>' ids when given a parent of plan dirs."""
    plans = child_plans(args.dir)
    if plans and args.command in MERGED:
        MERGED[args.command](plans, args)
        return
    if plans and hasattr(args, "id"):
        child, _, args.id = args.id.rpartition("/")
        args.dir /= child
    COMMANDS[args.command](args)


def main() -> None:
    """Run the CLI."""
    args = build_parser().parse_args()
    try:
        run_command(args)
    except FocusError as exc:
        for line in exc.problems or [str(exc)]:
            print(line, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
