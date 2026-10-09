"""Tests for the diff-preview pi extension."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "extensions"
    / "diff-preview.ts"
)
_NODE = shutil.which("node")
_RUNNER = """
import { pathToFileURL } from 'node:url'
const mod = await import(pathToFileURL(process.argv[1]).href)
const args = JSON.parse(process.argv[2])
const result = await (async () => { BODY })()
process.stdout.write(JSON.stringify(result ?? null))
"""
_PI_TUI_STUB = """
export const matchesKey = (data, key) => data === key
export const visibleWidth = (text) => text.length
export const truncateToWidth = (text, width) => text.slice(0, width)
export const wrapTextWithAnsi = (text, width) =>
  text.length === 0 ? [''] : Array.from({ length: Math.ceil(text.length / width) }, (_, n) => text.slice(n * width, (n + 1) * width))
"""
_PI_CODING_AGENT_STUB = """
export const getAgentDir = () => globalThis.agentDir ?? '@@AGENT_DIR@@'

const rows = (text) => {
  const lines = text.split('\\n')
  if (lines.at(-1) === '') lines.pop()
  return lines
}
export const generateDiffString = (before, after, context = 4) => {
  const [a, b] = [rows(before), rows(after)]
  let head = 0
  while (head < a.length && head < b.length && a[head] === b[head]) head++
  let tail = 0
  while (tail < a.length - head && tail < b.length - head && a.at(-1 - tail) === b.at(-1 - tail)) tail++
  const width = String(Math.max(a.length, b.length)).length
  const row = (mark, number, text) => `${mark}${String(number).padStart(width)} ${text}`
  const first = Math.max(0, head - context)
  const diff = [
    ...a.slice(first, head).map((text, n) => row(' ', first + n + 1, text)),
    ...a.slice(head, a.length - tail).map((text, n) => row('-', head + n + 1, text)),
    ...b.slice(head, b.length - tail).map((text, n) => row('+', head + n + 1, text)),
    ...a.slice(a.length - tail, a.length - tail + context).map((text, n) => row(' ', a.length - tail + n + 1, text)),
  ]
  return { diff: diff.join('\\n'), firstChangedLine: head + 1 }
}
export const renderDiff = (text) => (globalThis.paintDiff ?? ((diff) => diff))(text)
"""


_COMPACT_LAYOUT_STUB = """
const lines = (display) => display.split('\\n').map((text) => 'C|' + text)
export const renderCodeDiff = (patch, display, path, theme) =>
  globalThis.compactRender
    ? globalThis.compactRender(patch, display, path, theme)
    : { render: (width) => lines(display).flatMap((line) => Array.from({ length: Math.max(1, Math.ceil(line.length / width)) }, (_, n) => line.slice(n * width, (n + 1) * width))) }
