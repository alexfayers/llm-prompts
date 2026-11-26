import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

FORK_MODE_TS = (
    Path(__file__).parents[2] / "src/llm_prompts/benchmark/guard/fork_mode.ts"
)
DRIVER = """\
const extension = (await import(process.env.FORK_MODE_TS)).default;
const handlers = {};
extension({ on: (name, handler) => { handlers[name] = handler; }, getThinkingLevel: () => "low" });
const event = JSON.parse(process.env.FORK_EVENT);
const result = await handlers.tool_call(event, { model: { provider: "p", id: "m" } });
console.log(JSON.stringify({ result: result ?? null, input: event.input }));
"""


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


def _call(
    tmp_path: Path, tool: str, tool_input: dict[str, str], config: str
) -> dict[str, Any]:
    (tmp_path / "driver.mjs").write_text(DRIVER)
    (tmp_path / "bench-fork-mode.json").write_text(config)
    env = {
        "PATH": str(Path(shutil.which("node") or "").parent),
        "PI_CODING_AGENT_DIR": str(tmp_path),
        "FORK_MODE_TS": FORK_MODE_TS.as_uri(),
        "FORK_EVENT": json.dumps({"toolName": tool, "input": tool_input}),
    }
    argv = ["node", "--experimental-strip-types", str(tmp_path / "driver.mjs")]
    run = subprocess.run(argv, capture_output=True, text=True, check=True, env=env)
    out: dict[str, Any] = json.loads(run.stdout)
    return out


def test_a_cold_run_gives_a_plain_fork_the_model_and_thinking_of_the_session(
    tmp_path: Path,
) -> None:
    out = _call(tmp_path, "fork", {"task": "t"}, '{"warm": false}')

    assert out == {"result": None, "input": {"task": "t", "model": "p/m:low"}}


def test_a_warm_run_takes_the_model_off_a_plain_fork(tmp_path: Path) -> None:
    out = _call(tmp_path, "fork", {"task": "t", "model": "x"}, '{"warm": true}')

    assert out == {"result": None, "input": {"task": "t"}}


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [("bash", {}), ("fork", {"from": "a"}), ("fork", {"shared": "s", "model": "x"})],
)
def test_other_calls_are_left_alone(
    tmp_path: Path, tool: str, tool_input: dict[str, str]
) -> None:
    out = _call(tmp_path, tool, tool_input, '{"warm": false}')

    assert out == {"result": None, "input": tool_input}


@pytest.mark.parametrize("config", ["", "not json", "{}", '{"warm": "yes"}'])
def test_an_unreadable_config_blocks_a_fork(tmp_path: Path, config: str) -> None:
    out = _call(tmp_path, "fork", {"task": "t"}, config)

    assert out["result"]["block"] is True
