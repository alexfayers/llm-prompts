"""Tests for the codemode-sleep pi extension."""

import json
import subprocess
from pathlib import Path

_EXT = Path(__file__).parents[1] / "src/llm_prompts/prompts/pi/extensions"
_JS = """import { registerHooks } from "node:module";
import { mock } from "node:test";
const stub = "data:text/javascript,export const Type = new Proxy({}, { get: () => () => ({}) })";
registerHooks({ resolve: (s, c, next) => (s == "typebox" ? { url: stub, shortCircuit: true } : next(s, c)) });
mock.timers.enable({ apis: ["setTimeout"] });
let tool, done = false;
(await import(process.argv[1])).default({ registerTool: (t) => (tool = t) });
const run = (signal) => tool.execute("id", { ms: 500 }, signal).then((r) => r.content[0].text, (e) => e.name);
const slept = run().then((r) => (done = r));
mock.timers.tick(499);
await new Promise(setImmediate);
const early = done;
mock.timers.tick(1);
const ac = new AbortController(), aborted = run(ac.signal);
ac.abort();
console.log(JSON.stringify([early, await slept, await aborted]));"""


def test_sleeps_for_the_given_time_and_rejects_when_aborted() -> None:
    uri = (_EXT / "codemode-sleep.ts").as_uri()
    args = ["node", "--input-type=module", "-e", _JS, uri]
    out = subprocess.run(args, check=True, capture_output=True, text=True).stdout
    assert json.loads(out) == [False, "Slept 500 ms", "AbortError"]
