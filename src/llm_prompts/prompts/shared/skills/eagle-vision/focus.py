"""Manage an eagle-vision plan directory."""

import argparse
import re
import subprocess
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
    "Checks",
    "Later",
]
FRONT_MATTER_RE = re.compile(r"\A---\n((?:.*\n)*?)---\n")
STAGES: dict[str, str] = {"todo": "", "testing": "testing", "done": "done"}


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
    stage: str


Nodes = dict[str, Node]


def slugify(name: str) -> str:
    """Slug a node name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def node_path(base: Path, node_id: str, stage: str) -> Path:
    """Path to a node's file for a stage."""
    return base / "nodes" / STAGES[stage] / f"{node_id}.md"


def plan_path(base: Path) -> Path:
    """Path to PLAN.md."""
    return base / "PLAN.md"


def links_summary(depends: list[str], scope: list[str]) -> str:
    """Format a depends/scope summary."""
    lines = link_lines(depends, scope)
    return f" ({'; '.join(lines)})" if lines else ""


def link_lines(depends: list[str], scope: list[str]) -> list[str]:
    """Format non-empty depends/scope front-matter lines."""
    return [
        f"{key}: {', '.join(values)}"
        for key, values in (("depends", depends), ("scope", scope))
        if values
    ]


def render_node_file(depends: list[str], scope: list[str], body: str) -> str:
    """Render a node file."""
    return (
        "---\n"
        + "".join(f"{ln}\n" for ln in link_lines(depends, scope))
        + f"---\n{body}"
    )


def match_front_matter(text: str) -> re.Match[str]:
    """Match a node file's front matter, or raise."""
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise FocusError("malformed node file: missing front matter")
    return match


def parse_node_file(text: str) -> tuple[dict[str, list[str]], str]:
    """Parse a node file."""
    match = match_front_matter(text)
    front: dict[str, list[str]] = {"depends": [], "scope": []}
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


def set_links(text: str, depends: list[str], scope: list[str]) -> str:
    """Replace the depends/scope front-matter lines."""
    return replace_front_lines(text, {"depends", "scope"}, link_lines(depends, scope))


