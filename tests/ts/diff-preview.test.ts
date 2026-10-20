import assert from "node:assert/strict";
import fs from "node:fs";
import { join } from "node:path";
import { registerHooks } from "node:module";
import { pathToFileURL } from "node:url";
import { after, afterEach, beforeEach, describe, mock, test } from "node:test";
import { loadExtension, restoreMocks } from "./helpers.ts";

const PREVIEW_SLOT = Symbol.for("llm-prompts.permission-preview");
const SERVICES = Symbol.for("@gotgenes/pi-permission-system:session-services");
const WARNING = ["diff-preview: pi-compact-tools renderer unavailable, using built-in diff", "warning"];

type Compact = (...call: any[]) => { render(width: number): string[] };
const compactStub: Compact = (_patch, display) => ({ render: () => display.split("\n").map((text: string) => `C|${text}`) });
const unpainted = () => {
	throw new Error("no theme");
};

const AGENT_DIR = "/agent";
const compactLayout = join(AGENT_DIR, "npm", "node_modules", "pi-compact-tools", "extensions", "compact-tools-layout.ts");
const compactLayoutUrl = pathToFileURL(compactLayout).href;
const layoutSource = "export const renderCodeDiff = (...call) => globalThis.compactRender(...call);";
const layoutHooks = registerHooks({
	resolve: (specifier, context, next) => (specifier === compactLayout ? { url: compactLayoutUrl, format: "module", shortCircuit: true } : next(specifier, context)),
	load: (url, context, next) => (url === compactLayoutUrl ? { format: "module", source: layoutSource, shortCircuit: true } : next(url, context)),
});

let files: Map<string, string | null>;

const readFile = fs.readFileSync;
const readFileSync = (file: string, ...rest: any[]) => {
	if (!String(file).startsWith("/w/")) return (readFile as any)(file, ...rest);
	const text = files.get(file);
	if (text !== undefined && text !== null) return text;
	throw Object.assign(new Error(file), { code: text === null ? "EISDIR" : "ENOENT" });
};

beforeEach(() => {
	files = new Map();
	mock.method(fs, "readFileSync", readFileSync);
	delete (globalThis as any)[PREVIEW_SLOT];
});
afterEach(() => mock.restoreAll());
after(() => {
	layoutHooks.deregister();
	restoreMocks();
});

const formatEdit = async (input: object, existing?: string) => {
	if (existing !== undefined) files.set("/w/a.py", existing);
	return (await loadExtension("diff-preview")).module.formatEditDiff(input, "/w");
};
const formatWrite = async (content: string, existing?: string | null) => {
	if (existing !== undefined) files.set("/w/f.txt", existing);
	return (await loadExtension("diff-preview")).module.formatWriteDiff({ path: "f.txt", content }, "/w");
};

describe("formatEditDiff", () => {
	const edit = (oldText: string, newText: string) => ({ oldText, newText });
	const snippet = ["for 'a.py' (+1 -1)", "-1 a", "+1 b"];
	for (const [label, input, existing, expected] of [
		["is applied to the file and diffed in native format", { path: "a.py", edits: [edit("x = 1", "x = 2")] }, "x = 1\ny\n", ["for 'a.py' (+1 -1)", "-1 x = 1", "+1 x = 2", " 2 y"]],
		["matches every edit against the original file in any order", { path: "a.py", edits: [edit("b", "B"), edit("a", "A")] }, "a\nb\n", ["for 'a.py' (+2 -2)", "-1 a", "-2 b", "+1 A", "+2 B"]],
		["treats a single oldText newText input as one edit", { path: "a.py", ...edit("a", "b") }, "a\n", snippet],
		["ignores the line endings of the file", { path: "a.py", edits: [edit("a\nb", "a\nc")] }, "a\r\nb\r\n", ["for 'a.py' (+1 -1)", " 1 a", "-2 b", "+2 c"]],
		["falls back to its own snippet when the file is missing", { path: "a.py", edits: [edit("a", "b")] }, undefined, snippet],
		["falls back to its own snippet when the text is not in the file", { path: "a.py", edits: [edit("a", "b")] }, "zzz\n", snippet],
		["falls back to its own snippet when the text is not unique", { path: "a.py", edits: [edit("a", "b")] }, "a\na\n", snippet],
		["falls back to the snippets of overlapping edits", { path: "a.py", edits: [edit("ab", "x"), edit("bc", "y")] }, "abc\n", ["for 'a.py' (+2 -2)", "-1 ab", "+1 x", "-1 bc", "+1 y"]],
	] as const) {
		test(label, async () => {
			assert.deepEqual((await formatEdit(input, existing))?.split("\n"), expected);
		});
	}

	for (const input of [{ edits: [edit("a", "b")] }, { path: "a.py", edits: [{ oldText: 1 }] }]) {
		test(`declines ${JSON.stringify(input)} instead of throwing`, async () => {
			assert.equal(await formatEdit(input), undefined);
		});
	}
});

