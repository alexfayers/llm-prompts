import assert from "node:assert/strict";
import { beforeEach, describe, test } from "node:test";
import { openAsks } from "../../src/llm_prompts/prompts/pi/extensions/pending-asks.ts";
import { Background, registerBackgroundHooks } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/background.ts";
import { Registry, type Run } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";

const run = (id: string, patch: Partial<Run> = {}): Run => ({ id, name: id, role: "reader", background: true, state: "running", task: "t", startedAt: 1, ...patch });
const done = (code = "done") => ({ state: "done" as const, outcome: code, ref: "rc" });

let sent: [{ customType: string; content: string }, Record<string, unknown>][];
let appended: { type: string; customType: string; data: any }[];
let registry: Registry;
let background: Background;
const ctx = (idle = true) => ({ isIdle: () => idle }) as any;
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
		assert.deepEqual(sent, [[{ customType: "pi-context-results", content: "[fork a done] ref rc", display: true }, { triggerTurn: true }]]);
		background.finish(ctx(), "b", done(), "OUTCOME done ref:rc\nASK: keep it?");
		assert.equal(sent[1][0].content, "[fork b done] ASK: keep it? ref rc\nPinned: fork-b-b-1. They clear at the end of this turn unless you put them to the user with ask_user.");
		assert.equal(background.digest(), undefined);
	});

	test("a run that finishes while main is busy waits in the digest", () => {
		background.finish(ctx(false), "a", done(), "OUTCOME done ref:rc");
		assert.deepEqual(sent, []);
		assert.equal(background.digest(), "[fork a done] ref rc");
	});

	test("a run that needs main wakes it at once and the digest keeps what it asks", () => {
		background.finish(ctx(), "a", { state: "blocked", outcome: "blocked-on-user", ref: "rc" }, "OUTCOME blocked-on-user ref:rc\nASK: A or B?");
		assert.equal(sent.length, 1);
		assert.equal(sent[0][0].content, "[fork a blocked-on-user] ASK: A or B? ref rc\nPinned: fork-a-a-1. They clear at the end of this turn unless you put them to the user with ask_user.");
	});

	test("a digest not yet sent is handed over once", () => {
		background.finish(ctx(false), "a", done(), "OUTCOME done ref:rc", "[merge: landed abc]");
		assert.equal(background.digest(), "[fork a done] [merge: landed abc] ref rc");
		assert.equal(background.digest(), undefined);
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
		assert.equal(background.digest(), "[fork a done] ref rc");
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

	test("the next run starts with the digest of results that did not wake main, once", () => {
		background.finish(ctx(false), "a", done(), "OUTCOME done ref:rc");
		assert.deepEqual(handlers.before_agent_start({}, ctx()), { message: { customType: "pi-context-results", content: "[fork a done] ref rc", display: true } });
		assert.equal(handlers.before_agent_start({}, ctx()), undefined);
	});

	test("a session appends the digest when it settles and continues with it", async () => {
		background.finish(ctx(false), "a", done(), "OUTCOME done ref:rc");
		const settled = await handlers.agent_before_settle({ entries: [] }, { ...ctx(), hasUI: true });
		assert.deepEqual(settled, { entries: [{ type: "custom_message", customType: "pi-context-results", content: "[fork a done] ref rc", display: true }], continue: true });
		assert.equal(await handlers.agent_before_settle({ entries: [] }, { ...ctx(), hasUI: true }), undefined);
	});

	test("a session without a UI waits for a live run to finish when it settles, then continues with its digest", async () => {
		const settling = handlers.agent_before_settle({ entries: [] }, { ...ctx(), hasUI: false });
		background.finish(ctx(), "a", done(), "OUTCOME done ref:rc");
		const settled = await settling;
		assert.equal(settled.continue, true);
		assert.equal(settled.entries[0].content, "[fork a done] ref rc");
		assert.deepEqual(sent, []);
	});

	test("a background run's every change is saved as an entry, and only a background run's", () => {
		handlers.session_start({ reason: "startup" }, session());
		registry.start(run("c", { background: false }));
		registry.start(run("a"));
		registry.update("a", { state: "landing" });
		assert.deepEqual(appended.map(([type, data]) => [type, data.id, data.state]), [["pi-context-run", "a", "running"], ["pi-context-run", "a", "landing"]]);
	});

	test("a session whose pi is stale stops saving and does not break the registry", () => {
		const pi = { on: (event: string, handler: any) => (handlers[event] = handler), appendEntry: () => { throw new Error("stale"); } };
		registerBackgroundHooks(pi as any, background, registry);
		handlers.session_start({ reason: "startup" }, session());
		registry.start(run("c"));
		assert.doesNotThrow(() => registry.update("c", { state: "done" }));
	});

	test("a new session rebuilds the runs and tells main once about those that were still live", () => {
		handlers.session_start({ reason: "startup" }, session(run("x"), run("y", { state: "done" }), run("x", { state: "landing" })));
		assert.deepEqual(registry.all().map((r) => [r.id, r.state]), [["x", "lost"], ["y", "done"]]);
		assert.deepEqual(appended.map(([, data]) => [data.id, data.state]), [["x", "lost"]]);
		assert.deepEqual(sent.map(([message, options]) => [message.content, options]), [["[fork x lost] its session ended before it finished. Task: t", { deliverAs: "nextTurn" }]]);
	});

	test("a woken run's fork pins clear when it settles, unless its ask_user was cancelled", () => {
		const branch = () => appended.map(([customType, data]) => ({ type: "custom", customType, data }));
		const main = { ...ctx(), hasUI: false, sessionManager: { getBranch: branch } };
		const wakeWith = (name: string, messages: unknown[]) => {
			registry.start(run(name));
			background.finish(main, name, { state: "blocked", outcome: "blocked-on-user", ref: "rc" }, "OUTCOME blocked-on-user ref:rc\nASK: A or B?");
			assert.match(sent.at(-1)![0].content, new RegExp(`\nPinned: fork-${name}-${name}-1\\. They clear at the end of this turn unless you put them to the user with ask_user\\.$`));
			handlers.agent_end({ messages }, main);
			handlers.agent_settled({ aborted: false }, main);
		};
		wakeWith("x", [{ role: "assistant" }]);
		wakeWith("y", [{ role: "toolResult", toolName: "ask_user", isError: false, details: { cancelled: true } }]);
		assert.deepEqual(openAsks(branch()).map((ask) => ask.id), ["fork-y-y-1"]);
	});

	test("a result stays unread until a turn that delivered it settles, so an aborted or failed turn loses none", () => {
		const main = { ...ctx(false), hasUI: false, sessionManager: { getBranch: () => [] } };
		background.finish(main, "a", done(), "OUTCOME done ref:rc");
		const settle = (aborted: boolean, ...messages: unknown[]) => {
			assert.equal(background.digest(), registry.get("a")?.unread);
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
		const main = { ...ctx(false), hasUI: false, sessionManager: { getBranch: branch } };
		background.finish(main, "a", { state: "blocked", outcome: "blocked-on-user", ref: "rc" }, "OUTCOME blocked-on-user ref:rc\nASK: A or B?");
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
		assert.match(handlers.before_agent_start({}, ctx())?.message.content ?? "", /^\[fork late done\] ref rc$/);
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
