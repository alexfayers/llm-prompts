"""Tests for reading the pull request number off a squash-merge subject."""

from __future__ import annotations

import pytest

from llm_prompts.squash_subject import squash_pr_number


class TestSquashPrNumber:
    @pytest.mark.parametrize(
        ("subject", "expected"),
        [
            ("feat: x (#39)", 39),
            ("feat: x", None),
            ("feat (#3) x", None),
            ("x (#39) ", None),
        ],
    )
    def test_trailing_pr_number(self, subject: str, expected: int | None) -> None:
        assert squash_pr_number(subject) == expected
