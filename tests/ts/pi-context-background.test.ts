import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, mock, test } from "node:test";
import { useEnv } from "./helpers.ts";
import { openAsks } from "../../src/llm_prompts/prompts/pi/extensions/pending-asks.ts";
import { Background, registerBackgroundHooks, useBoardCapacity } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/background.ts";
import { LiveView } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/live-view.ts";
import { Registry, type Run } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";

const run = (id: string, patch: Partial<Run> = {}): Run => ({ id, name: id, role: "reader", state: "running", task: "t", startedAt: 1, ...patch });
const done = (code = "done") => ({ state: "done" as const, outcome: code, ref: "rc" });

useEnv({ PI_CONTEXT_RUN_ID: undefined, PI_CONTEXT_ROLE: undefined });
let sent: [{ customType: string; content: string }, Record<string, unknown>][];
let appended: { type: string; customType: string; data: any }[];
let registry: Registry;
let background: Background;
const ctx = (idle = true) => ({ isIdle: () => idle }) as any;
const finishHeld = (...args: Parameters<Background["finish"]>) => {
	void background.hold();
	background.finish(...args);
};
beforeEach(() => {
	sent = [];
	appended = [];
	registry = new Registry();
	background = new Background({ sendMessage: (message: any, options: any) => sent.push([message, options]), appendEntry: (customType: string, data: any) => appended.push({ type: "custom", customType, data }) } as any, registry);
	registry.start(run("a"));
	registry.start(run("b"));
});

describe("Background", () => {
	test("each ASK line of a finished run is pinned as a pending ask named after the fork", () => {
		background.finish(ctx(), "a", { state: "blocked", outcome: "blocked-on-user", ref: "rc" }, "OUTCOME blocked-on-user ref:rc\nASK: A or B?\nASK: keep it?");
		assert.deepEqual(openAsks(appended), [
			{ id: "fork-a-a-1", text: "a: A or B?" },
			{ id: "fork-a-a-2", text: "a: keep it?" },
		]);
	});

	test("each finished run wakes an idle main at once, while another run is still live", () => {
		background.finish(ctx(), "a", done(), "OUTCOME done ref:rc");
		assert.deepEqual(sent, [[{ customType: "pi-context-results", content: "[fork a done] ref rc\n1 fork still running.", display: true }, { deliverAs: "steer", triggerTurn: true }]]);
		background.finish(ctx(), "b", done(), "OUTCOME done ref:rc\nASK: keep it?");
		assert.equal(sent[1][0].content, "[fork b done] ASK: keep it? ref rc\nPinned: fork-b-b-1. They clear at the end of this turn unless you put them to the user with ask_user.\n0 forks still running.");
		assert.equal(background.digest(), undefined);
	});

	test("a run that finishes while main is busy or compacting starts no turn and waits in the digest", () => {
		background.finish(ctx(false), "a", done(), "OUTCOME done ref:rc");
		assert.deepEqual(sent, []);
		assert.equal(background.digest(), "[fork a done] ref rc\n1 fork still running.");
	});

	test("a run that needs main wakes it at once and the digest keeps what it asks", () => {
		background.finish(ctx(), "a", { state: "blocked", outcome: "blocked-on-user", ref: "rc" }, "OUTCOME blocked-on-user ref:rc\nASK: A or B?");
		assert.equal(sent.length, 1);
		assert.equal(sent[0][0].content, "[fork a blocked-on-user] ASK: A or B? ref rc\nPinned: fork-a-a-1. They clear at the end of this turn unless you put them to the user with ask_user.\n1 fork still running.");
	});

	test("a digest not yet sent is handed over once", () => {
		finishHeld(ctx(), "a", done(), "OUTCOME done ref:rc", "[merge: landed abc]");
		assert.equal(background.digest(), "[fork a done] [merge: landed abc] ref rc\n1 fork still running.");
		assert.equal(background.digest(), undefined);
	});

	test("with a capacity, the digest names the free fork slots and up to five ready board tasks", () => {
		background.capacity = { limit: () => 4, ready: () => ["t1", "t2", "t3", "t4", "t5", "t6"] };
		finishHeld(ctx(), "a", done(), "OUTCOME done ref:rc");
		assert.equal(background.digest(), "[fork a done] ref rc\n1 fork still running. [slots: 3 free | ready: t1, t2, t3, t4, t5]");
		background.capacity = { limit: () => 1, ready: () => [] };
		finishHeld(ctx(), "b", done(), "OUTCOME done ref:rc");
		assert.equal(background.digest(), "[fork b done] ref rc\n0 forks still running. [slots: 1 free]");
	});

	test("cancel aborts the run, and a later finish of it is ignored", () => {
		const signal = background.track("a");
		assert.equal(background.cancel("a")?.state, "cancelled");
		assert.equal(signal.aborted, true);
		background.finish(ctx(), "a", done(), "OUTCOME done ref:rc");
		assert.equal(registry.all().find((r) => r.id === "a")?.state, "cancelled");
		assert.equal(background.digest(), undefined);
		assert.equal(background.cancel("nope"), undefined);
	});

	test("hold ends when a run finishes and sends no wake of its own", async () => {
		const hold = background.hold();
		background.finish(ctx(), "a", done(), "OUTCOME done ref:rc");
		await hold;
		assert.deepEqual(sent, []);
		assert.equal(background.digest(), "[fork a done] ref rc\n1 fork still running.");
		assert.equal((background as any).holding, false);
	});

	test("hold also ends when a run needs main, and when the live runs are cancelled", async () => {
		const failing = background.hold();
		background.finish(ctx(), "a", { state: "failed", outcome: "failed", ref: "rc" }, "OUTCOME failed ref:rc");
		await failing;
		const cancelled = background.hold();
		background.cancel("b");
		await cancelled;
	});

	test("hold ends after its maximum time even while a run is live", async () => {
		await background.hold(10);
		assert.equal(registry.live().length, 2);
		assert.equal((background as any).holding, false);
	});

	test("shutdown stops every live background run and marks it lost", () => {
		const signal = background.track("a");
		background.shutdown();
		assert.equal(signal.aborted, true);
		assert.deepEqual(registry.all().map((r) => r.state), ["lost", "lost"]);
	});
});

