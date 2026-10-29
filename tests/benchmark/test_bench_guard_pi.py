import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

GUARD_TS = Path(__file__).parents[2] / "src/llm_prompts/benchmark/guard/pi.ts"
DRIVER = """\
const extension = (await import(process.env.GUARD_TS)).default;
const handlers = {};
extension({ on: (name, handler) => { handlers[name] = handler; } });
const event = JSON.parse(process.env.GUARD_EVENT);
console.log(JSON.stringify((await handlers.tool_call(event, {})) ?? null));
"""
RECORDER = (
    "import sys, pathlib; pathlib.Path(sys.argv[1]).write_text(sys.stdin.read());"
    "sys.stderr.write(sys.argv[3]); raise SystemExit(int(sys.argv[2]))"
)


def _node_supported() -> bool:
    node = shutil.which("node")
    out = subprocess.run(
        [node or "false", "--version"], check=False, capture_output=True, text=True
    )
    version = out.stdout.strip().lstrip("v").split(".")[:2]
    return node is not None and tuple(map(int, version)) >= (22, 6)


pytestmark = [
    pytest.mark.skipif(not _node_supported(), reason="node >= 22.6 missing"),
    pytest.mark.real_io,
]
CallGuard = Callable[..., object]


@pytest.fixture
def call_guard(tmp_path: Path) -> CallGuard:
    (tmp_path / "driver.mjs").write_text(DRIVER)

    def call(
        tool: str, tool_input: dict[str, str], config: str | None = None
    ) -> object:
        if config is not None:
            (tmp_path / "bench-guard.json").write_text(config)
        env = {
            "PATH": str(Path(shutil.which("node") or "").parent),
            "PI_CODING_AGENT_DIR": str(tmp_path),
            "GUARD_TS": GUARD_TS.as_uri(),
            "GUARD_EVENT": json.dumps({"toolName": tool, "input": tool_input}),
        }
        argv = ["node", "--experimental-strip-types", str(tmp_path / "driver.mjs")]
        run = subprocess.run(argv, capture_output=True, text=True, check=True, env=env)
        return json.loads(run.stdout)

    return call


def _recorder(tmp_path: Path, code: int, stderr: str = "") -> str:
    argv = [sys.executable, "-c", RECORDER, str(tmp_path / "stdin"), str(code), stderr]
    return json.dumps({"argv": argv})


def test_guard_exit_code_decides_and_bash_event_is_claude_shaped(
    call_guard: CallGuard, tmp_path: Path
) -> None:
    blocked = call_guard(
        "bash", {"command": "git push"}, _recorder(tmp_path, 2, "no\n")
    )
    assert blocked == {"block": True, "reason": "no"}
    assert json.loads((tmp_path / "stdin").read_text()) == {
        "tool_name": "Bash",
        "tool_input": {"command": "git push"},
    }
    assert call_guard("bash", {"command": "ls"}, _recorder(tmp_path, 0)) is None


@pytest.mark.parametrize(
    "config", ["", "not json", '{"argv": []}', '{"argv": ["/nope"]}']
)
def test_unreadable_config_or_failing_command_blocks(
    call_guard: CallGuard, config: str
) -> None:
    result = call_guard("bash", {"command": "ls"}, config)

    assert isinstance(result, dict)
    assert result["block"] is True
