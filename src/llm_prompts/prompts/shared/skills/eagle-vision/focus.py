"""Manage an eagle-vision plan directory."""

import argparse
import re
import sys
from collections.abc import Callable
from itertools import combinations
from pathlib import Path
from typing import TypedDict

SECTION_ORDER = [
    "Goal",
    "Approach",
    "Components",
    "Interfaces",
    "Graph",
    "Scope",
    "Nodes",
    "Constraints",
    "Later",
]
FRONT_MATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


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
    done: bool


Nodes = dict[str, Node]


def slugify(name: str) -> str:
    """Slug a node name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def render_node_file(depends: list[str], scope: list[str], body: str) -> str:
    """Render a node file."""

    def line(key: str, values: list[str]) -> str:
        return f"{key}: {', '.join(values)}" if values else f"{key}:"

    return f"---\n{line('depends', depends)}\n{line('scope', scope)}\n---\n{body}"


def parse_node_file(text: str) -> tuple[dict[str, list[str]], str]:
    """Parse a node file."""
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise FocusError("malformed node file: missing front matter")
    front: dict[str, list[str]] = {"depends": [], "scope": []}
    for fm_line in match.group(1).splitlines():
        key, _, value = fm_line.partition(":")
        key = key.strip()
        if key in front:
            front[key] = [v.strip() for v in value.split(",") if v.strip()]
    return front, text[match.end() :]


def find_node_path(base: Path, node_id: str) -> Path:
    """Find a node's file."""
    active = base / "nodes" / f"{node_id}.md"
    if active.exists():
        return active
    done = base / "nodes" / "done" / f"{node_id}.md"
    if done.exists():
        return done
    raise FocusError(f"unknown node '{node_id}'")


def load_nodes(base: Path) -> Nodes:
    """Load all nodes."""
    nodes: Nodes = {}
    for done, folder in ((False, base / "nodes"), (True, base / "nodes" / "done")):
        for path in sorted(folder.glob("*.md")):
            front, _ = parse_node_file(path.read_text())
            nodes[path.stem] = {
                "depends": front["depends"],
                "scope": front["scope"],
                "done": done,
            }
    return nodes


def find_cycle(nodes: Nodes) -> list[str] | None:
    """Find a dependency cycle."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(nodes, WHITE)
    path: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        if node_id not in color or color[node_id] == BLACK:
            return None
        if color[node_id] == GRAY:
            return [*path[path.index(node_id) :], node_id]
        color[node_id] = GRAY
        path.append(node_id)
        for dep in nodes[node_id]["depends"]:
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


def validate_or_raise(nodes: Nodes) -> None:
    """Validate the graph."""
    problems = [
        f"{node_id}: unknown dependency '{dep}'"
        for node_id, node in nodes.items()
        for dep in node["depends"]
        if dep not in nodes
    ]
    cycle = find_cycle(nodes)
    if cycle:
        problems.append(f"dependency cycle: {' -> '.join(cycle)}")

    def overlaps(a: str, b: str) -> bool:
        parts_a, parts_b = a.rstrip("/").split("/"), b.rstrip("/").split("/")
        shorter, longer = sorted((parts_a, parts_b), key=len)
        return longer[: len(shorter)] == shorter

    for (id_a, node_a), (id_b, node_b) in combinations(nodes.items(), 2):
        for entry_a in node_a["scope"]:
            for entry_b in node_b["scope"]:
                if overlaps(entry_a, entry_b):
                    problems.append(
                        f"scope overlap: {id_a} '{entry_a}' and {id_b} '{entry_b}'"
                    )
    if problems:
        raise FocusError(problems=problems)


def compute_waves(nodes: Nodes) -> dict[str, int]:
    """Compute each node's wave number."""
    waves: dict[str, int] = {}

    def wave(node_id: str) -> int:
        if node_id not in waves:
            waves[node_id] = 1 + max(
                (wave(dep) for dep in nodes[node_id]["depends"]), default=0
            )
        return waves[node_id]

    for node_id in nodes:
        wave(node_id)
    return waves


