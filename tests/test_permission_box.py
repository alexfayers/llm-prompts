"""Tests for the permission-box pi extension."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

_EXTENSIONS = (
    Path(__file__).parent.parent
    / "src"
    / "llm_prompts"
    / "prompts"
    / "pi"
    / "extensions"
)
_NODE = shutil.which("node")
_RUNNER = """
import { pathToFileURL } from 'node:url'
const load = (name) => import(pathToFileURL(process.argv[1].replace(/[^/]+$/, name)).href)
const args = JSON.parse(process.argv[2])
const result = await (async () => { BODY })()
process.stdout.write(JSON.stringify(result ?? null))
"""
_PI_TUI_STUB = """
const ESC = /\\x1b\\[[\\d;]*m/g
export const visibleWidth = (text) => text.replace(ESC, '').length
export const truncateToWidth = (text, width, _ellipsis = '', pad = false) => {
  const plain = text.replace(ESC, '')
  return plain.length > width ? plain.slice(0, width) : pad ? text + ' '.repeat(width - plain.length) : text
}
export const matchesKey = (data, key) => data === key
export const wrapTextWithAnsi = (text, width) =>
  text.length === 0 ? [''] : Array.from({ length: Math.ceil(text.length / width) }, (_, n) => text.slice(n * width, (n + 1) * width))
"""
_PI_CODING_AGENT_STUB = """
export const getAgentDir = () => '/nonexistent-agent-dir'
export const generateDiffString = () => ({ diff: '' })
export const renderDiff = (text) => text
"""
_HARNESS = """
const ESC = /\\x1b\\[[\\d;]*m/g
const plain = (lines) => lines.map((line) => line.replace(ESC, ''))
const theme = { fg: (color, text) => `\\x1b[3${({ accent: 1, dim: 2, muted: 3 })[color] ?? 2}m${text}\\x1b[0m`, bold: (text) => `\\x1b[1m${text}\\x1b[0m` }
class PermissionPromptComponent {
  constructor(lines = ['Permission Required', 'body', '', '> (y) Yes']) { this.lines = lines; this.calls = []; this.seen = [] }
  render(width) { this.seen.push(width); return this.lines.map((line, index) => (index === 0 ? theme.fg('accent', line) : line)) }
  handleInput(data) { this.calls.push(['input', data]) }
  invalidate() { this.calls.push(['invalidate']) }
}
const handlers = {}
const on = (name, handler) => { (handlers[name] ??= []).push(handler) }
const pi = { events: { on }, on, registerCommand() {} }
const emit = async (name, payload, ctx) => { for (const handler of handlers[name] ?? []) await handler(payload, ctx) }
const shown = []
const previews = (globalThis[Symbol.for('llm-prompts.permission-preview')] = new Map())
const ui = {
  notify() {},
  onTerminalInput: () => () => {},
  select: async () => undefined,
  confirm: async () => undefined,
  input: async () => undefined,
  editor: async () => undefined,
  custom(factory, options) {
    const entry = { options }
    shown.push(entry)
    return new Promise((resolve) => {
      const tui = { terminal: { rows: 40, columns: 100 }, getFocusedComponent: () => entry.component, requestRender() {} }
      const made = factory(tui, theme, undefined, resolve)
      entry.made = made
      Promise.resolve(made).then((component) => { entry.component = component })
    })
  },
}
const settle = () => new Promise((resolve) => setImmediate(resolve))
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


def _run(
    body: str,
    args: dict[str, Any] | None = None,
    *,
    extensions: tuple[str, ...] = ("permission-box",),
) -> Any:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
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
        (agent / "index.js").write_text(_PI_CODING_AGENT_STUB)
        for name in extensions:
            shutil.copy(_EXTENSIONS / f"{name}.ts", work)
        script = work / "run.mjs"
        done = subprocess.run(
            [
                str(_NODE),
                "--input-type=module",
                "-e",
                _RUNNER.replace("BODY", _HARNESS + body),
                str(script),
                json.dumps(args or {}),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)


_START = """
const box = await load('permission-box.ts')
box.default(pi)
await emit('session_start', {}, { mode: 'tui', ui })
"""


class TestBox:
    def test_the_permission_prompt_is_framed_in_a_rounded_accent_box_titled_from_its_first_line(
        self,
    ) -> None:
        result = _run(
            _START
            + """
void ui.custom(() => new PermissionPromptComponent(), { overlay: false })
await settle()
const lines = shown[0].component.render(30)
return { lines: plain(lines), raw: lines, widths: lines.map((line) => line.replace(ESC, '').length) }
"""
        )
        assert result["lines"] == [
            "\u256d\u2500 Permission Required \u2500\u2500\u2500\u2500\u2500\u2500\u256e",
            "\u2502  body                      \u2502",
            "\u2502                            \u2502",
            "\u2502 > (y) Yes                  \u2502",
            "\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f",
        ]
        assert set(result["widths"]) == {30}
        assert result["raw"][0].startswith("\x1b[31m\u256d\u2500\x1b[0m\x1b[32m\x1b[1m")

    def test_the_box_fills_exactly_the_width_the_host_gives_it_and_the_prompt_gets_the_inner_width(
        self,
    ) -> None:
        result = _run(
            _START
            + """
const inner = new PermissionPromptComponent()
void ui.custom(() => inner, { overlay: false })
await settle()
const wide = shown[0].component.render(100)
const narrow = shown[0].component.render(30)
return {
  wide: plain(wide), wideWidths: wide.map((line) => line.replace(ESC, '').length),
  narrowWidths: narrow.map((line) => line.replace(ESC, '').length), seen: inner.seen,
}
"""
        )
        assert set(result["wideWidths"]) == {100}
        assert [line[:1] for line in result["wide"]] == [
            "\u256d",
            *["\u2502"] * 3,
            "\u2570",
        ]
        assert result["narrowWidths"] == [30] * 5
        assert result["seen"] == [95, 25]

    def test_the_selected_option_marker_becomes_an_arrow_and_the_row_is_bold(
        self,
    ) -> None:
        result = _run(
            _START
            + """
const rows = ['Permission Required', 'body', theme.fg('accent', '\u25b6 (y) Yes'), '  (n) No']
void ui.custom(() => new PermissionPromptComponent(rows), { overlay: false })
await settle()
return shown[0].component.render(40).slice(1, -1)
"""
        )
        assert (
            result[1]
            == "\x1b[31m\u2502 \x1b[0m\x1b[1m\x1b[31m\u2192 (y) Yes\x1b[0m\x1b[0m"
            + " " * 27
            + "\x1b[31m \u2502\x1b[0m"
        )
        assert result[2].endswith("\x1b[31m \u2502\x1b[0m")
        assert "\u2192" not in result[2] and "\x1b[1m" not in result[2]

    def test_text_rows_are_indented_one_column_further_than_option_rows(self) -> None:
        result = _run(
            _START
            + """
const rows = ['Permission Required', 'tool  : edit', '', '\u25b6 (y) Yes', '  (n) No', 'a \u00b7 b']
void ui.custom(() => new PermissionPromptComponent(rows), { overlay: false })
await settle()
return plain(shown[0].component.render(40)).slice(1, -1).map((line) => line.replace(/[ \u2502]+$/, ''))
"""
        )
        assert result == [
            "\u2502  tool  : edit",
            "",
            "\u2502 \u2192 (y) Yes",
            "\u2502   (n) No",
            "\u2502  a \u2022 b",
        ]

    def test_the_key_hints_line_is_restyled_like_ask_user_with_dim_keys_muted_descriptions_and_plain_bullets(
        self,
    ) -> None:
        result = _run(
            _START
            + """
const rows = ['Permission Required', 'a \u00b7 b', '', theme.fg('muted', '\u2191/\u2193 move \u00b7 enter confirm \u00b7 esc')]
void ui.custom(() => new PermissionPromptComponent(rows), { overlay: false })
await settle()
const lines = shown[0].component.render(60)
return { body: lines[1], hints: lines[3], plainHints: plain(lines)[3] }
"""
        )

        def dim(text: str) -> str:
            return f"\x1b[32m{text}\x1b[0m"

        def muted(text: str) -> str:
            return f"\x1b[33m{text}\x1b[0m"

        assert (
            result["hints"]
            .split("\u2502 \x1b[0m", 1)[1]
            .startswith(
                " "
                + dim(
                    dim("\u2191/\u2193")
                    + muted(" move")
                    + " \u2022 "
                    + dim("enter")
                    + muted(" confirm")
                    + " \u2022 "
                    + dim("esc")
                )
            )
        )
        assert (
            result["plainHints"]
            .rstrip(" \u2502")
            .endswith("\u2191/\u2193 move \u2022 enter confirm \u2022 esc")
        )
        assert "\u2022" not in result["body"] and "\u00b7" in result["body"]

    def test_a_last_line_without_hint_separators_is_left_as_it_was(self) -> None:
        result = _run(
            _START
            + """
const rows = ['Permission Required', 'body', 'plain last']
void ui.custom(() => new PermissionPromptComponent(rows), { overlay: false })
await settle()
return plain(shown[0].component.render(40))[2]
"""
        )
        assert result.startswith("\u2502 plain last")

    def test_a_restyling_failure_keeps_the_original_row_inside_the_box(self) -> None:
        result = _run(
            _START
            + """
const rows = ['Permission Required', '\u25b6 (y) Yes', 'a \u00b7 b']
void ui.custom(() => new PermissionPromptComponent(rows), { overlay: false })
await settle()
const wrapper = shown[0].component
wrapper.theme = { fg: (_color, text) => text, bold: (text) => { if (text.includes('\u2192')) throw new Error('boom'); return text } }
return plain(wrapper.render(40))
"""
        )
        assert result[1].startswith("\u2502 \u25b6 (y) Yes")
        assert len(result) == 4
        assert result[0].startswith("\u256d") and result[3].startswith("\u2570")

    def test_a_prompt_announced_by_the_permission_system_opens_as_a_centred_capturing_overlay(
        self,
    ) -> None:
        result = _run(
            _START
            + """
await emit('permissions:ui_prompt', { requestId: 'r1' })
void ui.custom(() => new PermissionPromptComponent(), { overlay: false })
await settle()
return shown[0].options
"""
        )
        assert result == {
            "overlay": True,
            "overlayOptions": {
                "anchor": "center",
                "width": "92%",
                "minWidth": 40,
                "maxHeight": "85%",
                "margin": 1,
            },
        }

    def test_only_the_first_dialog_after_the_announcement_becomes_an_overlay_and_a_decision_withdraws_it(
        self,
    ) -> None:
        result = _run(
            _START
            + """
await emit('permissions:ui_prompt', { requestId: 'r1' })
void ui.custom(() => new PermissionPromptComponent(), { overlay: false })
void ui.custom(() => new PermissionPromptComponent(), { overlay: false })
await emit('permissions:ui_prompt', { requestId: 'r2' })
await emit('permissions:decision', { requestId: 'r2' })
void ui.custom(() => new PermissionPromptComponent(), { overlay: false })
await emit('permissions:ui_prompt', { requestId: 'r3' })
await emit('permissions:decision', { requestId: 'r-other' })
void ui.custom(() => new PermissionPromptComponent())
await settle()
return shown.map((entry) => entry.options)
"""
        )
        overlay = {
            "overlay": True,
            "overlayOptions": {
                "anchor": "center",
                "width": "92%",
                "minWidth": 40,
                "maxHeight": "85%",
                "margin": 1,
            },
        }
        assert result == [overlay, {"overlay": False}, {"overlay": False}, overlay]

    def test_a_new_session_forgets_an_announced_prompt(self) -> None:
        result = _run(
            _START
            + """
await emit('permissions:ui_prompt', { requestId: 'r1' })
await emit('session_start', {}, { mode: 'tui', ui })
void ui.custom(() => new PermissionPromptComponent(), { overlay: false })
await settle()
return shown[0].options
"""
        )
        assert result == {"overlay": False}

    def test_a_published_preview_is_shown_inside_the_box_above_a_divider_and_the_dialog(
        self,
    ) -> None:
        result = _run(
            _START
            + """
previews.set('r1', { title: 'Diff for f.md (+2 -0)', lines: (width) => ['+one', '+two'].map((line) => line.padEnd(width, ' ')) })
await emit('permissions:ui_prompt', { requestId: 'r1' })
void ui.custom(() => new PermissionPromptComponent(), { overlay: false })
await settle()
const lines = shown[0].component.render(40)
return { plain: plain(lines), widths: lines.map((line) => line.replace(ESC, '').length), raw: lines }
"""
        )
        assert [
            line.rstrip(" \u2502\u2500\u256e\u256f") for line in result["plain"]
        ] == [
            "\u256d\u2500 Permission Required",
            "\u2502  Diff for f.md (+2 -0)",
            "\u2502 +one",
            "\u2502 +two",
            "\u2502  Wheel  Alt+Up/Alt+Down  1-2/2",
            "",
            "\u2502  body",
            "",
            "\u2502 > (y) Yes",
            "\u2570",
        ]
        assert result["plain"][5] == "\u2502 " + "\u2500" * 36 + " \u2502"
        assert set(result["widths"]) == {40}
        assert "\x1b[1m" in result["raw"][1]
        assert result["raw"][5].count("\x1b[32m") == 1

    def test_without_a_published_preview_the_box_holds_only_the_dialog(self) -> None:
        result = _run(
            _START
            + """
previews.set('other', { title: 'x', lines: () => ['+one'] })
await emit('permissions:ui_prompt', { requestId: 'r1' })
void ui.custom(() => new PermissionPromptComponent(), { overlay: false })
await settle()
return plain(shown[0].component.render(40))
"""
        )
        assert len(result) == 5

    _LONG_PREVIEW = """
const many = Array.from({ length: 100 }, (_, n) => `+line ${n}`)
previews.set('r1', { title: 'Diff', lines: () => many })
await emit('permissions:ui_prompt', { requestId: 'r1' })
const inner = new PermissionPromptComponent()
void ui.custom(() => inner, { overlay: false })
await settle()
const dlg = shown[0].component
const range = () => plain(dlg.render(60)).find((line) => line.includes('Wheel')).replace(/[\u2502 ]+$/, '').split('  ').pop()
"""

    def test_the_preview_takes_what_remains_of_the_overlay_height_after_the_dialog(
        self,
    ) -> None:
        result = _run(
            _START
            + self._LONG_PREVIEW
            + "return { rows: dlg.render(60).length, range: range() }"
        )
        assert result == {"rows": 34, "range": "1-26/100"}

    def test_a_terminal_too_short_for_three_preview_rows_shows_only_the_dialog(
        self,
    ) -> None:
        result = _run(
            _START
            + self._LONG_PREVIEW
            + "dlg.tui.terminal.rows = 12\nconst short = dlg.render(60).length\ndlg.tui.terminal.rows = 13\nreturn { short, fits: dlg.render(60).length }"
        )
        assert result == {"short": 5, "fits": 11}

    def test_wheel_and_alt_arrows_scroll_the_preview_within_its_bounds_and_request_a_render(
        self,
    ) -> None:
        result = _run(
            _START
            + self._LONG_PREVIEW
            + """
let renders = 0
dlg.tui.requestRender = () => renders++
dlg.render(60)
const wheel = dlg.handleMouse({ type: 'wheel', wheelDelta: 3 })
const afterWheel = range()
dlg.handleInput('alt+down')
const afterDown = range()
dlg.handleInput('alt+up')
dlg.handleInput('alt+up')
const afterUp = range()
dlg.handleMouse({ type: 'wheel', wheelDelta: 1000 })
const bottom = range()
dlg.handleMouse({ type: 'wheel', wheelDelta: -1000 })
return { wheel, afterWheel, afterDown, afterUp, bottom, top: range(), renders, promptKeys: inner.calls }
"""
        )
        assert result["wheel"] == {"handled": True}
        assert [
            result[key]
            for key in ("afterWheel", "afterDown", "afterUp", "bottom", "top")
        ] == [
            "4-29/100",
            "5-30/100",
            "3-28/100",
            "75-100/100",
            "1-26/100",
        ]
        assert result["renders"] == 6
        assert result["promptKeys"] == []

    def test_keys_other_than_the_scroll_keys_and_wheels_without_a_preview_reach_the_prompt(
        self,
    ) -> None:
        result = _run(
            _START
            + """
const inner = new PermissionPromptComponent()
const mouse = []
inner.handleMouse = (event) => { mouse.push(event); return { handled: true } }
void ui.custom(() => inner, { overlay: false })
await settle()
const dlg = shown[0].component
dlg.render(60)
dlg.handleInput('alt+down')
dlg.handleInput('y')
return { calls: inner.calls, wheel: dlg.handleMouse({ type: 'wheel', wheelDelta: 2 }), mouse }
"""
        )
        assert result["calls"] == [["input", "alt+down"], ["input", "y"]]
        assert result["wheel"] == {"handled": True}
        assert result["mouse"] == [{"type": "wheel", "wheelDelta": 2}]

    def test_alt_arrows_and_the_wheel_reach_the_prompt_when_the_preview_is_not_shown(
        self,
    ) -> None:
        result = _run(
            _START
            + self._LONG_PREVIEW
            + """
dlg.tui.terminal.rows = 12
dlg.render(60)
dlg.handleInput('alt+down')
return { calls: inner.calls, wheel: dlg.handleMouse({ type: 'wheel', wheelDelta: 2 }) ?? null }
"""
        )
        assert result == {"calls": [["input", "alt+down"]], "wheel": None}

    def test_a_preview_that_throws_leaves_the_dialog_alone_in_the_box(self) -> None:
        result = _run(
            _START
            + """
previews.set('r1', { title: 'Diff', lines: () => { throw new Error('boom') } })
await emit('permissions:ui_prompt', { requestId: 'r1' })
void ui.custom(() => new PermissionPromptComponent(), { overlay: false })
await settle()
return plain(shown[0].component.render(40)).length
"""
        )
        assert result == 5

    def test_other_components_and_overlays_pass_through_untouched(self) -> None:
        result = _run(
            _START
            + """
class Other { render() { return ['x'] } }
const other = new Other()
const imposter = { render: () => ['plain'] }
void ui.custom(() => other, { overlay: false })
void ui.custom(() => new PermissionPromptComponent(), { overlay: true })
void ui.custom(() => imposter)
await settle()
return shown.map((entry) => entry.component === undefined ? 'none' : entry.component === other ? 'other' : entry.component === imposter ? 'imposter' : entry.component.constructor.name)
"""
        )
        assert result == ["other", "PermissionPromptComponent", "imposter"]

    def test_a_prompt_is_recognised_by_its_title_line_when_the_class_name_differs(
        self,
    ) -> None:
        result = _run(
            _START
            + """
const make = () => ({ render: () => ['Permission Required (Subagent)', 'b'], handleInput() {}, invalidate() {} })
void ui.custom(() => make(), { overlay: false })
void ui.custom(async () => make(), { overlay: false })
await settle()
return shown.map((entry) => plain(entry.component.render(50)))
"""
        )
        assert all(
            lines[0].lstrip().startswith("\u256d\u2500 Permission Required (Sub")
            for lines in result
        )
        assert len(result) == 2

    def test_input_invalidate_focus_mouse_and_dispose_reach_the_prompt(self) -> None:
        result = _run(
            _START
            + """
const inner = new PermissionPromptComponent()
inner.focused = false
const events = []
inner.handleMouse = (event) => { events.push(['mouse', event]); return { handled: true } }
inner.dispose = () => events.push(['dispose'])
void ui.custom(() => inner, { overlay: false })
await settle()
const wrapper = shown[0].component
wrapper.handleInput('y')
wrapper.invalidate()
wrapper.focused = true
const mouse = wrapper.handleMouse({ type: 'wheel' })
wrapper.dispose()
wrapper.render(44)
const bare = new PermissionPromptComponent()
void ui.custom(() => bare, { overlay: false })
await settle()
const plainWrapper = shown[1].component
return {
  calls: inner.calls, events, mouse, innerFocused: inner.focused, wrapperFocused: wrapper.focused, seen: inner.seen,
  bareHas: ['handleMouse', 'dispose', 'focused'].map((key) => key in plainWrapper),
}
"""
        )
        assert result["calls"] == [["input", "y"], ["invalidate"]]
        assert result["events"] == [["mouse", {"type": "wheel"}], ["dispose"]]
        assert result["mouse"] == {"handled": True}
        assert (result["innerFocused"], result["wrapperFocused"]) == (True, True)
        assert result["seen"] == [39]
        assert result["bareHas"] == [True, False, False]

    def test_a_framing_failure_shows_the_prompt_as_it_was(self) -> None:
        result = _run(
            _START
            + """
const inner = new PermissionPromptComponent()
const broken = { fg: () => { throw new Error('boom') }, bold: (text) => text }
void ui.custom((tui, _theme, keybindings, done) => inner, { overlay: false })
await settle()
const entry = shown[0]
const wrapper = entry.component
wrapper.theme = broken
return plain(wrapper.render(30))
"""
        )
        assert result == ["Permission Required", "body", "", "> (y) Yes"]


_COMBINED = """
process.env.PI_POPUP_DEFER_MS = '100'
const ORDER = args.order
const authorizers = new Map()
const service = { registerAuthorizer: (name, fn) => { authorizers.set(name, fn); return () => {} }, registerToolInputFormatter: () => () => {} }
globalThis[Symbol.for('@gotgenes/pi-permission-system:session-services')] = new Map([['sess', service]])
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const keyListeners = new Set()
const log = []
let focusedComponent = null
const combinedUi = {
  notify() {},
  select: async () => undefined,
  confirm: async () => undefined,
  input: async () => undefined,
  editor: async () => undefined,
  onTerminalInput: (listener) => { keyListeners.add(listener); return () => keyListeners.delete(listener) },
  custom: (factory, options) => new Promise((resolve) => {
    const tui = { terminal: { rows: 40, columns: 60 }, getFocusedComponent: () => focusedComponent, requestRender() {} }
    const component = factory(tui, theme, undefined, () => { log.push('closed ' + (options?.overlay ? 'overlay' : 'dialog')); resolve() })
    log.push('shown ' + (options?.overlay ? 'overlay' : 'dialog'))
    options?.onHandle?.({ hide() {} })
    ;(options?.overlay ? overlayHolder : dialogHolder).push({ component, options })
  }),
}
const overlayHolder = []
const dialogHolder = []
const modules = { 'popup-defer': await load('popup-defer.ts'), 'diff-preview': await load('diff-preview.ts'), 'permission-box': await load('permission-box.ts') }
for (const name of ORDER) modules[name].default(pi)
await emit('session_start', {}, { mode: 'tui', cwd: '/', ui: combinedUi })
if (args.restart) await emit('session_start', {}, { mode: 'tui', cwd: '/', ui: combinedUi })
await emit('permissions:ready', { sessionId: 'sess' })
const type = (data) => keyListeners.forEach((listener) => listener(data))
const ask = async (requestId) => {
  const details = { requestId, payload: { request: { toolName: 'edit', value: 'f.md', requester: { agentName: null, forwarded: false } }, evidence: [{ label: 'input', text: "for 'f.md' (+1 -0)\\n+body" }] } }
  await authorizers.get('diff-preview')(details)
  await emit('permissions:ui_prompt', { requestId })
  void combinedUi.custom(() => new PermissionPromptComponent(), { overlay: false })
}
"""

_ORDERS = [
    ["popup-defer", "permission-box", "diff-preview"],
    ["permission-box", "popup-defer", "diff-preview"],
    ["diff-preview", "permission-box", "popup-defer"],
    ["diff-preview", "popup-defer", "permission-box"],
]


class TestWithPopupDeferAndDiffPreview:
    """Tests for the box when popup-defer and diff-preview are loaded with it, in any order."""

    @staticmethod
    def _run_all(body: str, args: dict[str, Any]) -> Any:
        return _run(
            _COMBINED + body,
            args,
            extensions=("popup-defer", "diff-preview", "permission-box"),
        )

    @pytest.mark.parametrize(
        "order", _ORDERS, ids=lambda order: "-".join(name[:3] for name in order)
    )
    @pytest.mark.parametrize("typing", [False, True])
    @pytest.mark.parametrize("restart", [False, True])
    def test_the_prompt_opens_once_as_one_overlay_holding_the_diff_whether_or_not_the_user_is_typing(
        self, order: list[str], typing: bool, restart: bool
    ) -> None:
        result = self._run_all(
            """
if (args.typing) type('x')
await ask('r1')
await sleep(30)
const duringTyping = [...log]
await sleep(250)
const [{ component, options }] = overlayHolder
return { duringTyping, settled: log, dialogs: dialogHolder.length, options, lines: plain(component.render(60)) }
""",
            {"order": order, "typing": typing, "restart": restart},
        )
        assert result["duringTyping"] == ([] if typing else ["shown overlay"])
        assert result["settled"] == ["shown overlay"]
        assert result["dialogs"] == 0
        assert result["options"]["overlayOptions"]["anchor"] == "center"
        assert result["lines"][1].startswith("\u2502  Diff for 'f.md'")
        assert result["lines"][2].startswith("\u2502 +body")
        assert result["lines"][0].lstrip().startswith(
            "\u256d\u2500 Permission Required"
        ) and result["lines"][-1].startswith("\u2570")

    def test_a_held_ask_is_shown_with_its_own_preview_after_the_previous_one_closed(
        self,
    ) -> None:
        result = self._run_all(
            """
await ask('r1')
const has = ({ component }) => plain(component.render(60)).some((line) => line.includes('+body'))
const rendered = [has(overlayHolder[0])]
type('y')
await emit('permissions:decision', { requestId: 'r1' })
await ask('r2')
await sleep(250)
rendered.push(has(overlayHolder[1]))
return { log, rendered, slot: [...globalThis[Symbol.for('llm-prompts.permission-preview')].keys()] }
""",
            {"order": _ORDERS[0], "typing": False, "restart": False},
        )
        assert result["log"] == ["shown overlay", "shown overlay"]
        assert result["rendered"] == [True, True]
        assert result["slot"] == ["r2"]