"""


def _can_strip_types() -> bool:
    if _NODE is None:
        return False
    probe = subprocess.run(
        [_NODE, "-p", "Boolean(process.features.typescript)"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not _can_strip_types(), reason="node with type stripping missing"
)


def _run(body: str, args: dict[str, Any]) -> Any:
    with tempfile.TemporaryDirectory() as work:
        script = _stage_script(Path(work))
        return _run_staged(script, body, args)


def _stage_script(work: Path) -> Path:
    tui = work / "node_modules" / "@earendil-works" / "pi-tui"
    tui.mkdir(parents=True)
    (work / "package.json").write_text('{"type":"module"}')
    (tui / "package.json").write_text(
        '{"name":"@earendil-works/pi-tui","type":"module","main":"index.js"}'
    )
    (tui / "index.js").write_text(_PI_TUI_STUB)
    agent = work / "node_modules" / "@earendil-works" / "pi-coding-agent"
    agent.mkdir()
    (agent / "package.json").write_text(
        '{"name":"@earendil-works/pi-coding-agent","type":"module","main":"index.js"}'
    )
    agent_dir = work / "agent"
    (agent / "index.js").write_text(
        _PI_CODING_AGENT_STUB.replace("@@AGENT_DIR@@", str(agent_dir))
    )
    # Node refuses type stripping under node_modules, so the package is a symlink to a plain directory.
    compact = work / "compact-tools"
    (compact / "extensions").mkdir(parents=True)
    (compact / "extensions" / "compact-tools-layout.ts").write_text(
        _COMPACT_LAYOUT_STUB
    )
    (agent_dir / "npm" / "node_modules").mkdir(parents=True)
    (agent_dir / "npm" / "node_modules" / "pi-compact-tools").symlink_to(compact)
    script = work / _SCRIPT.name
    shutil.copy(_SCRIPT, script)
    return script


def _run_staged(script: Path, body: str, args: dict[str, Any]) -> Any:
    done = subprocess.run(
        [
            str(_NODE),
            "--input-type=module",
            "-e",
            _RUNNER.replace("BODY", body),
            str(script),
            json.dumps(args),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(done.stdout)


def _edit(
    tmp_path: Path, input: dict[str, Any], existing: str | None = None
) -> str | None:
    if existing is not None:
        (tmp_path / "a.py").write_bytes(existing.encode())
    result: str | None = _run(
        "return mod.formatEditDiff(args.input, args.cwd)",
        {"input": input, "cwd": str(tmp_path)},
    )
    return result


class TestFormatEditDiff:
    """Tests for the edit prompt preview."""

    def test_edit_is_applied_to_the_file_and_diffed_in_native_format(
        self, tmp_path: Path
    ) -> None:
        text = _edit(
            tmp_path,
            {"path": "a.py", "edits": [{"oldText": "x = 1", "newText": "x = 2"}]},
            "x = 1\ny\n",
        )
        assert text is not None
        assert text.splitlines() == [
            "for 'a.py' (+1 -1)",
            "-1 x = 1",
            "+1 x = 2",
            " 2 y",
        ]

    def test_every_edit_is_matched_against_the_original_file_in_any_order(
        self, tmp_path: Path
    ) -> None:
        text = _edit(
            tmp_path,
            {
                "path": "a.py",
                "edits": [
                    {"oldText": "b", "newText": "B"},
                    {"oldText": "a", "newText": "A"},
                ],
            },
            "a\nb\n",
        )
        assert text is not None
        assert text.splitlines() == [
            "for 'a.py' (+2 -2)",
            "-1 a",
            "-2 b",
            "+1 A",
            "+2 B",
        ]

    def test_single_oldtext_newtext_input_is_one_edit(self, tmp_path: Path) -> None:
        text = _edit(tmp_path, {"path": "a.py", "oldText": "a", "newText": "b"}, "a\n")
        assert text is not None
        assert text.splitlines() == ["for 'a.py' (+1 -1)", "-1 a", "+1 b"]

    def test_line_endings_of_the_file_do_not_matter(self, tmp_path: Path) -> None:
        text = _edit(
            tmp_path,
            {"path": "a.py", "edits": [{"oldText": "a\nb", "newText": "a\nc"}]},
            "a\r\nb\r\n",
        )
        assert text is not None
        assert text.splitlines() == ["for 'a.py' (+1 -1)", " 1 a", "-2 b", "+2 c"]

    @pytest.mark.parametrize("existing", [None, "zzz\n", "a\na\n"])
    def test_an_edit_that_cannot_be_applied_falls_back_to_its_own_snippet(
        self, tmp_path: Path, existing: str | None
    ) -> None:
        text = _edit(
            tmp_path,
            {"path": "a.py", "edits": [{"oldText": "a", "newText": "b"}]},
            existing,
        )
        assert text is not None
        assert text.splitlines() == ["for 'a.py' (+1 -1)", "-1 a", "+1 b"]

    def test_overlapping_edits_fall_back_to_their_own_snippets(
        self, tmp_path: Path
    ) -> None:
        text = _edit(
            tmp_path,
            {
                "path": "a.py",
                "edits": [
                    {"oldText": "ab", "newText": "x"},
                    {"oldText": "bc", "newText": "y"},
                ],
            },
            "abc\n",
        )
        assert text is not None
        assert text.splitlines()[1:] == ["-1 ab", "+1 x", "-1 bc", "+1 y"]

    def test_unusable_input_declines_instead_of_throwing(self, tmp_path: Path) -> None:
        assert _edit(tmp_path, {"path": "a.py"}) is None
        assert _edit(tmp_path, {"edits": [{"oldText": "a", "newText": "b"}]}) is None
        assert _edit(tmp_path, {"path": "a.py", "edits": [{"oldText": 1}]}) is None


def _write(tmp_path: Path, content: str, existing: str | None) -> str | None:
    target = tmp_path / "f.txt"
    if existing is not None:
        target.write_text(existing)
    result: str | None = _run(
        "return mod.formatWriteDiff(args.input, args.cwd)",
        {"input": {"path": "f.txt", "content": content}, "cwd": str(tmp_path)},
    )
    return result


class TestFormatWriteDiff:
    """Tests for the write prompt preview."""

    def test_overwrite_diffs_against_the_file_on_disk_in_native_format(
        self, tmp_path: Path
    ) -> None:
        text = _write(tmp_path, "a\nc\n", "a\nb\n")
        assert text is not None
        assert text.splitlines() == ["for 'f.txt' (+1 -1)", " 1 a", "-2 b", "+2 c"]

    def test_new_file_is_all_additions(self, tmp_path: Path) -> None:
        text = _write(tmp_path, "a\nb\n", None)
        assert text is not None
        assert text.splitlines() == ["for 'f.txt' (new file, +2)", "+1 a", "+2 b"]

    def test_unreadable_target_declines_instead_of_throwing(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "f.txt").mkdir()
        assert _write(tmp_path, "a\n", None) is None

    def test_long_diffs_keep_every_line(self, tmp_path: Path) -> None:
        text = _write(tmp_path, "".join(f"n{n}\n" for n in range(150)), None)
        assert text is not None
        lines = text.splitlines()
        assert lines[0] == "for 'f.txt' (new file, +150)"
        assert lines[1:] == [f"+{n + 1:>3} n{n}" for n in range(150)]

    def test_long_lines_are_kept_whole(self, tmp_path: Path) -> None:
        text = _write(tmp_path, "x" * 1000 + "\n", None)
        assert text is not None
        assert text.splitlines()[-1] == "+1 " + "x" * 1000


_SETUP = """
const handlers = {}
const pi = { events: { on: (name, handler) => { (handlers[name] ??= []).push(handler) } }, on: (name, handler) => { (handlers[name] ??= []).push(handler) } }
const registered = new Map()
const disposed = []
const authorizers = new Map()
const authorizerDisposed = []
const service = {
  registerAuthorizer: (name, fn) => {
    if (authorizers.has(name)) throw new Error('duplicate ' + name)
    authorizers.set(name, fn)
    return () => { authorizers.delete(name); authorizerDisposed.push(name) }
  },
  registerToolInputFormatter: (tool, formatter) => {
  if (registered.has(tool)) throw new Error('duplicate ' + tool)
  registered.set(tool, formatter)
  return () => { registered.delete(tool); disposed.push(tool) }
} }
globalThis[Symbol.for('@gotgenes/pi-permission-system:session-services')] = new Map([['sess', service]])
const emit = async (name, payload, ctx) => { for (const handler of handlers[name] ?? []) await handler(payload, ctx) }
mod.default(pi)
"""


class TestRegistration:
    """Tests for wiring the formatters into the permission system."""

    def test_formatters_register_on_ready_once_and_unregister_on_shutdown(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "f.txt").write_text("old\n")
        result = _run(
            _SETUP
            + """