describe("formatWriteDiff", () => {
	test("diffs an overwrite against the file on disk in native format", async () => {
		assert.deepEqual((await formatWrite("a\nc\n", "a\nb\n"))?.split("\n"), ["for 'f.txt' (+1 -1)", " 1 a", "-2 b", "+2 c"]);
	});

	test("shows a new file as all additions", async () => {
		assert.deepEqual((await formatWrite("a\nb\n"))?.split("\n"), ["for 'f.txt' (new file, +2)", "+1 a", "+2 b"]);
	});

	test("declines an unreadable target instead of throwing", async () => {
		assert.equal(await formatWrite("a\n", null), undefined);
	});
});

type Details = ReturnType<typeof ask>;
const ask = (requestId: string, toolName: string, evidence: { label: string; text: string }[], requester: { agentName: string | null; forwarded: boolean } = { agentName: null, forwarded: false }, value = "f.md", kind = "tool") =>
	({ requestId, payload: { kind, request: { toolName, value, requester }, evidence } });
const input = (text: string) => [{ label: "input", text }];
const slot = () => (globalThis as any)[PREVIEW_SLOT] as Map<string, any> | undefined;

interface StartOptions {
	mode?: string;
	ready?: boolean;
	/** Renderer exported by the layout module, or false when the module is absent. */
	compact?: Compact | false;
	paint?: (text: string) => string;
}

async function start({ mode = "tui", ready = true, compact = compactStub, paint = unpainted }: StartOptions = {}) {
	(globalThis as any).compactRender = compact;
	const ext = await loadExtension("diff-preview", {
		agentDir: compact ? AGENT_DIR : "/nonexistent",
		mocks: { "@earendil-works/pi-coding-agent": { renderDiff: paint } },
	});
	const handlers: Record<string, ((payload: any, ctx?: any) => unknown)[]> = {};
	const register = (name: string, handler: any) => (handlers[name] ??= []).push(handler);
	const registered = new Map<string, any>();
	const disposed: string[] = [];
	const authorizers = new Map<string, (details: unknown) => Promise<unknown>>();
	const service = {
		registerAuthorizer: (name: string, fn: any) => (authorizers.set(name, fn), () => (authorizers.delete(name), disposed.push(name))),
		registerToolInputFormatter: (tool: string, formatter: any) => {
			if (registered.has(tool)) throw new Error(`duplicate ${tool}`);
			registered.set(tool, formatter);
			return () => (registered.delete(tool), disposed.push(tool));
		},
	};
	(globalThis as any)[SERVICES] = new Map([["sess", service]]);
	ext.module.default({ events: { on: register }, on: register });
	const notes: unknown[][] = [];
	const customCalls: unknown[][] = [];
	const ctx = {
		mode,
		cwd: "/w",
		ui: {
			notify: (...note: unknown[]) => notes.push(note),
			onTerminalInput: () => {
				throw new Error("diff-preview must not listen for keys");
			},
			custom: (...call: unknown[]) => (customCalls.push(call), Promise.resolve()),
		},
	};
	const emit = async (name: string, payload: unknown = {}) => {
		for (const handler of handlers[name] ?? []) await handler(payload, ctx);
	};
	const authorize = (details: unknown) => authorizers.get("diff-preview")!(details);
	const open = async (details: Details) => {
		await authorize(details);
		await emit("permissions:ui_prompt", { requestId: details.requestId });
		return slot()?.get(details.requestId);
	};
	await emit("session_start");
	if (ready) await emit("permissions:ready", { sessionId: "sess" });
	return { emit, authorize, open, notes, customCalls, registered, disposed, authorizers };
}

