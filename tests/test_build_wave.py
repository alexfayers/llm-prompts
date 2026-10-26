"""Tests for the eagle-vision skill's build-wave workflow script."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import redirect_stdout
from dataclasses import dataclass
from functools import cache
from itertools import takewhile
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import pytest

_SKILL = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "shared"
    / "skills"
    / "eagle-vision"
)
_HARNESS = Path(__file__).parent / "build_wave_harness.mjs"

pytestmark = [
    pytest.mark.skipif(shutil.which("node") is None, reason="node missing"),
    pytest.mark.real_io,
]


@cache
def _focus_module() -> ModuleType:
    """The focus script, loaded once so setup calls run in-process."""
    spec = importlib.util.spec_from_file_location("focus", _SKILL / "focus.py")
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class Project:
    """A target repo, a plan dir and a skill dir built in a temp dir."""

    root: Path
    env: dict[str, str]

    @property
    def repo(self) -> Path:
        """The target repo's main checkout."""
        return self.root / "repo"

    @property
    def plan(self) -> Path:
        """The plan dir."""
        return self.repo / "plan"

    @property
    def skill(self) -> Path:
        """The skill dir holding the focus wrapper."""
        return self.root / "skill"

    def worktree(self, name: str) -> Path:
        """The default checkout path of a worktree."""
        return self.root / "repo-ev" / name

    def git(self, *args: str, cwd: Path | None = None) -> str:
        """Run git in the repo (or cwd) and return its stripped output."""
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def focus(self, *args: str) -> str:
        """Run a focus command on the plan in this process, returning its stdout."""
        command, *rest = args
        focus = _focus_module()
        parsed = focus.build_parser().parse_args([command, str(self.plan), *rest])
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, self.env), redirect_stdout(stdout):
            focus.run_command(parsed)
        return stdout.getvalue()

    def add_node(
        self,
        name: str,
        scope: list[str] | None = None,
        depends: list[str] | None = None,
    ) -> None:
        """Add a node whose test command selects its test file once that says ok."""
        self.focus(
            "add",
            name,
            "--scope",
            *(scope or [f"tests/test_{name}.py", f"src/{name}.txt"]),
        )
        if depends:
            self.focus("link", name, "--depends", *depends)
        self.focus("set-test", name, f"grep -q ok tests/test_{name}.py")

    def commit_on_checkout(self, subject: str, files: dict[str, str]) -> None:
        """Commit files straight onto the repo's checked-out branch."""
        for rel, content in files.items():
            (self.repo / rel).write_text(content)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", subject)

    def build_sh(self, text: str) -> None:
        """Write the plan's build.sh."""
        (self.plan / "build.sh").write_text(text)

    def run(
        self, scenario: dict[str, Any] | None = None, **args: Any
    ) -> dict[str, Any]:
        """Run the workflow script in the harness, returning its JSON output."""
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "script": str(_SKILL / "build-wave.js"),
                    "args": {
                        key: value
                        for key, value in {
                            "plan": str(self.plan),
                            "skill": str(self.skill),
                            "wave": 1,
                            "stamp": "t1",
                            **args,
                        }.items()
                        if value is not None
                    },
                    "scenario": scenario or {},
                }
            )
        )
        done = subprocess.run(
            ["node", str(_HARNESS), str(config)],
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )
        output: dict[str, Any] = json.loads(done.stdout)
        assert output["errors"] == []
        return output


_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.fsync",
    "GIT_CONFIG_VALUE_0": "none",
}
_POLL_SECONDS = 0.02
_IDLE_SAMPLE = "0 0 0 0 0 20"


@pytest.fixture(scope="session")
def fast_bin_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A bin dir with a quick `sleep` and an instant `iostat`, so the scripts' waits and CPU sampling return promptly."""
    real_sleep = shutil.which("sleep")
    bin_dir = tmp_path_factory.mktemp("bin")
    shims = {
        "sleep": f"exec {real_sleep} {_POLL_SECONDS}",
        "iostat": f"echo '{_IDLE_SAMPLE}'",
    }
    for name, body in shims.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)
    return bin_dir