await emit('session_start', {}, { cwd: args.cwd })
await emit('permissions:ready', { sessionId: 'sess' })
await emit('permissions:ready', { sessionId: 'sess' })
const tools = [...registered.keys()].sort()
const shown = registered.get('write')({ path: 'f.txt', content: 'new\\n' })
await emit('session_shutdown', {})
return { tools, shown, remaining: [...registered.keys()], disposed: disposed.sort() }
""",
            {"cwd": str(tmp_path)},
        )
        assert result["tools"] == ["edit", "write"]
        assert result["shown"].splitlines()[1:] == ["-1 old", "+1 new"]
        assert result["remaining"] == []
        assert result["disposed"] == ["edit", "write"]

    def test_a_tool_whose_formatter_is_taken_is_skipped_without_failing(self) -> None:
        result = _run(
            _SETUP
            + """
registered.set('edit', 'other')
await emit('permissions:ready', { sessionId: 'sess' })
await emit('permissions:ready', { sessionId: null })
await emit('permissions:ready', { sessionId: 'unknown' })
return { edit: registered.get('edit'), write: typeof registered.get('write') }
""",
            {},
        )
        assert result == {"edit": "other", "write": "function"}


_ASK_HELPERS = """
const askDetails = (requestId, toolName, evidence, requester = { agentName: null, forwarded: false }, value = 'f.md', kind = 'tool') =>
  ({ requestId, payload: { kind, request: { toolName, value, requester }, evidence } })
