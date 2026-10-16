"""Tests for the herdr-permission-blocked pi extension."""

import json
import subprocess
from pathlib import Path

_EXT = Path(__file__).parents[1] / "src/llm_prompts/prompts/pi/extensions"
_JS = """const h = {}, out = [], events = { on: (n, f) => (h[n] ??= []).push(f), emit: (n, p) => out.push(p) };
(await import(process.argv[1])).default({ events });
for (const t of process.argv[2].split(" ")) h[t[0] == "p" ? "permissions:ui_prompt" : "permissions:decision"].forEach((f) => f({ requestId: t[1] }));
console.log(JSON.stringify(out));"""


def test_each_prompt_blocks_once_until_its_own_decision() -> None:
    uri = (_EXT / "herdr-permission-blocked.ts").as_uri()
    args = ["node", "--input-type=module", "-e", _JS, uri, "pa pa pb da da dc db"]
    out = subprocess.run(args, check=True, capture_output=True, text=True).stdout
    on = {"active": True, "label": "Permission prompt"}
    assert json.loads(out) == [on, on, {"active": False}, {"active": False}]
