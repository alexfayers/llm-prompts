"""Render templates with variable substitution and frontmatter transformation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
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
    if "copilot_apply_to" in frontmatter:
        new_frontmatter.append(f"applyTo: '{frontmatter['copilot_apply_to']}'")
    if "copilot_mode" in frontmatter:
        new_frontmatter.append(f"mode: '{frontmatter['copilot_mode']}'")

    new_frontmatter.append("---")
    output = "\n".join(new_frontmatter) + "\n\n" + body

    return normalize_whitespace(output)


def render_for_kiro(body: str) -> str:
    """Render template for Kiro.

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
        return render_for_kiro(body)
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
        "target", choices=["cline", "copilot", "kiro"], help="Output target format."
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