@pytest.fixture(scope="session")
def template_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repo on main with one lint finding and an untracked empty plan with a Checks entry."""
    root = tmp_path_factory.mktemp("template").resolve()
    proj = Project(root, os.environ | _GIT_ENV)
    (root / "repo" / "src").mkdir(parents=True)
    proj.git("init", "-q", "-b", "main")
    (proj.repo / ".git" / "info" / "exclude").write_text("/plan/\n")
    (proj.repo / "src" / "old.txt").write_text("a\nLINT old\n")
    proj.git("add", "-A")
    proj.git("commit", "-q", "-m", "initial")
    proj.focus("init")
    plan_file = proj.plan / "PLAN.md"
    plan_file.write_text(
        plan_file.read_text().replace("## Checks\n", "## Checks\n\n- true\n", 1)
    )
    return root


@pytest.fixture
def project(tmp_path: Path, template_root: Path, fast_bin_dir: Path) -> Project:
    """A fresh copy of the template repo and plan."""
    root = tmp_path.resolve()
    shutil.copytree(template_root, root, symlinks=True, dirs_exist_ok=True)
    env = os.environ | _GIT_ENV
    env["PATH"] = f"{fast_bin_dir}{os.pathsep}{env['PATH']}"
    return Project(root, env)


_SHA = "a" * 40
_STUBBED_LABELS = ("scout", "probe", "testscheck1", "checks", "cleanup-probes")
_PROBE_STEPS = ["add", "sync", "deps", "build", "smoke", "baseline"]


@pytest.fixture
def bare(tmp_path: Path) -> Project:
    """A project of paths only: no repo, plan or skill on disk, for runs whose shell is scripted."""
    return Project(tmp_path.resolve(), dict(os.environ))


def seed_lint_baseline(project: Project, target: str) -> None:
    """Record the clean lint baseline the stubbed probe would have left for the repo at `target`."""
    fingerprint = subprocess.run(
        ["git", "hash-object", "--stdin"],
        input=f". {project.git('rev-parse', target)}\n",
        env=project.env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    baseline = Path(f"/tmp/eagle-vision{project.plan}/lint-base")
    baseline.mkdir(parents=True)
    (baseline / f"{fingerprint}.rc").write_text("0\n")
    (baseline / f"{fingerprint}.txt").write_text("")


def scripted_shell(
    project: Project,
    *nodes: str,
    wave: int = 1,
    earlier: tuple[str, ...] = (),
    last: bool = True,
    **replies: list[str],
) -> dict[str, Any]:
    """Marker lines the runner scripts of a green wave print, with `replies` overriding by label."""
    logs = f"{project.root}/logs"
    names = {node: f"ev{wave}-{node}" for node in nodes}
    shell = {
        "scout": [
            *(f"PRE_OK {node}" for node in earlier),
            *(f"NODE {node} ready todo" for node in nodes),
            "SCOUT_CPUS 8",
            "SCOUT_DIRS .",
            *(["SCOUT_LAST"] if last else []),
            "SCOUT_END",
        ],
        "probe": [f"GATE_STEP {step}" for step in _PROBE_STEPS],
        "testscheck1": ["TESTS_COLLECTED"],
        "gate1": [f"GATE_PASS {_SHA}"],
        "merge1": [
            "MERGE_TARGET main",
            *(f"MERGED {node} {_SHA}" for node in nodes),
            "MERGE_STEP join",
            "MERGE_STEP pkg-.",
        ],
        "checks": [
            f"CHECK_OK workspace {logs}/wave.log",
            f"CHECK_OK . {logs}/root.log",
        ],
        "cleanup": [
            *(f"REMOVE {name}" for name in names.values()),
            *(f"CLEANUP_STEP {name}" for name in names.values()),
        ],
        "cleanup-probes": ["REMOVE ev-probe", "CLEANUP_STEP ev-probe"],
        **{
            f"setup:{node}": [
                f"ROW {name} . {project.root}/repo-ev/{name} ev/{name} {_SHA} {_SHA} 0 0"
            ]
            for node, name in names.items()
        },
    }
    return {"shell": shell | replies}


_GATE_GIT = """\
#!/bin/sh
case "$1" in
  rev-parse) echo 0123456789abcdef0123456789abcdef01234567 ;;
  hash-object) cat > /dev/null; echo fingerprint ;;
esac
"""
_GATE_FOCUS = """\
import sys
from pathlib import Path

with Path(sys.argv[0]).with_name("calls.txt").open("a") as calls:
    calls.write(" ".join(sys.argv[2:]) + "\\n")
