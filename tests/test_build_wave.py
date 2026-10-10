"""Tests for the eagle-vision skill's build-wave workflow script."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")

_COLLECT_STUB = """\
import runpy
import subprocess
import sys
from pathlib import Path

REAL = {real!r}
if sys.argv[1] == "collect":
    lib = runpy.run_path(REAL, run_name="focus_lib")
    path = lib["find_node_path"](Path(sys.argv[2]), sys.argv[3])
    command = lib["node_test_command"](path.read_text())
    sys.exit(subprocess.run(command, shell=True, check=False).returncode)
sys.argv[0] = REAL
runpy.run_path(REAL, run_name="__main__")
"""


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
        """Run the focus script on the plan."""
        return subprocess.run(
            [
                sys.executable,
                str(self.skill / "focus.py"),
                args[0],
                str(self.plan),
                *args[1:],
            ],
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

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

    def commit_on_main(self, subject: str, files: dict[str, str]) -> None:
        """Commit files straight onto main."""
        for rel, content in files.items():
            (self.repo / rel).write_text(content)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", subject)

    def finish_by_hand(self, name: str, files: dict[str, str]) -> None:
        """Leave a node passed in nodes/done with uncommitted files in its worktree."""
        worktree = self.worktree(f"ev1-{name}")
        self.git("worktree", "add", "-q", "-b", f"ev/ev1-{name}", str(worktree), "main")
        for rel, content in files.items():
            (worktree / rel).parent.mkdir(parents=True, exist_ok=True)
            (worktree / rel).write_text(content)
        for step in ("start", "built", "pass"):
            self.focus(step, name)

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


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A repo on main with one lint finding and an untracked empty plan with a Checks entry."""
    root = tmp_path.resolve()
    env = os.environ | {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    proj = Project(root, env)
    (root / "repo" / "src").mkdir(parents=True)
    proj.git("init", "-q", "-b", "main")
    (proj.repo / ".git" / "info" / "exclude").write_text("/plan/\n")
    (proj.repo / "src" / "old.txt").write_text("a\nLINT old\n")
    proj.git("add", "-A")
    proj.git("commit", "-q", "-m", "initial")
    proj.skill.mkdir()
    (proj.skill / "focus.py").write_text(
        _COLLECT_STUB.format(real=str(_SKILL / "focus.py"))
    )
    proj.focus("init")
    plan_file = proj.plan / "PLAN.md"
    plan_file.write_text(
        plan_file.read_text().replace("## Checks\n", "## Checks\n\n- true\n", 1)
    )
    return proj


_LINT_SH = """\
ev_lint() {
  local p out
  p=$(ev_worktree_paths "$1" "$2" | head -n 1 | cut -d' ' -f2)
  out=$(grep -Hn LINT "$p"/src/*.txt | sed -E 's/^([^:]+):([0-9]+):/\\1:\\2: /')
  [ -z "$out" ] && return 0
  echo "$out"
  return 1
}
"""


class TestBuildWave:
    """Tests for one wave of the generic build workflow."""

    def test_one_ready_node_lands_one_commit_on_main(self, project: Project) -> None:
        project.add_node("alpha")
        project.focus("join")
        before = int(project.git("rev-list", "--count", "main"))
        out = project.run()
        assert out["result"]["escalations"] == []
        assert out["result"]["nextWaveSafe"] is True
        assert int(project.git("rev-list", "--count", "main")) == before + 1
        assert project.git("log", "-1", "--format=%s", "main") == "feat: alpha"
        assert (project.plan / "nodes" / "done" / "alpha.md").exists()
        assert not project.worktree("ev1-alpha").exists()

    def test_build_sh_sets_target_branch_and_subject(self, project: Project) -> None:
        project.add_node("alpha")
        project.focus("join")
        project.git("branch", "release")
        project.git("checkout", "-q", "release")
        project.build_sh(
            'EV_TARGET=release\nev_subject() { echo "chore: custom $1"; }\n'
        )
        main_tip = project.git("rev-parse", "main")
        out = project.run()
        assert out["result"]["escalations"] == []
        assert (
            project.git("log", "-1", "--format=%s", "release") == "chore: custom alpha"
        )
        assert project.git("rev-parse", "main") == main_tip

    def test_existing_lint_finding_that_only_moves_passes_the_gate(
        self, project: Project
    ) -> None:
        project.build_sh(_LINT_SH)
        project.add_node(
            "alpha", ["tests/test_alpha.py", "src/alpha.txt", "src/old.txt"]
        )
        project.focus("join")
        moved = {"src/alpha.txt": "impl\n", "src/old.txt": "x\ny\na\nLINT old\n"}
        out = project.run({"impl": {"alpha": {"files": moved}}})
        assert out["result"]["escalations"] == []
        assert out["result"]["passed"] == ["alpha"]

    def test_new_lint_finding_escalates_the_node_and_merges_nothing(
        self, project: Project
    ) -> None:
        project.build_sh(_LINT_SH)
        project.add_node("alpha")
        project.focus("join")
        main_tip = project.git("rev-parse", "main")
        out = project.run(
            {"impl": {"alpha": {"files": {"src/alpha.txt": "LINT fresh\n"}}}}
        )
        (escalation,) = out["result"]["escalations"]
        assert escalation["what"] == "alpha"
        assert "LINT fresh" in escalation["reason"]
        assert project.git("rev-parse", "main") == main_tip

    def test_resume_merges_a_node_built_before_the_target_moved(
        self, project: Project
    ) -> None:
        project.add_node("alpha")
        project.focus("join")
        project.finish_by_hand(
            "alpha", {"tests/test_alpha.py": "ok\n", "src/alpha.txt": "impl\n"}
        )
        project.commit_on_main("unrelated", {"other.txt": "other\n"})
        out = project.run(resume=True)
        assert out["result"]["escalations"] == []
        assert project.git("log", "--format=%s", "-3", "main").splitlines() == [
            "feat: alpha",
            "unrelated",
            "initial",
        ]

    def test_resume_escalates_a_node_whose_uncommitted_changes_overlap_the_target(
        self, project: Project
    ) -> None:
        project.add_node(
            "alpha", ["tests/test_alpha.py", "src/alpha.txt", "src/old.txt"]
        )
        project.focus("join")
        project.finish_by_hand(
            "alpha", {"tests/test_alpha.py": "ok\n", "src/old.txt": "node change\n"}
        )
        project.commit_on_main("main change", {"src/old.txt": "main change\n"})
        main_tip = project.git("rev-parse", "main")
        out = project.run(resume=True)
        (escalation,) = out["result"]["escalations"]
        assert escalation["what"] == "alpha"
        assert "local changes overlap" in escalation["reason"]
        assert project.git("rev-parse", "main") == main_tip

    def test_failed_probe_escalates_every_node_of_the_dir_without_merging(
        self, project: Project
    ) -> None:
        project.build_sh('ev_build() { [ "$2" = . ] && return 1; return 0; }\n')
        for name in ("alpha", "beta"):
            project.add_node(name)
        project.focus("join")
        out = project.run()
        assert {e["what"] for e in out["result"]["escalations"]} == {"alpha", "beta"}
        assert all(
            "feasibility probe failed" in e["reason"]
            for e in out["result"]["escalations"]
        )
        assert not [c for c in out["calls"] if c["label"].startswith("merge")]

    def test_plan_defect_triage_escalates_and_blocks_the_next_wave(
        self, project: Project
    ) -> None:
        project.build_sh("ev_wave_build() { return 1; }\n")
        project.add_node("alpha")
        project.focus("join")
        defect = {
            "dir": "workspace",
            "test": "build",
            "kind": "plan-defect",
            "laterNode": "beta",
            "fix": "beta Scope",
        }
        out = project.run({"triage": {"failures": [defect]}})
        (escalation,) = out["result"]["escalations"]
        assert escalation["what"] == "beta"
        assert "plan-defect" in escalation["reason"]
        assert out["result"]["nextWaveSafe"] is False

    def test_probe_worktree_lives_until_the_last_wave_finishes(
        self, project: Project
    ) -> None:
        project.add_node("alpha")
        project.add_node("beta", depends=["alpha"])
        project.focus("join")
        assert project.run()["result"]["escalations"] == []
        assert project.worktree("ev-probe").exists()
        assert project.run(wave=2, stamp="t2")["result"]["escalations"] == []
        assert not project.worktree("ev-probe").exists()

    @pytest.mark.parametrize("missing", ["plan", "skill", "stamp"])
    def test_missing_plan_skill_or_stamp_throws(
        self, project: Project, missing: str
    ) -> None:
        out = project.run(**{missing: None})
        assert "args must be" in out["error"]

    def test_tests_the_command_does_not_select_get_one_more_attempt_then_escalate(
        self, project: Project
    ) -> None:
        project.add_node("alpha")
        project.focus("join")
        out = project.run(
            {"tests": {"alpha": {"files": {"tests/test_alpha.py": "nothing\n"}}}}
        )
        writers = [
            c
            for c in out["calls"]
            if c["label"].startswith("tests")
            and not c["label"].startswith("testscheck")
        ]
        assert len(writers) == 2
        assert "collect.log" in writers[1]["prompt"]
        (escalation,) = out["result"]["escalations"]
        assert escalation["what"] == "alpha"
        assert not [c for c in out["calls"] if c["label"].startswith("impl")]