describe("registration", () => {
	test("formatters register on ready once and unregister on shutdown", async () => {
		files.set("/w/f.txt", "old\n");
		const { emit, registered, disposed } = await start({ ready: false });
		await emit("permissions:ready", { sessionId: "sess" });
		await emit("permissions:ready", { sessionId: "sess" });
		assert.deepEqual([...registered.keys()].sort(), ["edit", "write"]);
		assert.deepEqual(registered.get("write")({ path: "f.txt", content: "new\n" }).split("\n").slice(1, 3), ["-1 old", "+1 new"]);
		await emit("session_shutdown");
		assert.deepEqual([...registered.keys()], []);
		assert.deepEqual(disposed.sort(), ["diff-preview", "edit", "write"]);
	});

	test("a tool whose formatter is taken is skipped without failing", async () => {
		const { emit, registered } = await start({ ready: false });
		registered.set("edit", "other");
		for (const sessionId of ["sess", null, "unknown"]) await emit("permissions:ready", { sessionId });
		assert.equal(registered.get("edit"), "other");
		assert.equal(typeof registered.get("write"), "function");
	});

});

describe("preview slot", () => {
	test("an edit ask defers and publishes the diff for the box instead of opening an overlay", async () => {
		const { authorize, notes, customCalls } = await start();
		const text = ["for 'f.md' (+2 -0)", "+line 0", "+line 1"].join("\n");
		const details = ask("r1", "edit", input(text));
		assert.deepEqual(await authorize(details), { kind: "defer" });
		const preview = slot()!.get("r1");
		assert.equal(preview.title, "Diff for 'f.md' (+2 -0)");
		assert.deepEqual(preview.lines(40, undefined), ["C|+line 0", "C|+line 1"]);
		assert.deepEqual(details.payload.evidence, input("for 'f.md' (+2 -0)"));
		assert.deepEqual([customCalls, notes], [[], []]);
		await authorize(ask("r2", "edit", input("+a"), { agentName: "worker-1", forwarded: true }));
		assert.equal(slot()!.get("r2").title, "Diff for 'f.md' from worker-1");
	});

	test("a long bash command is published as plain text and a short one is not", async () => {
		const { open } = await start();
		const long = "echo " + "x".repeat(130);
		const shown = await open(ask("long", "bash", [], undefined, long, "bash"));
		assert.equal(shown.title, "bash");
		assert.deepEqual(shown.lines(200, undefined), [long]);
		assert.equal(await open(ask("short", "bash", [], undefined, "ls -la", "bash")), undefined);
		assert.deepEqual([...slot()!.keys()], ["long"]);
	});

	test("long text previews of any tool and forwarded asks are titled and trim the dialog", async () => {
		const { open } = await start();
		const forwarded = { agentName: "worker-1", forwarded: true };
		const full = ask("b", "bash", [{ label: "full command", text: "cd d\n" + "y".repeat(150) }], forwarded, "cd d", "bash");
		const tool = ask("t", "grep", input("a\nb"));
		const bash = await open(full);
		const grep = await open(tool);
		assert.equal(bash.title, "bash from worker-1");
		const lines = bash.lines(60, undefined);
		assert.equal(lines[0], "cd d");
		assert.equal(lines.slice(1).join(""), "y".repeat(150));
		assert.deepEqual([grep.title, grep.lines(60, undefined)], ["grep", ["a", "b"]]);
		assert.deepEqual(full.payload.evidence, [{ label: "full command", text: "cd d" }]);
		assert.deepEqual(tool.payload.evidence, input("a"));
	});

	test("a text preview never loads the compact renderer or paints as a diff", async () => {
		const { open, notes } = await start({
			compact: () => {
				throw new Error("should not draw text");
			},
			paint: (text) => `<painted>${text}`,
		});
		const preview = await open(ask("r1", "bash", [], undefined, "echo a\necho b", "bash"));
		assert.deepEqual([preview.lines(40, undefined), notes], [["echo a", "echo b"], []]);
	});

	test("a long dialog value is clipped to a short head", async () => {
		const { authorize } = await start();
		const details = ask("r1", "mcp", input("z".repeat(300)));
		await authorize(details);
		assert.equal(details.payload.evidence[0].text, "z".repeat(117) + "...");
	});

	test("a decision withdraws only its own preview", async () => {
		const { open, emit } = await start();
		await open(ask("r1", "edit", input("+a")));
		await open(ask("r2", "write", input("+b")));
		await emit("permissions:decision", { requestId: "other" });
		assert.deepEqual([...slot()!.keys()], ["r1", "r2"]);
		await emit("permissions:decision", { requestId: "r1" });
		await emit("permissions:decision", { requestId: "r1" });
		assert.deepEqual([...slot()!.keys()], ["r2"]);
	});

	test("shutdown and a new session withdraw every preview", async () => {
		const { open, emit } = await start();
		await open(ask("r1", "edit", input("+a")));
		await emit("session_start");
		assert.deepEqual([...slot()!.keys()], []);
		await open(ask("r2", "edit", input("+a")));
		await emit("session_shutdown");
		assert.deepEqual([...slot()!.keys()], []);
	});

	test("unrelated or malformed asks publish nothing and leave the dialog alone", async () => {
		const { authorize } = await start();
		const bash = ask("b", "bash", [{ label: "full command", text: "ls -la" }], undefined, "ls", "bash");
		const verdicts = [
			await authorize(bash),
			await authorize(ask("e", "edit", [{ label: "command", text: "x" }])),
			await authorize(ask("g", "grep", [{ label: "other", text: "x\ny" }])),
			await authorize(ask("s", "grep", input("one line"))),
			await authorize(null),
			await authorize({ requestId: "m", payload: {} }),
		];
		assert.deepEqual(verdicts, Array(6).fill({ kind: "defer" }));
		assert.equal(slot()?.size ?? 0, 0);
		assert.equal(bash.payload.evidence[0].text, "ls -la");
	});

	test("outside the tui the dialog is left whole and nothing is published", async () => {
		const { authorize } = await start({ mode: "print" });
		const details = ask("r1", "edit", input("+a\n+b"));
		assert.deepEqual(await authorize(details), { kind: "defer" });
		assert.equal(slot()?.size ?? 0, 0);
		assert.equal(details.payload.evidence[0].text, "+a\n+b");
	});
});