def find_node_path(base: Path, node_id: str) -> Path:
    """Find a node's file."""
    for stage in STAGES:
        path = node_path(base, node_id, stage)
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
            nodes[path.stem] = {
                "depends": front["depends"],
                "scope": front["scope"],
                "stage": stage,
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
            if node["stage"] == "done":
                lines.append(f"- [x] {node_id}")
            elif node["stage"] == "testing":
                lines.append(f"- [ ] {node_id} (testing)")
            else:
                ready = all(nodes[d]["stage"] == "done" for d in node["depends"])
                lines.append(f"- [ ] {node_id}" + (" (ready)" if ready else ""))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def mermaid_id(node_id: str) -> str:
    """Mermaid-safe node id (hyphens can trigger reserved-word parsing, e.g. 'end')."""
    return node_id.replace("-", "_")


def mermaid_node(node_id: str) -> str:
    """Mermaid node declaration: a safe id labelled with the original name."""
    return f'{mermaid_id(node_id)}["{node_id}"]'


def plan_sections(nodes: Nodes) -> dict[str, str]:
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
    done_ids = sorted(node_id for node_id in nodes if nodes[node_id]["stage"] == "done")
    if done_ids:
        graph.append("classDef done fill:#9f9,stroke:#393")
        graph.extend(f"{mermaid_id(node_id)}:::done" for node_id in done_ids)
    testing_ids = sorted(
        node_id for node_id in nodes if nodes[node_id]["stage"] == "testing"
    )
    if testing_ids:
        graph.append("classDef testing fill:#ff9,stroke:#993")
        graph.extend(f"{mermaid_id(node_id)}:::testing" for node_id in testing_ids)
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
    sections.update(plan_sections(nodes))
    path.write_text(render_plan(base.name, sections))


def merge_unique(existing: list[str], additions: list[str]) -> list[str]:
    """Append new items."""
    result = list(existing)
    result.extend(item for item in additions if item not in result)
    return result


def cmd_init(base: Path) -> None:
    """Create a plan."""
    if base.exists():
        raise FocusError(f"{base} already exists")
    (base / "nodes" / STAGES["testing"]).mkdir(parents=True)
    (base / "nodes" / STAGES["done"]).mkdir(parents=True)
    sections = {name: "" for name in SECTION_ORDER} | plan_sections({})
    plan_path(base).write_text(render_plan(base.name, sections))
    print(f"created {base}")


def cmd_add(base: Path, name: str, depends: list[str], scope: list[str]) -> None:
    """Add a node."""
    require_plan(base)
    node_id = slugify(name)
    path = node_path(base, node_id, "todo")
    if any(node_path(base, node_id, stage).exists() for stage in STAGES):
        raise FocusError(f"node '{node_id}' already exists")
    nodes = load_nodes(base)
    nodes[node_id] = {"depends": depends, "scope": scope, "stage": "todo"}
    validate_or_raise(nodes)
    body = f"# {name}\n\n## In\n\n## Out\n\n## Accept\n"
    path.write_text(render_node_file(depends, scope, body))
    regenerate_plan(base, nodes)
    print(f"added {path}{links_summary(depends, scope)}")


def edit_links(
    base: Path, node_id: str, depends: list[str], scope: list[str], add: bool
) -> None:
    """Link or unlink a node."""
    require_plan(base)
    nodes = load_nodes(base)
    path = find_node_path(base, node_id)
    front, _ = parse_node_file(path.read_text())
    if add:
        new_depends = merge_unique(front["depends"], depends)
        new_scope = merge_unique(front["scope"], scope)
    else:
        new_depends = [d for d in front["depends"] if d not in depends]
        new_scope = [s for s in front["scope"] if s not in scope]
    nodes[node_id] = {
        "depends": new_depends,
        "scope": new_scope,
        "stage": nodes[node_id]["stage"],
    }
    validate_or_raise(nodes)
    path.write_text(set_links(path.read_text(), new_depends, new_scope))
    regenerate_plan(base, nodes)
    print(f"{node_id}{links_summary(new_depends, new_scope)}")


def move_node(
    base: Path,
    node_id: str,
    src_stage: str,
    dst_stage: str,
    verb: str,
    note: str = "",
) -> None:
    """Move a node between stages."""
    nodes = require_known_node(base, node_id)
    src_path = node_path(base, node_id, src_stage)
    if not src_path.exists():
        raise FocusError(f"'{node_id}' is not in nodes/{STAGES[src_stage]}")
    nodes[node_id]["stage"] = dst_stage
    validate_or_raise(nodes)
    src_path.rename(node_path(base, node_id, dst_stage))
    regenerate_plan(base, nodes)
    print(f"{verb} {node_id}" + (f": {note}" if note else ""))


def cmd_built(base: Path, node_id: str) -> None:
    """Mark a node built, awaiting acceptance tests."""
    move_node(base, node_id, "todo", "testing", "built")
    path = node_path(base, node_id, "testing")
    path.write_text(update_failed_line(path.read_text(), None))


def cmd_pass(base: Path, node_id: str) -> None:
    """Mark a node's acceptance tests passing."""
    move_node(base, node_id, "testing", "done", "pass")


def cmd_fail(base: Path, node_id: str, reason: str) -> None:
    """Mark a node's acceptance tests failing."""
    move_node(base, node_id, "testing", "todo", "fail", reason)
    path = node_path(base, node_id, "todo")
    path.write_text(update_failed_line(path.read_text(), reason))


def cmd_set_test(base: Path, node_id: str, command: str) -> None:
    """Set a node's plan-time test command."""
    require_known_node(base, node_id)
    if "\n" in command:
        raise FocusError("test command must be one line")
    path = find_node_path(base, node_id)
    path.write_text(
        replace_front_lines(path.read_text(), {"test"}, [f"test: {command}"])
    )
    print(f"{node_id} test: {command}")


def cmd_check(base: Path, node_id: str) -> None:
    """Run a node's test command and the plan's Checks, then pass or fail it."""
    nodes = require_known_node(base, node_id)
    if nodes[node_id]["stage"] != "testing":
        raise FocusError(f"'{node_id}' is not in nodes/{STAGES['testing']}")
    command = node_test_command(find_node_path(base, node_id).read_text())
    if command is None:
        raise FocusError(f"'{node_id}' has no test command")
    checks = parse_checks(parse_sections(plan_path(base).read_text()).get("Checks", ""))
    for cmd in [command, *checks]:
        print(f"$ {cmd}", flush=True)
        result = subprocess.run(cmd, shell=True, check=False)
        if result.returncode != 0:
            cmd_fail(base, node_id, f"`{cmd}` exited {result.returncode}")
            sys.exit(1)
    cmd_pass(base, node_id)


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
            path.write_text(set_links(path.read_text(), node["depends"], node["scope"]))
    nodes[new_id] = nodes.pop(node_id)
    old_path = node_path(base, node_id, nodes[new_id]["stage"])
    new_path = node_path(base, new_id, nodes[new_id]["stage"])
    new_path.write_text(
        re.sub(
            r"^# .*$", f"# {name}", old_path.read_text(), count=1, flags=re.MULTILINE
        )
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


def cmd_show(base: Path, node_id: str) -> None:
    """Print a node brief."""
    nodes = require_known_node(base, node_id)
    print(render_plan(base.name, plan_without_nodes(base)), end="")
    print(find_node_path(base, node_id).read_text(), end="")
    for dep_id in nodes[node_id]["depends"]:
        print(f"## {dep_id}\n\n{node_section(base, dep_id, 'Out')}")


def cmd_ready(base: Path, node_id: str) -> None:
    """Report whether a node is ready."""
    nodes = require_known_node(base, node_id)
    if node_test_command(find_node_path(base, node_id).read_text()) is None:
        raise FocusError(f"'{node_id}' has no test command")
    checks = parse_checks(parse_sections(plan_path(base).read_text()).get("Checks", ""))
    if not checks:
        raise FocusError("plan has no Checks")
    waiting = [d for d in nodes[node_id]["depends"] if nodes[d]["stage"] != "done"]
    if waiting:
        print(f"waiting on: {', '.join(waiting)}")
        sys.exit(1)
    print("ready")


def cmd_waves(base: Path) -> None:
    """Print nodes grouped by wave."""
    require_plan(base)
    print(render_waves(load_nodes(base)))


COMMENT_INTRO = (
    "This change was planned with the eagle-vision skill, then built node by "
    "node from that plan. The eagle-vision plan and each node's acceptance "
    "criteria are below."
)


def details(summary: str, body: str) -> str:
    """Wrap body in a collapsible <details> block."""
    return f"<details><summary>{summary}</summary>\n\n{body}\n\n</details>"


def cmd_comment(base: Path) -> None:
    """Print a PR comment with the plan and each node's acceptance criteria."""
    require_plan(base)
    nodes = load_nodes(base)
    waves = compute_waves(nodes)
    order = sorted(nodes, key=lambda n: (waves[n], n))
    accept = "\n\n".join(
        f"### {node_id}\n\n{node_section(base, node_id, 'Accept')}" for node_id in order
    )
    print(
        "\n\n".join(
            [
                "## Eagle-vision plan",
                COMMENT_INTRO,
                details("Eagle-vision plan", render_sections(plan_without_nodes(base))),
                details("Eagle-vision acceptance criteria per node", accept),
            ]
        )
    )


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

    add_cmd("remove", "Remove a node with no dependents").add_argument("id")
    rename_parser = add_cmd("rename", "Rename a node")
    rename_parser.add_argument("id")
    rename_parser.add_argument("name")

    add_cmd("built", "Mark a node built, awaiting acceptance tests").add_argument("id")
    add_cmd("pass", "Mark a node's acceptance tests passing").add_argument("id")
    fail_parser = add_cmd("fail", "Mark a node's acceptance tests failing")
    fail_parser.add_argument("id")
    fail_parser.add_argument("reason")
    set_test_parser = add_cmd("set-test", "Set a node's plan-time test command")
    set_test_parser.add_argument("id")
    set_test_parser.add_argument("command")
    add_cmd(
        "check", "Run a node's test command and the plan's Checks, then pass or fail it"
    ).add_argument("id")
    add_cmd("show", "Show a node and its dependencies").add_argument("id")
    add_cmd("ready", "Check whether a node is ready").add_argument("id")
    add_cmd("waves", "Print nodes grouped by wave")
    add_cmd(
        "comment",
        "Print a PR comment with the plan and each node's acceptance criteria",
    )

    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace], None]] = {
    "init": lambda a: cmd_init(a.dir),
    "add": lambda a: cmd_add(a.dir, a.name, a.depends, a.scope),
    "link": lambda a: edit_links(a.dir, a.id, a.depends, a.scope, add=True),
    "unlink": lambda a: edit_links(a.dir, a.id, a.depends, a.scope, add=False),
    "remove": lambda a: cmd_remove(a.dir, a.id),
    "rename": lambda a: cmd_rename(a.dir, a.id, a.name),
    "built": lambda a: cmd_built(a.dir, a.id),
    "pass": lambda a: cmd_pass(a.dir, a.id),
    "fail": lambda a: cmd_fail(a.dir, a.id, a.reason),
    "set-test": lambda a: cmd_set_test(a.dir, a.id, a.command),
    "check": lambda a: cmd_check(a.dir, a.id),
    "show": lambda a: cmd_show(a.dir, a.id),
    "ready": lambda a: cmd_ready(a.dir, a.id),
    "waves": lambda a: cmd_waves(a.dir),
    "comment": lambda a: cmd_comment(a.dir),
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
