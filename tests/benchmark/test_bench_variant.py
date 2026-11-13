import importlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeSubprocess

from llm_prompts import setup
from llm_prompts.benchmark import paths
from llm_prompts.benchmark.agents.adapter import VariantBuildError
from llm_prompts.benchmark.cell import variants
from llm_prompts.benchmark.types import WORKTREE, Variant

SHA = "0123456789abcdef0123456789abcdef01234567"
OVERLAY = "git+https://example.invalid/alex-prompts.git"
CONFIG = {
    "tools": [
        {"name": "cline-hooks", "source": "git+https://example.invalid/hooks.git"},
        {"name": "mcp-memory", "source": "git+https://example.invalid/memory.git"},
        {"name": "alex-prompts", "source": OVERLAY},
    ]
}


@pytest.fixture
def repo(
    tmp_path: Path,
    bench_dirs: Any,
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    root = tmp_path / "repo"
    (root / variants.PROMPTS).mkdir(parents=True)
    (root / "tracked.txt").write_text("one")
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: f"/usr/bin/{name}")
    monkeypatch.setattr(setup, "read_config", lambda: CONFIG)
    fake_subprocess.on("rev-parse", stdout=f"{SHA}\n")
    fake_subprocess.on("ls-files", stdout="tracked.txt\0")
    return root


def _build(
    repo: Path,
    ref: str = "main",
    overlays: tuple[str, ...] = ("alex-prompts",),
    tool_sources: dict[str, str] | None = None,
) -> Variant:
    return variants.build("a", ref, ("claude", "pi"), overlays, tool_sources, repo=repo)


def test_overlay_prompts_lists_the_overlays_installed_in_the_variant_venv(
    repo: Path, fake_subprocess: FakeSubprocess
) -> None:
    variant = _build(repo)
    fake_subprocess.on_match(
        lambda argv: argv[:1] == [str(variant.venv / "bin" / "python")],
        stdout='["/venv/overlay/prompts"]\n',
    )

    assert variants.overlay_prompts(variant) == [Path("/venv/overlay/prompts")]


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def test_build_installs_venv_templates_and_guard_then_reuses_cache(
    repo: Path, fake_subprocess: FakeSubprocess
) -> None:
    variant = _build(repo)

    (install,) = fake_subprocess.matching("uv", "pip", "install")
    assert {str(variant.src), "pytest", OVERLAY} <= set(install)
    template = variant.templates["claude"]
    assert any(
        argv[1:4] == ["install", "claude-code", "--root"] and argv[4] == str(template)
        for argv in fake_subprocess.commands
    )
    claude = _json(template / ".claude" / ".claude.json")
    assert claude["mcpServers"]["memory"]["url"] == variants.PLACEHOLDER_MEMORY_URL
    pi_dir = variant.templates["pi"] / ".pi" / "agent"
    hooks = _json(template / ".claude" / "settings.json")["hooks"]["PreToolUse"]
    assert hooks[0]["hooks"][0]["command"].endswith(
        "llm_prompts.benchmark.guard.claude"
    )
    assert (pi_dir / "extensions" / "bench-guard.ts").exists()

    runs = len(fake_subprocess.commands)
    assert _build(repo) == variant
    assert len(fake_subprocess.commands) == runs + 1


def test_build_installs_an_overridden_tool_source_into_its_own_cache(
    repo: Path, fake_subprocess: FakeSubprocess
) -> None:
    override = "git+https://example.invalid/memory-pr.git"
    default = _build(repo)

    variant = _build(repo, tool_sources={"mcp-memory": override})

    install = fake_subprocess.matching("uv", "pip", "install")[-1]
    assert override in install
    assert "git+https://example.invalid/memory.git" not in install
    assert variant.venv != default.venv


def test_only_the_named_overlays_are_installed_each_in_its_own_cache(
    repo: Path, fake_subprocess: FakeSubprocess, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = "git+https://example.invalid/other-prompts.git"
    config = {"tools": [*CONFIG["tools"], {"name": "other-prompts", "source": other}]}
    monkeypatch.setattr(setup, "read_config", lambda: config)

    core = _build(repo, overlays=())
    one = _build(repo, overlays=("other-prompts",))
    both = _build(repo, overlays=("alex-prompts", "other-prompts"))

    core_install, one_install, both_install = fake_subprocess.matching(
        "uv", "pip", "install"
    )
    assert OVERLAY not in core_install + one_install
    assert other not in core_install
    assert other in one_install
    assert OVERLAY in both_install and other in both_install
    assert len({core.venv, one.venv, both.venv}) == 3


def _installed_overlay(
    site: Path, monkeypatch: pytest.MonkeyPatch, name: str, pi_settings: dict[str, Any]
) -> None:
    module = name.replace("-", "_")
    (site / module / "prompts" / "pi").mkdir(parents=True)
    (site / module / "__init__.py").write_text("")
    (site / module / "prompts" / "pi" / "settings.json").write_text(
        json.dumps(pi_settings)
    )
    info = site / f"{module}-0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 0\n")
    (info / "entry_points.txt").write_text(f"[llm_prompts]\n{name} = {module}\n")
    monkeypatch.syspath_prepend(str(site))
    importlib.invalidate_caches()