def render_waves(nodes: Nodes) -> str:
    """Render nodes grouped by wave."""
    waves = compute_waves(nodes)
    by_wave: dict[int, list[str]] = {}
    for node_id in sorted(nodes):
        by_wave.setdefault(waves[node_id], []).append(node_id)
    blocks = []
    for wave_num in sorted(by_wave):
        lines = [f"### Wave {wave_num}"]
        for node_id in by_wave[wave_num]:
            node = nodes[node_id]
            if node["done"]:
                lines.append(f"- [x] {node_id}")
            else:
                ready = all(nodes[d]["done"] for d in node["depends"])
                lines.append(f"- [ ] {node_id}" + (" (ready)" if ready else ""))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def plan_sections(nodes: Nodes) -> dict[str, str]:
    """Render generated sections."""
    referenced = {dep for node in nodes.values() for dep in node["depends"]}
    graph = ["```mermaid", "graph LR"]
    for node_id in sorted(nodes):
        depends = nodes[node_id]["depends"]
        if depends:
            graph.extend(f"{dep} --> {node_id}" for dep in sorted(depends))
        elif node_id not in referenced:
            graph.append(node_id)
    done_ids = sorted(node_id for node_id in nodes if nodes[node_id]["done"])
    if done_ids:
        graph.append("classDef done fill:#9f9,stroke:#393")
        graph.extend(f"{node_id}:::done" for node_id in done_ids)
    graph.append("```")
    return {
        "Graph": "\n".join(graph),
        "Scope": "\n".join(
            f"- {node_id}: {', '.join(nodes[node_id]['scope'])}"
            for node_id in sorted(nodes)
            if nodes[node_id]["scope"]
        ),
        "Nodes": render_waves(nodes),
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


def render_plan(title: str, sections: dict[str, str]) -> str:
    """Render PLAN.md."""
    blocks = [f"# {title}"]
    for name in SECTION_ORDER:
        body = sections.get(name, "")
        blocks.append(f"## {name}" + (f"\n\n{body}" if body else ""))
    return "\n\n".join(blocks) + "\n"


def require_plan(base: Path) -> None:
    """Require a plan directory."""
    if not (base / "PLAN.md").is_file():
        raise FocusError(f"no PLAN.md found in {base}")


def regenerate_plan(base: Path, nodes: Nodes) -> None:
    """Regenerate PLAN.md."""
    plan_path = base / "PLAN.md"
    sections = parse_sections(plan_path.read_text())
    sections.update(plan_sections(nodes))
    plan_path.write_text(render_plan(base.name, sections))


def merge_unique(existing: list[str], additions: list[str]) -> list[str]:
    """Append new items."""
    result = list(existing)
    result.extend(item for item in additions if item not in result)
    return result


def cmd_init(base: Path) -> None:
    """Create a plan."""
    if base.exists():
        raise FocusError(f"{base} already exists")
    (base / "nodes" / "done").mkdir(parents=True)
    sections = {name: "" for name in SECTION_ORDER} | plan_sections({})
    (base / "PLAN.md").write_text(render_plan(base.name, sections))
    print(f"created {base}")


def cmd_add(base: Path, name: str, depends: list[str], scope: list[str]) -> None:
    """Add a node."""
    require_plan(base)
    node_id = slugify(name)
    path = base / "nodes" / f"{node_id}.md"
    if path.exists() or (base / "nodes" / "done" / f"{node_id}.md").exists():
        raise FocusError(f"node '{node_id}' already exists")
    nodes = load_nodes(base)
    nodes[node_id] = {"depends": depends, "scope": scope, "done": False}
    validate_or_raise(nodes)
    body = f"# {name}\n\n## In\n\n## Out\n\n## Accept\n"
    path.write_text(render_node_file(depends, scope, body))
    regenerate_plan(base, nodes)
    print(f"added {path} (depends: {', '.join(depends)}; scope: {', '.join(scope)})")


def edit_links(
    base: Path, node_id: str, depends: list[str], scope: list[str], add: bool
) -> None:
    """Link or unlink a node."""
    require_plan(base)
    nodes = load_nodes(base)
    path = find_node_path(base, node_id)
    front, body = parse_node_file(path.read_text())
    if add:
        new_depends = merge_unique(front["depends"], depends)
        new_scope = merge_unique(front["scope"], scope)
    else:
        new_depends = [d for d in front["depends"] if d not in depends]
        new_scope = [s for s in front["scope"] if s not in scope]
    nodes[node_id] = {
        "depends": new_depends,
        "scope": new_scope,
        "done": nodes[node_id]["done"],
    }
    validate_or_raise(nodes)
    path.write_text(render_node_file(new_depends, new_scope, body))
    regenerate_plan(base, nodes)
    print(f"{node_id} depends: {', '.join(new_depends)}; scope: {', '.join(new_scope)}")


def cmd_done(base: Path, node_id: str) -> None:
    """Mark a node done."""
    require_plan(base)
    nodes = load_nodes(base)
    if node_id not in nodes:
        raise FocusError(f"unknown node '{node_id}'")
    if nodes[node_id]["done"]:
        raise FocusError(f"'{node_id}' is already done")
    nodes[node_id]["done"] = True
    validate_or_raise(nodes)
    src = base / "nodes" / f"{node_id}.md"
    src.rename(base / "nodes" / "done" / f"{node_id}.md")
    regenerate_plan(base, nodes)
    print(f"done {node_id}")


def cmd_show(base: Path, node_id: str) -> None:
    """Print a node brief."""
    require_plan(base)
    nodes = load_nodes(base)
    if node_id not in nodes:
        raise FocusError(f"unknown node '{node_id}'")
    sections = parse_sections((base / "PLAN.md").read_text())
    sections.pop("Nodes", None)
    print(render_plan(base.name, sections), end="")
    print(find_node_path(base, node_id).read_text(), end="")
    for dep_id in nodes[node_id]["depends"]:
        _, dep_body = parse_node_file(find_node_path(base, dep_id).read_text())
        print(f"## {dep_id}\n\n{parse_sections(dep_body).get('Out', '')}")


def cmd_ready(base: Path, node_id: str) -> None:
    """Report whether a node is ready."""
    require_plan(base)
    nodes = load_nodes(base)
    if node_id not in nodes:
        raise FocusError(f"unknown node '{node_id}'")
    waiting = [d for d in nodes[node_id]["depends"] if not nodes[d]["done"]]
    if waiting:
        print(f"waiting on: {', '.join(waiting)}")
        sys.exit(1)
    print("ready")


def cmd_waves(base: Path) -> None:
    """Print nodes grouped by wave."""
    require_plan(base)
    print(render_waves(load_nodes(base)))


def build_parser() -> argparse.ArgumentParser:
    """Build the parser."""
    parser = argparse.ArgumentParser(description="Manage a plan directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_cmd(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("dir", type=Path)
        return sub

    def add_links(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--depends", nargs="*", default=[])
        sub.add_argument("--scope", nargs="*", default=[])

    add_cmd("init", "Create a new plan directory")

    add_parser = add_cmd("add", "Add a new node")
    add_parser.add_argument("name")
    add_links(add_parser)

    for command, help_text in (
        ("link", "Add dependencies/scope to a node"),
        ("unlink", "Remove dependencies/scope from a node"),
    ):
        link_parser = add_cmd(command, help_text)
        link_parser.add_argument("id")
        add_links(link_parser)

    add_cmd("done", "Mark a node done").add_argument("id")
    add_cmd("show", "Show a node and its dependencies").add_argument("id")
    add_cmd("ready", "Check whether a node is ready").add_argument("id")
    add_cmd("waves", "Print nodes grouped by wave")

    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace], None]] = {
    "init": lambda a: cmd_init(a.dir),
    "add": lambda a: cmd_add(a.dir, a.name, a.depends, a.scope),
    "link": lambda a: edit_links(a.dir, a.id, a.depends, a.scope, add=True),
    "unlink": lambda a: edit_links(a.dir, a.id, a.depends, a.scope, add=False),
    "done": lambda a: cmd_done(a.dir, a.id),
    "show": lambda a: cmd_show(a.dir, a.id),
    "ready": lambda a: cmd_ready(a.dir, a.id),
    "waves": lambda a: cmd_waves(a.dir),
}


def main() -> None:
    """Run the CLI."""
    args = build_parser().parse_args()
    try:
        COMMANDS[args.command](args)
    except FocusError as exc:
        for line in exc.problems or [str(exc)]:
            print(line, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