"""


_UI_SETUP = """
const settle = () => new Promise((resolve) => setImmediate(resolve))
const notes = []
const customCalls = []
const ctx = {
  mode: 'tui',
  ui: {
    notify: (message, type) => notes.push([message, type]),
    onTerminalInput: () => { throw new Error('diff-preview must not listen for keys') },
    custom: (...call) => { customCalls.push(call); return Promise.resolve() },
  },
}
const slot = () => globalThis[Symbol.for('llm-prompts.permission-preview')]
const open = async (details) => {
  await authorizers.get('diff-preview')(details)
  await emit('permissions:ui_prompt', { requestId: details.requestId })
  return slot()?.get(details.requestId)
}
"""


class TestPreviewSlot:
    """Tests for publishing the full diff or command to the permission box."""

    def test_an_edit_ask_defers_and_publishes_the_diff_for_the_box_instead_of_opening_an_overlay(
        self,
    ) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const text = ["for 'f.md' (+2 -0)", '+line 0', '+line 1'].join('\\n')
const details = askDetails('r1', 'edit', [{ label: 'input', text }])
const verdict = await authorizers.get('diff-preview')(details)
const preview = slot().get('r1')
await emit('permissions:ui_prompt', { requestId: 'r1' })
return { verdict, title: preview.title, lines: preview.lines(40, undefined), dialog: details.payload.evidence, customCalls: customCalls.length, notes }
""",
            {},
        )
        assert result == {
            "verdict": {"kind": "defer"},
            "title": "Diff for 'f.md' (+2 -0)",
            "lines": ["C|+line 0", "C|+line 1"],
            "dialog": [{"label": "input", "text": "for 'f.md' (+2 -0)"}],
            "customCalls": 0,
            "notes": [],
        }

    def test_a_long_bash_command_is_published_as_plain_text_and_a_short_one_is_not(
        self,
    ) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const long = 'echo ' + 'x'.repeat(130)
const shown = await open(askDetails('long', 'bash', [], undefined, long, 'bash'))
const short = await open(askDetails('short', 'bash', [], undefined, 'ls -la', 'bash'))
return { title: shown.title, lines: shown.lines(200, undefined), long, short: short ?? null, keys: [...slot().keys()] }
""",
            {},
        )
        assert result["title"] == "bash"
        assert result["lines"] == [result["long"]]
        assert result["short"] is None
        assert result["keys"] == ["long"]

    def test_long_text_previews_of_any_tool_and_forwarded_asks_are_titled_and_trim_the_dialog(
        self,
    ) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const forwarded = { agentName: 'worker-1', forwarded: true }
const wide = 'y'.repeat(150)
const full = askDetails('b', 'bash', [{ label: 'full command', text: 'cd d\\n' + wide }], forwarded, 'cd d', 'bash')
const tool = askDetails('t', 'grep', [{ label: 'input', text: 'a\\nb' }])
const bash = await open(full)
const grep = await open(tool)
return { bash: [bash.title, bash.lines(60, undefined)], grep: [grep.title, grep.lines(60, undefined)], dialogBash: full.payload.evidence, dialogTool: tool.payload.evidence }
""",
            {},
        )
        assert result["bash"][0] == "bash from worker-1"
        assert result["bash"][1][0] == "cd d"
        assert "".join(result["bash"][1][1:]) == "y" * 150
        assert result["grep"] == ["grep", ["a", "b"]]
        assert result["dialogBash"] == [{"label": "full command", "text": "cd d"}]
        assert result["dialogTool"] == [{"label": "input", "text": "a"}]

    def test_a_forwarded_edit_names_the_requesting_agent_in_the_title(self) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const preview = await open(askDetails('r1', 'edit', [{ label: 'input', text: '+a' }], { agentName: 'worker-1', forwarded: true }))
