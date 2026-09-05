"""Shared pytest fixtures for the test suite."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SideEffect = (
    BaseException | type[BaseException] | Callable[[list[str], dict[str, Any]], Any]
)


def _verb_tokens(argv: list[str]) -> list[str]:
    if not argv or argv[0] != "git":
        return list(argv)
    tokens = argv[1:]
    while len(tokens) >= 2 and tokens[0] == "-C":
        tokens = tokens[2:]
    return tokens


def _matches_repo(argv: list[str], repo: str | Path | None) -> bool:
    if repo is None:
        return True
    repo_str = str(repo)
    return any(
        tok == "-C" and argv[i + 1] == repo_str for i, tok in enumerate(argv[:-1])
    )


def _pick(value: Any, index: int) -> Any:
    return value[min(index, len(value) - 1)] if isinstance(value, list) else value


class _Route:
    def __init__(
        self,
        tokens: list[str] | None,
        predicate: Callable[[list[str]], bool] | None,
        stdout: str | list[str],
        returncode: int | list[int],
        stderr: str | list[str],
        repo: str | Path | None,
        side_effect: SideEffect | None,
    ) -> None:
        self.tokens, self.predicate, self.repo, self.side_effect = (
            tokens,
            predicate,
            repo,
            side_effect,
        )
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self._index = 0

    def next_values(self) -> tuple[str, int, str]:
        index = self._index
        self._index += 1
        return (
            _pick(self.stdout, index),
            _pick(self.returncode, index),
            _pick(self.stderr, index),
        )


class FakeSubprocess:
    """Fake replacement for subprocess.run, routed by command prefix."""

    def __init__(self) -> None:
        """Initialise empty routing tables and call records."""
        self.commands: list[list[str]] = []
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.strict = False
        self._routes: list[_Route] = []
        self._match_routes: list[_Route] = []

    @property
    def verbs(self) -> list[str]:
        """Return each recorded call's verb tokens, joined by spaces."""
        return [" ".join(_verb_tokens(argv)) for argv in self.commands]

    def on(
        self,
        *tokens: str,
        stdout: str | list[str] = "",
        returncode: int | list[int] = 0,
        stderr: str | list[str] = "",
        repo: str | Path | None = None,
        side_effect: SideEffect | None = None,
    ) -> None:
        """Register a canned response for commands whose verb tokens start with tokens."""
        self._routes.append(
            _Route(list(tokens), None, stdout, returncode, stderr, repo, side_effect)
        )

    def on_match(
        self,
        predicate: Callable[[list[str]], bool],
        *,
        stdout: str | list[str] = "",
        returncode: int | list[int] = 0,
        stderr: str | list[str] = "",
        repo: str | Path | None = None,
        side_effect: SideEffect | None = None,
    ) -> None:
        """Register a canned response for commands matching an arbitrary predicate."""
        self._match_routes.append(
            _Route(None, predicate, stdout, returncode, stderr, repo, side_effect)
        )

    def _resolve(self, argv: list[str]) -> _Route | None:
        for route in reversed(self._match_routes):
            if (
                route.predicate is not None
                and route.predicate(argv)
                and _matches_repo(argv, route.repo)
            ):
                return route
        verb = _verb_tokens(argv)
        best, best_len = None, -1
        for route in self._routes:
            tokens = route.tokens or []
            ok = (
                len(tokens) <= len(verb)
                and verb[: len(tokens)] == tokens
                and _matches_repo(argv, route.repo)
            )
            if ok and len(tokens) >= best_len:
                best, best_len = route, len(tokens)
        return best

    def run(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Replace subprocess.run: record the call and resolve a canned response."""
        self.commands.append(list(argv))
        self.calls.append((list(argv), dict(kwargs)))
        route = self._resolve(argv)
        if route is None:
            if self.strict:
                raise AssertionError(f"fake_subprocess: unrouted command {argv!r}")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if route.side_effect is not None:
            effect = route.side_effect
            if isinstance(effect, BaseException):
                raise effect
            if isinstance(effect, type) and issubclass(effect, BaseException):
                raise effect()
            result = effect(argv, kwargs)
            if result is not None:
                return result
        stdout, returncode, stderr = route.next_values()
        if kwargs.get("check") and returncode != 0:
            raise subprocess.CalledProcessError(
                returncode, argv, output=stdout, stderr=stderr
            )
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    def matching(self, *tokens: str) -> list[list[str]]:
        """Return recorded argvs whose verb tokens start with tokens."""
        wanted = list(tokens)
        return [
            argv
            for argv in self.commands
            if _verb_tokens(argv)[: len(wanted)] == wanted
        ]

    def assert_sequence(self, *expected: str) -> None:
        """Assert the recorded verbs match expected verb prefixes, in order."""
        verbs = self.verbs
        assert len(verbs) == len(expected), (
            f"expected {list(expected)!r}, got {verbs!r}"
        )
        for actual, prefix in zip(verbs, expected, strict=True):
            assert actual.startswith(prefix), (
                f"expected {list(expected)!r}, got {verbs!r}"
            )

    def log_lines(self, *subjects: str) -> str:
        """Return git log --format=%s style output for the given subjects."""
        return "\n".join(subjects) + "\n" if subjects else ""

    def sha_subjects(self, *pairs: tuple[str, str]) -> str:
        """Return git log --format=%h%x09%s style output for the given (sha, subject) pairs."""
        return "".join(f"{sha}\t{subject}\n" for sha, subject in pairs)


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> FakeSubprocess:
    """Patch subprocess.run with a FakeSubprocess instance and return it."""
    fake = FakeSubprocess()
    monkeypatch.setattr(subprocess, "run", fake.run)
    return fake
