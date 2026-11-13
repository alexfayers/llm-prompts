from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from llm_prompts.benchmark import paths
from llm_prompts.benchmark.runner.sandbox import (
    SandboxMissing,
    SandboxPolicy,
    macos_profile,
    remaps_paths,
    require,
    wrap,
)

if TYPE_CHECKING:
    from .conftest import FakeSandbox

POLICY = SandboxPolicy(writable=(Path("/tmp/cell"),), denied_ports=(8000,))


def test_wrap_uses_available_sandbox_and_require_names_opt_out(
    fake_sandbox: FakeSandbox, tmp_path: Path
) -> None:
    with pytest.raises(SandboxMissing, match="--no-os-sandbox"):
        require(True)

    fake_sandbox.present("sandbox-exec")
    profile = macos_profile(POLICY.writable, POLICY.denied_ports)
    assert wrap(["a"], POLICY) == ["sandbox-exec", "-p", profile, "a"]

    fake_sandbox._present.clear()
    fake_sandbox.present("bwrap")
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    argv = wrap(["claude", "-p"], SandboxPolicy(writable=(link,)))
    assert argv[:4] == ["bwrap", "--ro-bind", "/", "/"]
    assert argv[-3:] == ["--", "claude", "-p"]
    assert str(target.resolve()) in argv
    assert str(link) not in argv
    assert "--unshare-net" not in argv


def test_bwrap_mounts_cell_root_at_fixed_path_and_only_linux_remaps(
    fake_sandbox: FakeSandbox, tmp_path: Path
) -> None:
    real, fixed = tmp_path / "real", tmp_path / "fixed"
    real.mkdir()
    fake_sandbox.present("sandbox-exec", "bwrap")
    assert not remaps_paths()
    fake_sandbox._present.discard("sandbox-exec")
    assert remaps_paths()

    argv = wrap(["pi"], SandboxPolicy(writable=(real,), mount=(real, fixed)))

    triples = [argv[i : i + 3] for i in range(len(argv))]
    assert ["--bind", str(real), str(fixed)] in triples
    assert argv[argv.index("--chdir") + 1] == str(fixed / "workspace")


def test_read_only_paths_stay_unwritable_inside_the_writable_temp_dirs(
    fake_sandbox: FakeSandbox, tmp_path: Path
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    policy = SandboxPolicy(writable=(tmp_path,), read_only=(store,))
    fake_sandbox.present("bwrap")

    argv = wrap(["pi"], policy)

    triples = [argv[i : i + 3] for i in range(len(argv))]
    assert argv.index(str(store)) > argv.index(str(tmp_path))
    assert ["--ro-bind", str(store), str(store)] in triples
    profile = macos_profile(policy.writable, policy.denied_ports, policy.read_only)
    assert profile.index(f'(deny file-write* (subpath "{store}"))') > profile.index(
        "(allow file-write*"
    )


def test_host_user_skill_dirs_are_hidden_from_the_cell(
    fake_sandbox: FakeSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths, "live_home", lambda: tmp_path / "host")
    skills = [
        str(tmp_path / "host" / sub) for sub in (".pi/agent/skills", ".claude/skills")
    ]
    for skill in skills:
        Path(skill).mkdir(parents=True)
    fake_sandbox.present("bwrap")

    argv = wrap(["pi"], POLICY)

    for skill in skills:
        assert argv[argv.index(skill) - 1] == "--tmpfs"
        assert argv.index(skill) > argv.index("/")
        assert f'(deny file-read* (subpath "{skill}"))' in macos_profile(
            POLICY.writable, POLICY.denied_ports
        )
    assert str(tmp_path / "host" / ".pi" / "agent") not in argv


def test_absent_host_skill_dirs_are_not_mounted(
    fake_sandbox: FakeSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths, "live_home", lambda: tmp_path / "host")
    (tmp_path / "host" / ".claude" / "skills").mkdir(parents=True)
    fake_sandbox.present("bwrap")

    argv = wrap(["pi"], POLICY)

    assert str(tmp_path / "host" / ".claude" / "skills") in argv
    assert str(tmp_path / "host" / ".pi" / "agent" / "skills") not in argv


def test_skill_dirs_are_not_hidden_when_the_cell_home_is_the_host_home(
    fake_sandbox: FakeSandbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths, "live_home", lambda: tmp_path)
    fake_sandbox.present("bwrap")

    argv = wrap(["pi"], SandboxPolicy(writable=(tmp_path,)))

    assert not any(
        argv[index] == "--tmpfs" and "skills" in argv[index + 1]
        for index in range(len(argv) - 1)
    )
    assert "file-read*" not in macos_profile((tmp_path,), ())


def test_macos_profile_allows_temp_and_writable_and_denies_ports() -> None:
    result = macos_profile([Path('/x/a"b')], [3000])

    assert '(subpath "/private/tmp")' in result
    assert '(subpath "/x/a\\"b")' in result
    assert "(deny file-write*)" in result
    assert '(deny network-outbound (remote tcp "localhost:3000"))' in result