return preview.title
""",
            {},
        )
        assert result == "Diff for 'f.md' from worker-1"

    def test_a_text_preview_never_loads_the_compact_renderer_or_paints_as_a_diff(
        self,
    ) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
globalThis.compactRender = () => { throw new Error('should not draw text') }
globalThis.paintDiff = (text) => '<painted>' + text
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const preview = await open(askDetails('r1', 'bash', [], undefined, 'echo a\\necho b', 'bash'))
return { lines: preview.lines(40, undefined), notes }
""",
            {},
        )
        assert result == {"lines": ["echo a", "echo b"], "notes": []}

    def test_a_long_dialog_value_is_clipped_to_a_short_head(self) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const details = askDetails('r1', 'mcp', [{ label: 'input', text: 'z'.repeat(300) }])
await authorizers.get('diff-preview')(details)
return details.payload.evidence[0].text
""",
            {},
        )
        assert result == "z" * 117 + "..."

    def test_a_decision_withdraws_only_its_own_preview(self) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
await open(askDetails('r1', 'edit', [{ label: 'input', text: '+a' }]))
await open(askDetails('r2', 'write', [{ label: 'input', text: '+b' }]))
await emit('permissions:decision', { requestId: 'other' })
const afterOther = [...slot().keys()]
await emit('permissions:decision', { requestId: 'r1' })
await emit('permissions:decision', { requestId: 'r1' })
return { afterOther, remaining: [...slot().keys()] }
""",
            {},
        )
        assert result == {"afterOther": ["r1", "r2"], "remaining": ["r2"]}

    def test_shutdown_and_a_new_session_withdraw_every_preview(self) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
await open(askDetails('r1', 'edit', [{ label: 'input', text: '+a' }]))
await emit('session_start', {}, ctx)
const afterRestart = [...slot().keys()]
await open(askDetails('r2', 'edit', [{ label: 'input', text: '+a' }]))
await emit('session_shutdown', {})
return { afterRestart, afterShutdown: [...slot().keys()] }
""",
            {},
        )
        assert result == {"afterRestart": [], "afterShutdown": []}

    def test_unrelated_or_malformed_asks_publish_nothing_and_leave_the_dialog_alone(
        self,
    ) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const authorize = authorizers.get('diff-preview')
const bash = askDetails('b', 'bash', [{ label: 'full command', text: 'ls -la' }], undefined, 'ls', 'bash')
const verdicts = [
  await authorize(bash),
  await authorize(askDetails('e', 'edit', [{ label: 'command', text: 'x' }])),
  await authorize(askDetails('g', 'grep', [{ label: 'other', text: 'x\\ny' }])),
  await authorize(askDetails('s', 'grep', [{ label: 'input', text: 'one line' }])),
  await authorize(null),
  await authorize({ requestId: 'm', payload: {} }),
]
return { verdicts, published: slot()?.size ?? 0, bash: bash.payload.evidence[0].text }
""",
            {},
        )
        assert result == {
            "verdicts": [{"kind": "defer"}] * 6,
            "published": 0,
            "bash": "ls -la",
        }

    def test_outside_the_tui_the_dialog_is_left_whole_and_nothing_is_published(
        self,
    ) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
await emit('session_start', {}, { ...ctx, mode: 'print' })
await emit('permissions:ready', { sessionId: 'sess' })
const details = askDetails('r1', 'edit', [{ label: 'input', text: '+a\\n+b' }])
const verdict = await authorizers.get('diff-preview')(details)
return { verdict, published: slot()?.size ?? 0, text: details.payload.evidence[0].text }
""",
            {},
        )
        assert result == {
            "verdict": {"kind": "defer"},
            "published": 0,
            "text": "+a\n+b",
        }

    def test_long_lines_wrap_instead_of_being_cut(self) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
globalThis.agentDir = '/nonexistent'
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const preview = await open(askDetails('r1', 'edit', [{ label: 'input', text: '+' + 'y'.repeat(50) }]))
return preview.lines(20, undefined)
""",
            {},
        )
        assert "".join(result) == "+" + "y" * 50
        assert {len(row) for row in result} == {20, 11}

    def test_without_the_compact_renderer_the_diff_is_painted_by_pi(self) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
