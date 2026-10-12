"""Tests that every shipped pi extension exports a default factory function."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_prompts.extension_factories import DEFAULT_FACTORY

_EXTENSIONS = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "extensions"
)


@pytest.mark.parametrize(
    "extension", sorted(_EXTENSIONS.glob("*.ts")), ids=lambda p: p.name
)
def test_extension_exports_default_factory_function(extension: Path) -> None:
    assert DEFAULT_FACTORY.search(extension.read_text())