describe("rendering without the compact renderer", () => {
	test("long lines wrap instead of being cut", async () => {
		const { open } = await start({ compact: false });
		const lines = (await open(ask("r1", "edit", input("+" + "y".repeat(50))))).lines(20, undefined);
		assert.equal(lines.join(""), "+" + "y".repeat(50));
		assert.deepEqual(new Set(lines.map((row: string) => row.length)), new Set([20, 11]));
	});

	test("the diff is painted by pi", async () => {
		const paint = (text: string) => text.split("\n").map((row) => `\x1b[32m${row}\x1b[39m`).join("\n");
		const { open } = await start({ compact: false, paint });
		const preview = await open(ask("r1", "edit", input("for 'f.md' (+1 -0)\n+1 " + "y".repeat(20))));
		assert.deepEqual(preview.lines(80, undefined), ["\x1b[32m+1 " + "y".repeat(20) + "\x1b[39m"]);
	});

	test("an unavailable renderer falls back and warns once per session", async () => {
		const { open, emit, notes } = await start({ compact: false });
		const shownFor = async (requestId: string) =>
			(await open(ask(requestId, "edit", input("for 'f.md' (+1 -0)\n+1 a")))).lines(30, undefined)[0];
		const rows = [await shownFor("r1"), await shownFor("r2")];
		assert.equal(notes.length, 1);
		await emit("session_start");
		rows.push(await shownFor("r3"));
		assert.deepEqual(rows, ["+1 a", "+1 a", "+1 a"]);
		assert.deepEqual(notes, [WARNING, WARNING]);
	});
});

describe("rendering with the compact renderer", () => {
	test("the diff is drawn with the box theme", async () => {
		const calls: unknown[][] = [];
		const theme = { fg: (_color: string, text: string) => text };
		const { open, notes } = await start({ compact: (...call) => (calls.push(call), { render: () => ["drawn"] }) });
		const preview = await open(ask("r1", "write", input("for 'src/x.py' (+1 -0)\n+1 new")));
		assert.deepEqual(preview.lines(60, theme), ["drawn"]);
		assert.deepEqual(calls, [["", "+1 new", "src/x.py", theme]]);
		assert.equal(preview.title, "Diff for 'src/x.py' (+1 -0)");
		assert.deepEqual(notes, []);
	});

	test("a renderer that throws falls back and warns once", async () => {
		const { open, notes } = await start({
			compact: () => {
				throw new Error("bad theme");
			},
		});
		const preview = await open(ask("r1", "edit", input("for 'f.md' (+1 -0)\n+1 a")));
		preview.lines(30, undefined);
		assert.equal(preview.lines(30, undefined)[0], "+1 a");
		assert.deepEqual(notes, [WARNING]);
	});
});