"""
_GATE_BUILD_SH = """\
ev_repo() { echo "{root}/repo"; }
ev_worktree_paths() { echo "$2 {root}/wt/$1"; }
ev_lint() { local out="{root}/lint-$1.out"; cat "$out"; [ ! -s "$out" ]; }
"""


@dataclass
class GateShell:
    """The real probe and gate scripts of a node, run against stubbed git and focus.py."""

    project: Project
    scripts: dict[str, Path]
    env: dict[str, str]

    def lint(
        self, step: str, script: str, findings: list[str]
    ) -> subprocess.CompletedProcess[str]:
        """Run one lint arm of `script` in a worktree whose linter prints `findings`."""
        name = "ev-probe" if script == "probe" else "ev1-alpha"
        (self.project.root / f"lint-{name}.out").write_text(
            "".join(
                f"{self.project.root}/wt/{name}/{finding}\n" for finding in findings
            )
        )
        return subprocess.run(
            ["bash", str(self.scripts[script]), step],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
        )

    @property
    def focus_calls(self) -> list[str]:
        """The arguments of every `focus.py` call the scripts made."""
        calls = self.project.skill / "calls.txt"
        return calls.read_text().splitlines() if calls.exists() else []


def _runner_script(prompt: str) -> str:
    """The shell script a runner prompt tells the runner to write."""
    return prompt[prompt.index("\n\n", prompt.index("3. Read")) + 2 :]


@pytest.fixture
def gate_shell(bare: Project) -> Iterator[GateShell]:
    """The probe and gate scripts of one node, written out with stubs for git, focus.py and the linter."""
    calls = bare.run(scripted_shell(bare, "alpha"))["calls"]
    scripts: dict[str, Path] = {}
    for name, label in (("probe", "probe"), ("gate", "gate1")):
        (call,) = [c for c in calls if c["label"].startswith(label)]
        scripts[name] = bare.root / f"{name}.sh"
        scripts[name].write_text(_runner_script(call["prompt"]))
    bin_dir = bare.root / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(_GATE_GIT)
    (bin_dir / "git").chmod(0o755)
    bare.skill.mkdir()
    (bare.skill / "focus.py").write_text(_GATE_FOCUS)
    bare.plan.mkdir(parents=True)
    bare.build_sh(_GATE_BUILD_SH.replace("{root}", str(bare.root)))
    logs = Path(f"/tmp/eagle-vision{bare.plan}/wave-1/t1")
    logs.mkdir(parents=True)
    for name in ("ev-probe", "ev1-alpha"):
        (bare.root / "wt" / name).mkdir(parents=True)
    env = bare.env | {"PATH": f"{bin_dir}{os.pathsep}{bare.env['PATH']}"}
    yield GateShell(bare, scripts, env)
    shutil.rmtree(f"/tmp/eagle-vision{bare.plan}")


class TestBuildWave:
    """Tests for one wave of the generic build workflow."""

    def test_ready_node_lands_on_the_build_sh_target_and_one_overlapping_the_moved_target_escalates(
        self, project: Project
    ) -> None:
        project.add_node("alpha")
        project.add_node("beta", ["tests/test_beta.py", "src/old.txt"])
        project.focus("join")
        project.git("branch", "release")
        project.git("checkout", "-q", "release")
        project.build_sh(
            'EV_TARGET=release\nev_subject() { echo "chore: custom $1"; }\n'
        )
        project.git(
            "worktree",
            "add",
            "-q",
            "-b",
            "ev/ev1-beta",
            str(project.worktree("ev1-beta")),
        )
        (project.worktree("ev1-beta") / "src" / "old.txt").write_text("node change\n")
        project.commit_on_checkout("unrelated", {"other.txt": "other\n"})
        project.commit_on_checkout("main change", {"src/old.txt": "main change\n"})
        main_tip = project.git("rev-parse", "main")
        seed_lint_baseline(project, "release")
        stubbed = scripted_shell(project, "alpha", "beta")["shell"]
        out = project.run(
            {"stub": {k: stubbed[k] for k in _STUBBED_LABELS}}, skill=str(_SKILL)
        )
        (escalation,) = out["result"]["escalations"]
        assert "local changes overlap release" in escalation["reason"]
        assert project.git("log", "--format=%s", "-4", "release").splitlines() == [
            "chore: custom alpha",
            "main change",
            "unrelated",
            "initial",
        ]
        assert project.git("show", "release:src/old.txt") == "main change"
        assert project.git("rev-parse", "main") == main_tip
        assert (project.plan / "nodes" / "done" / "alpha.md").exists()
        assert not project.worktree("ev1-alpha").exists()

    def test_node_whose_worktree_overlaps_the_moved_target_escalates_and_the_other_node_lands(
        self, bare: Project
    ) -> None:
        shell = scripted_shell(bare, "alpha", "beta")
        shell["shell"] |= {
            "merge1": [
                "MERGE_TARGET release",
                f"MERGED alpha {_SHA}",
                "MERGE_STEP join",
                "MERGE_STEP pkg-.",
            ],
            "setup:beta": [
                "SYNC_FAIL . local changes overlap release",
                f"ROW ev1-beta . {bare.root}/repo-ev/ev1-beta ev/ev1-beta {_SHA} {_SHA} 1 0",
            ],
        }
        out = bare.run(shell)
        assert "error" not in out
        (escalation,) = out["result"]["escalations"]
        assert escalation["what"] == "beta"
        assert "local changes overlap release" in escalation["reason"]
        assert out["result"]["passed"] == ["alpha"]
        assert out["result"]["nextWaveSafe"] is False
        labels = [c["label"] for c in out["calls"]]
        assert not [
            label
            for label in labels
            if label.endswith(":beta") and not label.startswith("setup")
        ]

    def test_default_target_is_main_and_default_subject_is_a_conventional_commit(
        self, bare: Project, tmp_path: Path
    ) -> None:
        out = bare.run(scripted_shell(bare, "alpha"))
        assert out["result"]["escalations"] == []
        assert out["result"]["nextWaveSafe"] is True
        (gate,) = [c for c in out["calls"] if c["label"] == "gate1:alpha"]
        prelude = "\n".join(
            takewhile(
                lambda l: not l.startswith("ev_keep()"),
                _runner_script(gate["prompt"]).splitlines(),
            )
        )
        (tmp_path / "prelude.sh").write_text(prelude)
        subjects = subprocess.run(
            [
                "bash",
                "-c",
                '. prelude.sh; echo "$EV_TARGET"; ev_subject alpha; ev_subject fix-x; ev_subject pkg/fix-y; ev_subject pkg/z',
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        assert subjects == [
            "main",
            "feat: alpha",
            "fix: fix-x",
            "fix(pkg): fix-y",
            "feat(pkg): z",
        ]

    def test_existing_lint_finding_that_only_moves_passes_the_gate(
        self, gate_shell: GateShell
    ) -> None:
        gate_shell.lint("run-baseline", "probe", ["src/old.txt:2: LINT old"])
        done = gate_shell.lint("run-lint", "gate", ["src/old.txt:4: LINT old"])
        assert done.returncode == 0
        assert "GATE_STEP lint" in done.stdout
        assert "GATE_FAIL" not in done.stdout
        assert gate_shell.focus_calls == []

    def test_new_lint_finding_fails_the_node_with_the_finding_as_detail(
        self, gate_shell: GateShell
    ) -> None:
        gate_shell.lint("run-baseline", "probe", ["src/old.txt:2: LINT old"])
        done = gate_shell.lint(
            "run-lint",
            "gate",
            ["src/old.txt:2: LINT old", "src/alpha.txt:1: LINT fresh"],
        )
        assert done.returncode == 1
        assert "GATE_FAIL lint: new findings" in done.stdout
        assert "GATE_DETAIL src/alpha.txt: LINT fresh" in done.stdout
        assert "GATE_DETAIL src/old.txt" not in done.stdout
        assert gate_shell.focus_calls == [
            f"{gate_shell.project.plan} alpha lint: new findings"
        ]

    def test_gate_failures_escalate_the_node_and_merge_nothing(
        self, bare: Project
    ) -> None:
        failure = [
            "GATE_FAIL lint: new findings /logs/alpha-lint.new",
            "GATE_DETAIL src/alpha.txt: LINT fresh",
        ]
        out = bare.run(
            scripted_shell(bare, "alpha", gate1=failure, gate2=failure, gate3=failure)
        )
        assert "error" not in out
        (escalation,) = out["result"]["escalations"]
        assert escalation["what"] == "alpha"
        assert "LINT fresh" in escalation["reason"]
        assert not [c for c in out["calls"] if c["label"].startswith("merge")]

    @pytest.mark.parametrize(
        ("state", "row", "escalation"),
        [
            ("done", f"ROW alpha . /wt ev/ev1-alpha {_SHA} {_SHA} 1 0", None),
            ("done", f"ROW alpha . /wt ev/ev1-alpha {_SHA} {_SHA} 1 2", "still dirty"),
            ("done", f"ROW alpha . /wt ev/ev1-alpha {_SHA} {_SHA} 0 0", "no commit"),
            ("todo", "NO_WORKTREE ev1-alpha", "worktree missing"),
            ("done", "NO_WORKTREE ev1-alpha", None),
        ],
    )
    def test_resume_merges_a_done_node_without_rebuilding_it(
        self, bare: Project, state: str, row: str, escalation: str | None
    ) -> None:
        shell = scripted_shell(bare, "alpha")
        shell["shell"] |= {
            "scout": [f"NODE alpha ready {state}", "SCOUT_END"],
            "resume:alpha": [row],
        }
        out = bare.run(shell, resume=True)
        assert "error" not in out
        labels = [c["label"].split(":")[0] for c in out["calls"]]
        assert not {"setup", "tests1", "impl"} & set(labels)
        landed = escalation is None and "ROW" in row
        assert {"gate1", "merge1"} <= set(labels) if landed else "merge1" not in labels
        reasons = [e["reason"] for e in out["result"]["escalations"]]
        assert (not reasons) if escalation is None else (escalation in reasons[0])

    def test_failed_probe_escalates_every_node_of_the_dir_without_merging(
        self, bare: Project
    ) -> None:
        out = bare.run(
            scripted_shell(
                bare, "alpha", "beta", probe=["GATE_FAIL build failed /logs/probe.log"]
            )
        )
        assert "error" not in out
        assert {e["what"] for e in out["result"]["escalations"]} == {"alpha", "beta"}
        assert all(
            "feasibility probe failed" in e["reason"]
            for e in out["result"]["escalations"]
        )
        assert not [c for c in out["calls"] if c["label"].startswith("merge")]

    def test_plan_defect_triage_escalates_and_blocks_the_next_wave(
        self, bare: Project
    ) -> None:
        defect = {
            "dir": "workspace",
            "test": "build",
            "kind": "plan-defect",
            "laterNode": "beta",
            "fix": "beta Scope",
        }
        shell = scripted_shell(
            bare,
            "alpha",
            checks=[
                "CHECK_FAIL workspace /logs/wave.log",
                "CHECK_OK . /logs/root.log",
            ],
        )
        out = bare.run(shell | {"triage": {"failures": [defect]}})
        assert "error" not in out
        (escalation,) = out["result"]["escalations"]
        assert escalation["what"] == "beta"
        assert "plan-defect" in escalation["reason"]
        assert out["result"]["nextWaveSafe"] is False

    def test_probe_worktree_lives_until_the_last_wave_finishes(
        self, bare: Project
    ) -> None:
        first = bare.run(scripted_shell(bare, "alpha", last=False))
        assert "error" not in first
        assert first["result"]["escalations"] == []
        assert not [
            c for c in first["calls"] if c["label"].startswith("cleanup-probes")
        ]
        second = bare.run(
            scripted_shell(bare, "beta", wave=2, earlier=("alpha",)),
            wave=2,
            stamp="t2",
        )
        assert "error" not in second
        assert second["result"]["escalations"] == []
        (cleanup,) = [
            c for c in second["calls"] if c["label"].startswith("cleanup-probes")
        ]
        assert "ev_worktree_remove" in cleanup["prompt"]
        assert "ev-probe)" in cleanup["prompt"]

    @pytest.mark.parametrize("missing", ["plan", "skill", "stamp"])
    def test_missing_plan_skill_or_stamp_throws(
        self, bare: Project, missing: str
    ) -> None:
        out = bare.run(**{missing: None})
        assert "args must be" in out["error"]

    def test_tests_the_command_does_not_select_get_one_more_attempt_then_escalate(
        self, bare: Project
    ) -> None:
        shell = scripted_shell(
            bare,
            "alpha",
            testscheck1=["TESTS_EMPTY /logs/tests-1-collect.log"],
            testscheck2=["TESTS_EMPTY /logs/tests-2-collect.log"],
        )
        out = bare.run(shell | {"tests": {"alpha": {"files": {}}}})
        assert "error" not in out
        writers = [
            c
            for c in out["calls"]
            if c["label"].startswith("tests")
            and not c["label"].startswith("testscheck")
        ]
        assert len(writers) == 2
        assert "/logs/tests-1-collect.log" in writers[1]["prompt"]
        (escalation,) = out["result"]["escalations"]
        assert escalation["what"] == "alpha"
        assert not [c for c in out["calls"] if c["label"].startswith("impl")]