describe("hooks", () => {
	let handlers: Record<string, (event: any, ctx: any) => any>;
	let appended: [string, any][];
	const boot = () => {
		handlers = {};
		const pi = { on: (event: string, handler: any) => (handlers[event] = handler), sendMessage: (message: any, options: any) => sent.push([message, options]), appendEntry: (type: string, data: any) => appended.push([type, data]) };
		background = new Background(pi as any, registry);
		registerBackgroundHooks(pi as any, background, registry);
	};
	beforeEach(() => {
		appended = [];
		boot();
	});
	const session = (...data: Run[]) => ({ ...ctx(), hasUI: true, sessionManager: { getEntries: () => data.map((run) => ({ type: "custom", customType: "pi-context-run", data: run })) } });

	test("board capacity folds the board of the session's directory at start and again when a run ends", async () => {
		const on: Record<string, (event: any, ctx: any) => any> = {};
		const folds: string[] = [];
		const boards = [["early"], ["t1", "t2"]];
		useBoardCapacity({ on: (event: string, handler: any) => (on[event] = handler) } as any, background, () => 5, async (cwd) => (folds.push(cwd), boards[folds.length - 1]));
		on.session_start({}, { cwd: "/repo" });
		await new Promise(setImmediate);
		background.finish(ctx(false), "a", done(), "OUTCOME done ref:rc");
		await new Promise(setImmediate);
		assert.deepEqual(folds, ["/repo", "/repo"]);
		assert.equal(background.digest(), "[fork a done] ref rc\n1 fork still running. [slots: 4 free | ready: t1, t2]");
	});

	test("board capacity folds the board again before a board tool's result returns, and only once per run end", async () => {
		const on: Record<string, (event: any, ctx: any) => any> = {};
		const boards = [["t1", "t2"], ["t2"], ["x"]];
		let folds = 0;
		useBoardCapacity({ on: (event: string, handler: any) => (on[event] = handler) } as any, background, () => 5, async () => boards[folds++]);
		on.session_start({}, { cwd: "/repo" });
		await new Promise(setImmediate);
		await on.tool_result({ toolName: "read" }, {});
		assert.equal(folds, 1);
		await on.tool_result({ toolName: "tower_do_patch" }, {});
		assert.equal(folds, 2);
		background.finish(ctx(false), "a", done(), "OUTCOME done ref:rc");
		assert.equal(background.digest(), "[fork a done] ref rc\n1 fork still running. [slots: 4 free | ready: t2]");
		await new Promise(setImmediate);
		registry.update("a", { unread: undefined });
		await new Promise(setImmediate);
		assert.equal(folds, 3);
	});

	test("an idle main woken by a fork that finished its board task gets the ready list folded after the fork ended", async () => {
		const on: Record<string, (event: any, ctx: any) => any> = {};
		const boards = [["t1", "t2"], ["t2"]];
		let folds = 0;
		useBoardCapacity({ on: (event: string, handler: any) => (on[event] = handler) } as any, background, () => 5, async () => boards[folds++]);
		on.session_start({}, { cwd: "/repo" });
		await new Promise(setImmediate);
		background.finish(ctx(), "a", done(), "OUTCOME done ref:rc");
		await new Promise(setImmediate);
		assert.deepEqual(sent.map(([message]) => message.content), ["[fork a done] ref rc\n1 fork still running. [slots: 4 free | ready: t2]"]);
	});

	test("a main that turns busy while the board folds gets no wake, and its next run starts with the digest", async () => {
		const on: Record<string, (event: any, ctx: any) => any> = {};
		useBoardCapacity({ on: (event: string, handler: any) => (on[event] = handler) } as any, background, () => 5, async () => ["t2"]);
		on.session_start({}, { cwd: "/repo" });
		let idle = true;
		background.finish({ isIdle: () => idle } as any, "a", done(), "OUTCOME done ref:rc");
		idle = false;
		await new Promise(setImmediate);
		assert.deepEqual(sent, []);
		assert.equal(handlers.before_agent_start({}, ctx()).message.content, "[fork a done] ref rc\n1 fork still running. [slots: 4 free | ready: t2]");
	});

	test("board capacity folds the board again before a tower_do_status result returns", async () => {
		const on: Record<string, (event: any, ctx: any) => any> = {};
		let folds = 0;
		useBoardCapacity({ on: (event: string, handler: any) => (on[event] = handler) } as any, background, () => 5, async () => (folds++, []));
		on.session_start({}, { cwd: "/repo" });
		await on.tool_result({ toolName: "tower_do_status" }, {});
		assert.equal(folds, 2);
	});

	test("the next run starts with the digest of results that did not wake main, once", () => {
		finishHeld(ctx(), "a", done(), "OUTCOME done ref:rc");
		assert.deepEqual(handlers.before_agent_start({}, ctx()), { message: { customType: "pi-context-results", content: "[fork a done] ref rc\n1 fork still running.", display: true } });
		assert.equal(handlers.before_agent_start({}, ctx()), undefined);
	});

	test("runs that finish during one turn of a busy main reach it in one message at the turn's end, with the live fork count", () => {
		background.finish(ctx(false), "a", done(), "OUTCOME done ref:rc");
		background.finish(ctx(false), "b", done(), "OUTCOME done ref:rc");
		handlers.turn_end({ message: { role: "assistant", stopReason: "toolUse" } }, ctx(false));
		assert.deepEqual(sent, [[{ customType: "pi-context-results", content: "[fork a done] ref rc\n[fork b done] ref rc\n0 forks still running.", display: true }, { deliverAs: "steer", triggerTurn: true }]]);
		handlers.turn_end({ message: { role: "assistant", stopReason: "toolUse" } }, ctx(false));
		assert.equal(sent.length, 1);
	});

	test("a result of a turn that ends aborted is not queued to steer, so the next run gets it once", () => {
		const main = { ...ctx(false), hasUI: true, sessionManager: { getBranch: () => [] } };
		background.finish(main, "a", done(), "OUTCOME done ref:rc");
		handlers.turn_end({ message: { role: "assistant", stopReason: "aborted" } }, main);
		handlers.agent_end({ messages: [{ role: "assistant", stopReason: "aborted" }] }, main);
		handlers.agent_settled({ aborted: true }, main);
		assert.deepEqual(sent, []);
		assert.equal(handlers.before_agent_start({}, ctx())?.message.content, "[fork a done] ref rc\n1 fork still running.");
	});

	test("a run that finishes after main's last turn ended, before it settles, wakes main once when it settles", () => {
		const main = { ...ctx(false), hasUI: true, sessionManager: { getBranch: () => [] } };
		handlers.turn_end({ message: { role: "assistant", stopReason: "stop" } }, main);
		background.finish(main, "a", done(), "OUTCOME done ref:rc");
		handlers.agent_end({ messages: [{ role: "assistant", stopReason: "stop" }] }, main);
		handlers.agent_settled({ aborted: false }, main);
		assert.deepEqual(sent, [[{ customType: "pi-context-results", content: "[fork a done] ref rc\n1 fork still running.", display: true }, { deliverAs: "steer", triggerTurn: true }]]);
		handlers.agent_settled({ aborted: false }, main);
		assert.equal(sent.length, 1);
	});

	test("a run that finishes after main's last turn ended in an error does not wake main when it settles", () => {
		const main = { ...ctx(false), hasUI: true, sessionManager: { getBranch: () => [] } };
		handlers.turn_end({ message: { role: "assistant", stopReason: "error" } }, main);
		background.finish(main, "a", done(), "OUTCOME done ref:rc");
		handlers.agent_end({ messages: [{ role: "assistant", stopReason: "error" }] }, main);
		handlers.agent_settled({ aborted: false }, main);
		assert.deepEqual(sent, []);
	});

	test("a session appends the digest when it settles and continues with it", async () => {
		finishHeld(ctx(), "a", done(), "OUTCOME done ref:rc");
		const settled = await handlers.agent_before_settle({ entries: [] }, { ...ctx(), hasUI: true });
		assert.deepEqual(settled, { entries: [{ type: "custom_message", customType: "pi-context-results", content: "[fork a done] ref rc\n1 fork still running.", display: true }], continue: true });
		assert.equal(await handlers.agent_before_settle({ entries: [] }, { ...ctx(), hasUI: true }), undefined);
	});

	test("a session without a UI waits for a live run to finish when it settles, then continues with its digest", async () => {
		const settling = handlers.agent_before_settle({ entries: [] }, { ...ctx(), hasUI: false });
		background.finish(ctx(), "a", done(), "OUTCOME done ref:rc");
		const settled = await settling;
		assert.equal(settled.continue, true);
		assert.equal(settled.entries[0].content, "[fork a done] ref rc\n1 fork still running.");
		assert.deepEqual(sent, []);
	});

	describe("in a team", () => {
		useEnv({ PI_CONTEXT_ROLE: "team", PI_CONTEXT_RUN_ID: "team1" });

		test("a session with a UI waits for a live member to finish when it settles", async () => {
			const settling = handlers.agent_before_settle({ entries: [] }, { ...ctx(), hasUI: true });
			background.finish(ctx(), "a", done(), "OUTCOME done ref:rc");
			assert.equal((await settling).entries[0].content, "[fork a done] ref rc\n1 fork still running.");
		});

		test("a shutdown stops every member, waits for each to end and releases the wait, so a cancelled team leaves none running", async () => {
			const signal = background.track("a");
			let ended = false;
			background.follow("a", new Promise<void>((resolve) => signal.addEventListener("abort", () => setTimeout(() => ((ended = true), resolve()), 20))));
			const settling = handlers.agent_before_settle({ entries: [] }, { ...ctx(), hasUI: true });
			await handlers.session_shutdown({ reason: "quit" }, ctx());
			assert.equal(ended, true);
			await settling;
			assert.equal(registry.get("a")?.state, "lost");
		});

		test("a team restores only the runs it started", () => {
			handlers.session_start({ reason: "startup" }, session(run("m1", { owner: "team1", state: "done", unread: "u" }), run("main-run", { state: "done", unread: "u" }), run("m2", { owner: "other", state: "done", unread: "u" })));
			assert.deepEqual(registry.all().map((each) => each.id).filter((id) => ["m1", "main-run", "m2"].includes(id)), ["m1"]);
		});
	});

	test("a run's every change is saved as an entry", () => {
		handlers.session_start({ reason: "startup" }, session());
		registry.start(run("a"));
		registry.update("a", { state: "landing" });
		assert.deepEqual(appended.map(([type, data]) => [type, data.id, data.state]), [["pi-context-run", "a", "running"], ["pi-context-run", "a", "landing"]]);
	});

	test("a new session restores only runs that are unread, have an open ask or can be continued", () => {
		const files = fs.mkdtempSync(path.join(os.tmpdir(), "bound-"));
		fs.writeFileSync(path.join(files, "seed.jsonl"), "");
		const asked = { type: "custom", customType: "pending-asks", data: { action: "add", id: "fork-asked-asked-1", text: "asked: q?" } };
		const sessionWith = (...runs: Run[]) => ({ ...session(...runs), sessionManager: { getEntries: () => [...session(...runs).sessionManager.getEntries(), asked] } });
		handlers.session_start({ reason: "startup" }, sessionWith(
			run("old", { state: "done" }),
			run("unread", { state: "done", unread: "u" }),
			run("asked", { state: "done" }),
			run("warm", { state: "done", files, lastRequestAt: Date.now() }),
		));
		fs.rmSync(files, { recursive: true });
		assert.deepEqual(registry.all().map((r) => r.id), ["unread", "asked", "warm"]);
	});

	test("a session whose pi is stale stops saving and does not break the registry", () => {
		const pi = { on: (event: string, handler: any) => (handlers[event] = handler), appendEntry: () => { throw new Error("stale"); } };
		registerBackgroundHooks(pi as any, background, registry);
		handlers.session_start({ reason: "startup" }, session());
		registry.start(run("c"));
		assert.doesNotThrow(() => registry.update("c", { state: "done" }));
	});

	test("a new session rebuilds the runs and tells main once about those that were still live", () => {
		handlers.session_start({ reason: "startup" }, session(run("x"), run("y", { state: "done", unread: "u" }), run("x", { state: "landing" })));
		assert.deepEqual(registry.all().map((r) => [r.id, r.state]), [["y", "done"]]);
		assert.deepEqual(appended.map(([, data]) => [data.id, data.state]), [["x", "lost"]]);
		assert.deepEqual(sent.map(([message, options]) => [message.content, options]), [["[fork x lost] its session ended before it finished. Task: t", { deliverAs: "nextTurn" }]]);
	});

	describe("check-in note", () => {
		const MINUTE = 60_000;
		let listeners: ((record: any) => void)[];
		const emit = (record: object) => listeners.forEach((listener) => listener(record));
		const call = (command: string) => emit({ type: "tool_execution_start", toolName: "bash", args: { command } });
		const notes = () => handlers.tool_result({ content: [{ type: "text", text: "out" }] }, ctx())?.content.slice(1).map((block: { text: string }) => block.text);
		beforeEach(() => {
			mock.timers.enable({ apis: ["Date"], now: 100 * MINUTE });
			listeners = [];
			background.view = new LiveView(registry);
			registry.update("a", { startedAt: 100 * MINUTE });
			registry.update("b", { state: "done" });
			background.attach("a", { steer: async () => undefined, watch: (listener) => (listeners.push(listener), () => undefined) });
			emit({ type: "message_end", message: { role: "assistant", content: [] } });
			call("git diff --stat");
		});
		afterEach(() => mock.timers.reset());

		test("a fork past the interval is named with its turns and last call on a tool result, once per interval", () => {
			mock.timers.setTime(104 * MINUTE);
			assert.equal(notes(), undefined);
			mock.timers.setTime(106 * MINUTE);
			assert.deepEqual(notes(), ["[fork a] still running after 6m, 1 turn, last call bash: git diff --stat. Check on it with fork_steer, or stop it with fork_cancel."]);
			assert.equal(notes(), undefined);
			mock.timers.setTime(112 * MINUTE);
			assert.match(notes()?.[0], /after 12m/);
		});

		test("a fork is not noted while an llm-prompts watch call runs, and is again once it ends", () => {
			emit({ type: "tool_execution_start", toolCallId: "w1", toolName: "bash", args: { command: "timeout 540 llm-prompts watch gh-pr alexfayers/llm-prompts#1 --until merged" } });
			call("git status");
			mock.timers.setTime(120 * MINUTE);
			assert.equal(notes(), undefined);
			emit({ type: "tool_execution_end", toolCallId: "w1", toolName: "bash" });
			assert.match(notes()?.[0], /after 20m, 1 turn, last call bash: git status/);
		});

		test("the llmPrompts.forks.checkInMinutes setting sets the interval", () => {
			const pi = { on: (event: string, handler: any) => (handlers[event] = handler), getSettings: () => ({ llmPrompts: { forks: { checkInMinutes: 2 } } }) };
			registerBackgroundHooks(pi as any, background, registry);
			mock.timers.setTime(103 * MINUTE);
			assert.match(notes()?.[0], /after 3m/);
		});
	});

	test("a woken run's fork pins clear when it settles, unless its ask_user was cancelled", () => {
		const branch = () => appended.map(([customType, data]) => ({ type: "custom", customType, data }));
		const main = { ...ctx(), hasUI: false, sessionManager: { getBranch: branch } };
		const wakeWith = (name: string, messages: unknown[]) => {
			registry.start(run(name));
			background.finish(main, name, { state: "blocked", outcome: "blocked-on-user", ref: "rc" }, "OUTCOME blocked-on-user ref:rc\nASK: A or B?");
			assert.match(sent.at(-1)![0].content, new RegExp(`\nPinned: fork-${name}-${name}-1\\. They clear at the end of this turn unless you put them to the user with ask_user\\.\n2 forks still running\\.$`));
			handlers.agent_end({ messages }, main);
			handlers.agent_settled({ aborted: false }, main);
		};
		wakeWith("x", [{ role: "assistant" }]);
		wakeWith("y", [{ role: "toolResult", toolName: "ask_user", isError: false, details: { cancelled: true } }]);
		assert.deepEqual(openAsks(branch()).map((ask) => ask.id), ["fork-y-y-1"]);
	});

	test("a result stays unread until a turn that delivered it settles, so an aborted or failed turn loses none", () => {
		const main = { ...ctx(), hasUI: false, sessionManager: { getBranch: () => [] } };
		finishHeld(main, "a", done(), "OUTCOME done ref:rc");
		const settle = (aborted: boolean, ...messages: unknown[]) => {
			assert.equal(background.digest(), `${registry.get("a")?.unread}\n1 fork still running.`);
			handlers.agent_end({ messages }, main);
			handlers.agent_settled({ aborted }, main);
		};
		settle(true);
		settle(false, { role: "assistant", stopReason: "error" });
		assert.equal(registry.get("a")?.unread, "[fork a done] ref rc");
		settle(false, { role: "assistant", stopReason: "stop" });
		assert.equal(registry.get("a")?.unread, undefined);
	});

	test("the pins of a result whose turn failed are announced again with it, and clear once a later turn settles", () => {
		const branch = () => appended.map(([customType, data]) => ({ type: "custom", customType, data }));
		const main = { ...ctx(), hasUI: false, sessionManager: { getBranch: branch } };
		finishHeld(main, "a", { state: "blocked", outcome: "blocked-on-user", ref: "rc" }, "OUTCOME blocked-on-user ref:rc\nASK: A or B?");
		const pinned = /Pinned: fork-a-a-1\./;
		const turn = (stopReason: string) => {
			const content = handlers.before_agent_start({}, main)?.message.content;
			handlers.agent_end({ messages: [{ role: "assistant", stopReason }] }, main);
			handlers.agent_settled({ aborted: false }, main);
			return content;
		};
		assert.match(turn("error"), pinned);
		assert.match(turn("aborted"), pinned);
		assert.deepEqual(openAsks(branch()).map((ask) => ask.id), ["fork-a-a-1"]);
		assert.match(turn("stop"), pinned);
		assert.deepEqual(openAsks(branch()), []);
	});

	test("a result that arrived while main was busy reaches the session that restarts after a quit", () => {
		handlers.session_start({ reason: "startup" }, session());
		registry.start(run("late"));
		background.finish(ctx(false), "late", done(), "OUTCOME done ref:rc");
		handlers.session_shutdown({ reason: "quit" }, ctx());
		registry = new Registry();
		boot();
		handlers.session_start({ reason: "resume" }, session(...appended.map(([, data]) => data)));
		assert.match(handlers.before_agent_start({}, ctx())?.message.content ?? "", /^\[fork late done\] ref rc\n0 forks still running\.$/);
		assert.equal(handlers.before_agent_start({}, ctx()), undefined);
	});

	test("a run a reload cut off is reported as lost to the reload, with its kept worktree", () => {
		handlers.session_start({ reason: "startup" }, session());
		registry.start(run("w", { worktree: "/wt/w" }));
		appended = [];
		handlers.session_shutdown({ reason: "reload" }, ctx());
		assert.deepEqual(appended.map(([, data]) => [data.id, data.state, data.endedBy]), [["w", "running", "reload"]]);
		sent = [];
		handlers.session_start({ reason: "reload" }, session(...appended.map(([, data]) => data)));
		assert.deepEqual(sent.map(([message]) => message.content), ["[fork w lost] a /reload ended it before it finished. Its worktree /wt/w is kept. Task: t"]);
	});

	test("a run that reload_now's reload ended and can resume is not reported as lost", () => {
		const files = fs.mkdtempSync(path.join(os.tmpdir(), "resume-"));
		fs.writeFileSync(path.join(files, "seed.jsonl"), "");
		handlers.session_start({ reason: "startup" }, session());
		registry.start(run("w", { files }));
		appended = [];
		handlers.session_shutdown({ reason: "reload" }, ctx());
		sent = [];
		(globalThis as any)[Symbol.for("llm-prompts.reload-now.requested")] = true;
		try {
			handlers.session_start({ reason: "reload" }, session(...appended.map(([, data]) => data)));
		} finally {
			delete (globalThis as any)[Symbol.for("llm-prompts.reload-now.requested")];
		}
		assert.deepEqual(sent, []);
	});

	test("shutdown marks the live runs lost without saving that, so the next session reports them", () => {
		handlers.session_start({ reason: "startup" }, session());
		registry.start(run("a"));
		registry.start(run("b"));
		appended = [];
		handlers.session_shutdown({ reason: "quit" }, ctx());
		assert.deepEqual(registry.all().map((r) => r.state), ["lost", "lost"]);
		assert.deepEqual(appended.map(([, data]) => [data.state, data.endedBy]), [["running", "quit"], ["running", "quit"]]);
		appended = [];
		registry.start(run("late"));
		assert.deepEqual(appended, []);
	});
});
