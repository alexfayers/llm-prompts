"""Render templates with variable substitution and frontmatter transformation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def _read_text(path: Path) -> str:
    """Read UTF-8 text from disk.

    Args:
        path: Path to read.

    Returns:
        File content.
    """
    return path.read_text(encoding="utf-8")


def parse_frontmatter(content: str) -> tuple[str, dict[str, str]]:
    """Extract YAML frontmatter and body from content.

    Args:
        content: Template content that may include frontmatter.

    Returns:
        Tuple containing body and parsed frontmatter.
    """
    frontmatter_match = re.match(r"^---\n(.*?)\n---\n?", content, re.DOTALL)

    if not frontmatter_match:
        return content, {}

    body = content[frontmatter_match.end() :].lstrip("\n")
    frontmatter_text = frontmatter_match.group(1)

    frontmatter_dict = {}
    for line in frontmatter_text.splitlines():
        if ": " not in line:
            continue
        key, _, value = line.partition(": ")
        frontmatter_dict[key.strip()] = value.strip().strip("'\"")

    return body, frontmatter_dict


def split_frontmatter(content: str) -> tuple[list[str], str] | None:
    """Split content into its frontmatter lines and verbatim body.

    Args:
        content: File content that may begin with a ``---`` frontmatter block.

    Returns:
        A ``(frontmatter_lines, body)`` pair, or ``None`` when no block is
        present. The body is returned verbatim (no leading-newline stripping).
    """
    match = re.match(r"^---\n(.*?)\n---\n?", content, re.DOTALL)
    if not match:
        return None
    return match.group(1).splitlines(), content[match.end() :]


_BLOCK_SCALAR_INDICATOR = re.compile(r"[>|][+-]?")


def resolve_frontmatter(frontmatter_lines: list[str]) -> dict[str, str] | None:
    """Resolve flat frontmatter lines into key/value strings, folding block scalars.

    Uses the same flat frontmatter model as :func:`parse_frontmatter`, but also
    folds ``>``/``|`` block-scalar values the way YAML would, instead of only
    returning their indicator line. A value line whose indicator carries
    trailing content beyond the bare ``>``/``>-``/``>+``/``|``/``|-``/``|+``
    marker - the shape of a suffix mistakenly appended onto the indicator
    itself, rather than as a continuation line - is malformed and fails the
    whole block.

    Args:
        frontmatter_lines: Frontmatter lines, as returned by split_frontmatter.

    Returns:
        Mapping of key to resolved value, or None if any value is malformed.
    """
    resolved: dict[str, str] = {}
    lines = frontmatter_lines
    i = 0
    while i < len(lines):
        key, _, raw_value = lines[i].partition(": ")
        key = key.strip()
        raw_value = raw_value.strip()
        i += 1
        if not raw_value or raw_value[0] not in ">|":
            resolved[key] = raw_value.strip("'\"")
            continue
        if not _BLOCK_SCALAR_INDICATOR.fullmatch(raw_value):
            return None

        block_lines: list[str] = []
        indent = None
        while i < len(lines) and (not lines[i].strip() or lines[i][:1] in " \t"):
            if lines[i].strip():
                if indent is None:
                    indent = len(lines[i]) - len(lines[i].lstrip())
                block_lines.append(lines[i][indent:])
            else:
                block_lines.append("")
            i += 1
        resolved[key] = ("\n" if raw_value[0] == "|" else " ").join(block_lines)
    return resolved


def strip_gating_keys(content: str, keys: set[str]) -> str:
    """Remove gating frontmatter keys from content, preserving other keys verbatim.

    Uses the same flat frontmatter model as :func:`parse_frontmatter`. Lines whose
    key is in ``keys`` are dropped; all other lines are kept exactly as written. If
    no keys remain, the entire frontmatter block is removed.

    Args:
        content: File content that may begin with a frontmatter block.
        keys: Frontmatter keys to strip.

    Returns:
        Content with the named gating keys removed from its frontmatter.
    """
    split = split_frontmatter(content)
    if split is None:
        return content
    frontmatter_lines, body = split
    kept = [
        line
        for line in frontmatter_lines
        if line.partition(": ")[0].strip() not in keys
    ]
    if not kept:
        return body
    return "---\n" + "\n".join(kept) + "\n---\n" + body


def substitute_variables(content: str, variables: dict[str, str]) -> str:
    """Replace {{key}} placeholders with variable values.

    Args:
        content: Input content containing placeholders.
        variables: Mapping of variable names to replacement values.

    Returns:
        Content with placeholders replaced.
    """
    result = content
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value)
    return result


def find_unreplaced_variables(content: str) -> list[str]:
    """Find any {{VAR}} placeholders remaining after substitution.

    Args:
        content: Content after variable substitution.

    Returns:
        List of unreplaced variable names.
    """
    return re.findall(r"\{\{(\w+)\}\}", content)


def normalize_whitespace(content: str) -> str:
    """Collapse excessive blank lines to maximum of two.

    Args:
        content: Input text to normalize.

    Returns:
        Normalized content with a trailing newline.
    """
    return re.sub(r"\n{3,}", "\n\n", content).strip() + "\n"


def _scoped_paths(
    frontmatter: dict[str, str], override_key: str | None = None
) -> list[str]:
    """Return the glob patterns scoping a rule, honouring a target override.

    Args:
        frontmatter: Parsed frontmatter key-value pairs.
        override_key: Target-specific key that wins over ``paths`` when set.

    Returns:
        Stripped, non-empty glob patterns in source order.
    """
    raw = frontmatter.get("paths", "")
    if override_key is not None:
        raw = frontmatter.get(override_key, raw)
    return [p.strip() for p in raw.split(",") if p.strip()]


def render_for_cline(body: str) -> str:
    """Render template for Cline.

    Args:
        body: Template body.

    Returns:
        Normalized body content.
    """
    return normalize_whitespace(body)


def render_for_copilot(body: str, frontmatter: dict[str, str]) -> str:
    """Render template for Copilot.

    Args:
        body: Template body.
        frontmatter: Parsed frontmatter key-value pairs.

    Returns:
        Copilot-formatted content.
    """
    new_frontmatter = ["---"]

    if "description" in frontmatter:
        new_frontmatter.append(f"description: {frontmatter['description']}")
    apply_to = _scoped_paths(frontmatter, "copilot_apply_to")
    if apply_to:
        new_frontmatter.append(f"applyTo: '{', '.join(apply_to)}'")
    if "copilot_mode" in frontmatter:
        new_frontmatter.append(f"mode: '{frontmatter['copilot_mode']}'")

    new_frontmatter.append("---")
    output = "\n".join(new_frontmatter) + "\n\n" + body

    return normalize_whitespace(output)


def render_for_kiro(body: str, frontmatter: dict[str, str]) -> str:
    """Render template for Kiro.

    Args:
        body: Template body.
        frontmatter: Parsed frontmatter key-value pairs.

    Returns:
        Kiro-formatted content, with inclusion-mode frontmatter when
        ``kiro_inclusion`` is set or ``paths`` scopes the rule, otherwise the
        normalized body only.
    """
    patterns = _scoped_paths(frontmatter, "kiro_file_match_pattern")
    inclusion = frontmatter.get("kiro_inclusion") or (
        "fileMatch" if patterns else None
    )
    if not inclusion:
        return normalize_whitespace(body)

    new_frontmatter = ["---", f"inclusion: {inclusion}"]
    if inclusion == "fileMatch" and patterns:
        if len(patterns) == 1:
            new_frontmatter.append(f"fileMatchPattern: '{patterns[0]}'")
        else:
            joined = ", ".join(f"'{p}'" for p in patterns)
            new_frontmatter.append(f"fileMatchPattern: [{joined}]")
    if inclusion == "auto":
        if "name" in frontmatter:
            new_frontmatter.append(f"name: {frontmatter['name']}")
        if "description" in frontmatter:
            new_frontmatter.append(f"description: {frontmatter['description']}")
    new_frontmatter.append("---")
    output = "\n".join(new_frontmatter) + "\n\n" + body
    return normalize_whitespace(output)


def render_for_claude_code(body: str, frontmatter: dict[str, str]) -> str:
    """Render template for Claude Code.

    Args:
        body: Template body.
        frontmatter: Parsed frontmatter key-value pairs.

    Returns:
        Normalized body, prefixed with a ``paths`` block when the rule is
        scoped to specific files.
    """
    patterns = _scoped_paths(frontmatter)
    if not patterns:
        return normalize_whitespace(body)
    listed = "\n".join(f'  - "{p}"' for p in patterns)
    return normalize_whitespace(f"---\npaths:\n{listed}\n---\n\n{body}")


def render_for_codex(body: str) -> str:
    """Render template for Codex.

    Args:
        body: Template body.

    Returns:
        Normalized body content.
    """
    return normalize_whitespace(body)


def render_template(template_path: str, variables_path: str, target: str) -> str:
    """Render a template file with variable substitution.

    Args:
        template_path: Path to the template file.
        variables_path: Path to JSON file with variables.
        target: Target format (`cline`, `copilot`, or `kiro`).

    Returns:
        Rendered content.

    Raises:
        ValueError: If target is not a recognised format.
    """
    template_content = _read_text(Path(template_path))
    variables = json.loads(_read_text(Path(variables_path)))
    variables.setdefault("REPO_ROOT", str(Path(__file__).parent.parent.resolve()))

    # Substitute variables
    substituted = substitute_variables(template_content, variables)

    # Parse frontmatter
    body, frontmatter = parse_frontmatter(substituted)

    # Render based on target
    if target == "cline":
        return render_for_cline(body)
    if target == "copilot":
        return render_for_copilot(body, frontmatter)
    if target == "kiro":
        return render_for_kiro(body, frontmatter)
    if target == "claude-code":
        return render_for_claude_code(body, frontmatter)
    if target == "codex":
        return render_for_codex(body)
    msg = f"Unknown target format: {target}"
    raise ValueError(msg)


def build_parser() -> argparse.ArgumentParser:
    """Build a command-line argument parser.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        description="Render a template file for Cline or Copilot.",
    )
    parser.add_argument("template_path", help="Path to the template file.")
    parser.add_argument("variables_path", help="Path to JSON file with variables.")
    parser.add_argument(
        "target",
        choices=["cline", "copilot", "kiro", "claude-code", "codex"],
        help="Output target format.",
    )
    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface.

    Args:
        argv: Optional argument sequence excluding program name.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    output = render_template(args.template_path, args.variables_path, args.target)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