def test_an_overlay_that_sets_up_the_model_provider_of_an_agent_is_installed_for_it_without_asking(
    repo: Path,
    fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = "git+https://example.invalid/provider-prompts.git"
    config = {
        "tools": [
            *CONFIG["tools"],
            {"name": "provider-prompts", "source": provider},
        ]
    }
    monkeypatch.setattr(setup, "read_config", lambda: config)
    site = tmp_path / "site"
    site.mkdir()
    _installed_overlay(
        site, monkeypatch, "provider-prompts", {"defaultProvider": "custom"}
    )
    _installed_overlay(site, monkeypatch, "alex-prompts", {"packages": []})

    variants.build("a", "main", ("pi",), (), repo=repo)
    variants.build("a", "main", ("claude",), (), repo=repo)

    pi_install, claude_install = fake_subprocess.matching("uv", "pip", "install")
    assert provider in pi_install
    assert OVERLAY not in pi_install
    assert provider not in claude_install


def _local_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = {
        "tools": [
            {"name": name, "source": str(tmp_path / name)}
            for name in ("cline-hooks", "mcp-memory", "alex-prompts")
        ]
    }
    monkeypatch.setattr(setup, "read_config", lambda: config)


def test_a_builds_local_tools_from_their_origin_sha_and_b_from_the_checkout(
    tmp_path: Path, repo: Path, fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    _local_tools(tmp_path, monkeypatch)
    fake_subprocess.on("remote", "get-url", stdout="git@example.invalid:me/hooks.git\n")

    a = variants.build("a", "main", ("pi",), (), None, repo=repo)
    b = variants.build("b", "main", ("pi",), (), None, repo=repo)
    pinned = variants.build("a", "main", ("pi",), (), {"mcp-memory": "/m/a"}, repo=repo)

    installs = fake_subprocess.matching("uv", "pip", "install")
    assert f"git+ssh://git@example.invalid/me/hooks.git@{SHA}" in installs[0]
    assert str(tmp_path / "cline-hooks") in installs[1]
    assert "/m/a" in installs[2]
    assert f"git+ssh://git@example.invalid/me/hooks.git@{SHA}" in installs[2]
    assert len({a.venv, b.venv, pinned.venv}) == 3


def test_a_builds_overlays_from_their_origin_sha_and_prints_the_shas(
    tmp_path: Path, repo: Path, fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    _local_tools(tmp_path, monkeypatch)
    fake_subprocess.on("remote", "get-url", stdout="https://example.invalid/me/t.git\n")

    variants.build("a", "main", ("pi",), ("alex-prompts",), None, repo=repo)
    variants.build("b", "main", ("pi",), ("alex-prompts",), None, repo=repo)

    installs = fake_subprocess.matching("uv", "pip", "install")
    assert f"git+https://example.invalid/me/t.git@{SHA}" in installs[0]
    assert str(tmp_path / "alex-prompts") not in installs[0]
    assert str(tmp_path / "alex-prompts") in installs[1]
    assert (
        f"building a main (cline-hooks@{SHA[:8]}, mcp-memory@{SHA[:8]}, "
        f"alex-prompts@{SHA[:8]})" in capsys.readouterr().err
    )


def test_a_fails_without_an_origin_for_a_tool_it_installs(
    tmp_path: Path, repo: Path, fake_subprocess: FakeSubprocess,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    _local_tools(tmp_path, monkeypatch)
    fake_subprocess.on_match(
        lambda argv: any(arg.startswith("origin/") for arg in argv), returncode=128
    )

    with pytest.raises(VariantBuildError, match="cline-hooks.*no origin/main"):
        variants.build("a", "main", ("pi",), ("alex-prompts",), None, repo=repo)


def test_build_id_exists_only_when_every_tool_source_is_pinned(repo: Path) -> None:
    pinned = {
        "cline-hooks": f"git+https://example.invalid/hooks.git@{SHA}",
        "mcp-memory": f"git+https://example.invalid/memory.git@{SHA}",
        "alex-prompts": f"git+https://example.invalid/alex.git@{SHA}",
    }

    assert _build(repo).build is None
    assert _build(repo, tool_sources=pinned).build is not None


def test_build_id_follows_the_built_content_not_where_or_from_what_state_it_was_built(
    repo: Path, fake_subprocess: FakeSubprocess, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = {"text": "one"}

    def install(argv: list[str], kwargs: dict[str, Any]) -> None:
        venv = Path(argv[argv.index("--python") + 1]).parents[1]
        site = venv / "lib" / "python3" / "site-packages"
        (site / "tool" / "prompts").mkdir(parents=True, exist_ok=True)
        (site / "tool" / "code.py").write_text(code["text"])
        (site / "tool" / "prompts" / "p.md").write_text(str(venv))
        (site / "tool-1.dist-info").mkdir(exist_ok=True)
        (site / "tool-1.dist-info" / "RECORD").write_text(str(venv))

    def render(argv: list[str], kwargs: dict[str, Any]) -> None:
        root = Path(argv[argv.index("--root") + 1])
        (root / ".config").mkdir(parents=True, exist_ok=True)
        (root / ".config" / "installed.json").write_text(f"{root} {time.time()}")
        (root / "prompt.md").write_text(f"rules at {root}")

    fake_subprocess.on("uv", "pip", "install", side_effect=install)
    fake_subprocess.on_match(lambda argv: "--root" in argv, side_effect=render)

    def build(state: str) -> Variant:
        monkeypatch.setattr(setup, "source_state", lambda location: state)
        return _build(repo)

    first = build("checkout state one")
    elsewhere = build("checkout state two")
    code["text"] = "two"
    changed = build("checkout state three")

    assert elsewhere.venv != first.venv
    assert elsewhere.build == first.build
    assert changed.build != first.build


def test_build_worktree_keys_on_content(repo: Path) -> None:
    first = _build(repo, WORKTREE)
    (repo / "tracked.txt").write_text("changed")
    second = _build(repo, WORKTREE)

    assert first.key.startswith("worktree-") and first.key != second.key
    assert (second.src / "tracked.txt").read_text() == "changed"


def test_build_fails_on_unknown_ref_and_live_path_in_template(
    repo: Path, fake_subprocess: FakeSubprocess
) -> None:
    def leak(
        argv: list[str], kwargs: dict[str, Any]
    ) -> subprocess.CompletedProcess[str] | None:
        root = Path(argv[argv.index("--root") + 1]) / "leak.json"
        root.parent.mkdir(parents=True, exist_ok=True)
        root.write_text(str(Path.home() / ".claude"))
        return None

    fake_subprocess.on_match(lambda argv: "--root" in argv, side_effect=leak)
    with pytest.raises(VariantBuildError, match="leak.json"):
        _build(repo)

    fake_subprocess.on("rev-parse", returncode=128, stderr="bad revision")
    with pytest.raises(VariantBuildError, match="ref not found"):
        _build(repo, "nope")


def test_prune_keeps_only_the_newest_build_of_each_ref_and_the_current_variants(
    repo: Path,
) -> None:
    def age(variant: Variant, seconds: int) -> None:
        marker = variant.venv.parent / variants.REF_MARKER
        os.utime(marker, (time.time() - seconds, time.time() - seconds))

    old = _build(repo, "main", tool_sources={"mcp-memory": "/m/1"})
    newest = _build(repo, "main", tool_sources={"mcp-memory": "/m/2"})
    other = _build(repo, "other", tool_sources={"mcp-memory": "/m/3"})
    for variant, seconds in ((old, 30), (newest, 20), (other, 10)):
        age(variant, seconds)
    legacy = paths.variant_dir("legacy-overlays-12345678")
    legacy.mkdir(parents=True)
    unused_src = paths.variant_dir("legacy")
    unused_src.mkdir()

    variants.prune([old])

    assert [variant.venv.parent.exists() for variant in (old, newest, other)] == [
        True,
        True,
        True,
    ]
    assert not legacy.exists() and not unused_src.exists()
    assert newest.src.exists()

    variants.prune([])

    assert [variant.venv.parent.exists() for variant in (old, newest, other)] == [
        False,
        True,
        True,
    ]


def _pollute(template: Path) -> Path:
    polluted = template / ".config" / "tool.json"
    polluted.parent.mkdir(parents=True, exist_ok=True)
    polluted.write_text(
        f'{{"home": "{paths.work_dir()}/{paths.CELL_ROOT_PREFIX}1-abc/home"}}'
    )
    return polluted


def test_a_cached_build_whose_template_names_a_cell_home_is_rebuilt(
    repo: Path, fake_subprocess: FakeSubprocess
) -> None:
    variant = _build(repo)
    polluted = _pollute(variant.templates["pi"])

    _build(repo)

    assert not polluted.exists()


def test_a_fresh_build_whose_template_names_a_cell_home_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = variants.template

    def polluting(venv_dir: Path, agent: str, template_dir: Path) -> Path:
        _pollute(install(venv_dir, agent, template_dir))  # type: ignore[arg-type]
        return template_dir

    monkeypatch.setattr(variants, "template", polluting)

    with pytest.raises(VariantBuildError, match="cell home"):
        _build(repo)