globalThis.agentDir = '/nonexistent'
globalThis.paintDiff = (text) => text.split('\\n').map((line) => '\x1b[32m' + line + '\x1b[39m').join('\\n')
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const preview = await open(askDetails('r1', 'edit', [{ label: 'input', text: "for 'f.md' (+1 -0)\\n+1 " + 'y'.repeat(20) }]))
return preview.lines(80, undefined)
""",
            {},
        )
        assert result == ["\x1b[32m+1 " + "y" * 20 + "\x1b[39m"]

    def test_a_painter_that_throws_leaves_the_diff_readable(self) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
globalThis.agentDir = '/nonexistent'
globalThis.paintDiff = () => { throw new Error('no theme') }
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const preview = await open(askDetails('r1', 'edit', [{ label: 'input', text: '+1 a' }]))
return preview.lines(20, undefined)
""",
            {},
        )
        assert result == ["+1 a"]

    def test_the_diff_is_drawn_by_the_compact_tools_renderer_with_the_box_theme(
        self,
    ) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
const calls = []
const theme = { fg: (color, text) => text }
globalThis.compactRender = (...call) => { calls.push(call); return { render: () => ['drawn'] } }
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const text = ["for 'src/x.py' (+1 -0)", '+1 new'].join('\\n')
const preview = await open(askDetails('r1', 'write', [{ label: 'input', text }]))
const shown = preview.lines(60, theme)
return { calls: calls.map(([patch, display, path, given]) => [patch, display, path, given === theme]), shown, title: preview.title, notes }
""",
            {},
        )
        assert result["calls"] == [["", "+1 new", "src/x.py", True]]
        assert result["shown"] == ["drawn"]
        assert result["title"] == "Diff for 'src/x.py' (+1 -0)"
        assert result["notes"] == []

    def test_an_unavailable_compact_renderer_falls_back_and_warns_once_per_session(
        self,
    ) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
globalThis.agentDir = '/nonexistent'
const shownFor = async (requestId) => {
  const preview = await open(askDetails(requestId, 'edit', [{ label: 'input', text: "for 'f.md' (+1 -0)\\n+1 a" }]))
  return preview.lines(30, undefined)[0]
}
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const rows = [await shownFor('r1'), await shownFor('r2')]
const sameSession = notes.length
await emit('session_start', {}, ctx)
rows.push(await shownFor('r3'))
return { rows, sameSession, notes }
""",
            {},
        )
        warning = [
            "diff-preview: pi-compact-tools renderer unavailable, using built-in diff",
            "warning",
        ]
        assert result["rows"] == ["+1 a"] * 3
        assert result["sameSession"] == 1
        assert result["notes"] == [warning, warning]

    def test_a_compact_renderer_that_throws_falls_back_and_warns_once(self) -> None:
        result = _run(
            _SETUP
            + _ASK_HELPERS
            + _UI_SETUP
            + """
globalThis.compactRender = () => { throw new Error('bad theme') }
await emit('session_start', {}, ctx)
await emit('permissions:ready', { sessionId: 'sess' })
const preview = await open(askDetails('r1', 'edit', [{ label: 'input', text: "for 'f.md' (+1 -0)\\n+1 a" }]))
preview.lines(30, undefined)
return { shown: preview.lines(30, undefined)[0], notes }
""",
            {},
        )
        assert result == {
            "shown": "+1 a",
            "notes": [
                [
                    "diff-preview: pi-compact-tools renderer unavailable, using built-in diff",
                    "warning",
                ]
            ],
        }

    def test_authorizer_registers_once_and_is_disposed_on_shutdown(self) -> None:
        result = _run(
            _SETUP
            + """
await emit('permissions:ready', { sessionId: 'sess' })
await emit('permissions:ready', { sessionId: 'sess' })
const names = [...authorizers.keys()]
await emit('session_shutdown', {})
return { names, remaining: [...authorizers.keys()], disposed: authorizerDisposed }
""",
            {},
        )
        assert result == {
            "names": ["diff-preview"],
            "remaining": [],
            "disposed": ["diff-preview"],
        }
