import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, mock, test } from "node:test";
import { useEnv } from "./helpers.ts";

const { register } = await import("../../src/llm_prompts/prompts/pi/extensions/popup-defer.ts");

const DEBOUNCE_MS = 200;
const TICK_MS = 30;
const DIALOGS: Record<string, unknown[]> = {
	select: ["Pick", ["a", "b"]],
	confirm: ["Sure?", "message"],
	input: ["Name", "placeholder"],
	editor: ["Edit", "prefill"],
	custom: [() => {}],
};

let started: number;
let shown: { method: string; args: any[]; at: number }[];
let notices: string[];
let inputs: Set<(data: string) => { consume?: boolean } | undefined>;
let results: Record<string, { value: unknown; at: number }>;

const elapsed = () => Date.now() - started;
const flush = () => new Promise((done) => setImmediate(done));
async function elapse(ms: number) {
	for (let spent = 0; spent < ms; spent += 10) {
		mock.timers.tick(10);
		await flush();
	}
}

let ui: Record<string, any>;
function makeUi() {
	const fake: Record<string, any> = {
		notify: (message: string) => notices.push(message),
		onTerminalInput: (handler: any) => (inputs.add(handler), () => inputs.delete(handler)),
	};
	for (const method of Object.keys(DIALOGS)) {
		fake[method] = (...args: unknown[]) => (shown.push({ method, args, at: elapsed() }), Promise.resolve(`${method}-result`));
	}
	return fake;
}

function makePi(limits?: { maxHoldMs?: number; swallowMs?: number }) {
	const handlers: Record<string, Function[]> = {};
	const commands: Record<string, any> = {};
	register({ on: (event: string, handler: Function) => (handlers[event] ??= []).push(handler), registerCommand: (name: string, command: unknown) => (commands[name] = command) } as any, limits);
	return { handlers, commands };
}
const start = async (pi: ReturnType<typeof makePi>, mode = "tui") => {
	for (const handler of pi.handlers.session_start) await handler({}, { mode, ui });
};
const begin = async (limits?: { maxHoldMs?: number; swallowMs?: number }) => {
	const pi = makePi(limits);
	await start(pi);
	return pi;
};
const key = (data: string) => [...inputs].reduce((consumed, handler) => Boolean(handler(data)?.consume) || consumed, false);
const call = (method: string, args: unknown[] = DIALOGS[method], name = method) => {
	ui[method](...args).then((value: unknown) => (results[name] = { value: value ?? null, at: elapsed() }));
};
const command = (pi: ReturnType<typeof makePi>, args: string) => pi.commands["popup-defer"].handler(args, { ui });
const methods = () => shown.map((call) => call.method);

useEnv({ PI_POPUP_DEFER_MS: String(DEBOUNCE_MS) });
beforeEach(() => {
	mock.timers.enable({ apis: ["setTimeout", "Date"] });
	started = Date.now();
	shown = [];
	notices = [];
	inputs = new Set();
	results = {};
	ui = makeUi();
});
afterEach(() => {
	mock.timers.reset();
});

test("every dialog method is held while typing then shown after a pause", async () => {
	const names = Object.keys(DIALOGS);
	await begin();
	key("a");
	for (const method of names) call(method);
	await elapse(DEBOUNCE_MS / 2);
	assert.equal(shown.length, 0);
	await elapse(DEBOUNCE_MS);
	assert.deepEqual(methods(), names);
	assert.ok(shown.every((entry) => entry.at >= DEBOUNCE_MS));
	for (const method of names) assert.equal(results[method].value, `${method}-result`);
});

for (const [label, mode, typed] of [["tui idle", "tui", false], ["not tui", "rpc", true]] as const) {
	test(`a dialog is shown at once in ${label}`, async () => {
		await start(makePi(), mode);
		if (typed) key("a");
		call("select");
		await elapse(TICK_MS);
		assert.deepEqual(methods(), ["select"]);
		assert.ok(shown[0].at < DEBOUNCE_MS);
		assert.equal(inputs.size, mode === "tui" ? 1 : 0);
	});
}

for (const [label, data] of [
	["mouse press", "\x1b[<0;10;5M"],
	["focus in", "\x1b[I"],
	["colour", "\x1b[?997;1n"],
	["release", "\x1b[97;1:3u"],
]) {
	test(`${label} report does not hold a dialog`, async () => {
		await begin();
		assert.equal(key(data), false);
		call("select");
		await elapse(TICK_MS);
		assert.equal(shown.length, 1);
	});
}

for (const [label, enter] of [["cr", "\r"], ["kitty", "\x1b[13u"]]) {
	test(`${label} enter ends the typing burst`, async () => {
		await begin();
		key("a");
		call("select");
		await elapse(TICK_MS);
		assert.equal(shown.length, 0);
		key(enter);
		await elapse(TICK_MS);
		assert.equal(shown.length, 1);
	});
}

test("held dialogs are shown in the order they were requested", async () => {
	await begin();
	key("a");
	for (const method of ["select", "confirm", "input"]) call(method);
	await elapse(DEBOUNCE_MS * 2);
	assert.deepEqual(methods(), ["select", "confirm", "input"]);
});

test("a dialog is shown after the max hold even if typing continues", async () => {
	const maxHold = DEBOUNCE_MS * 3;
	await begin({ maxHoldMs: maxHold });
	key("a");
	call("select");
	for (let spent = 0; spent < maxHold + 5 * TICK_MS; spent += TICK_MS) {
		await elapse(TICK_MS);
		key("a");
	}
	assert.equal(shown.length, 1);
	assert.ok(shown[0].at >= maxHold && shown[0].at < maxHold + DEBOUNCE_MS);
});

test("aborting a held dialog resolves it without showing it", async () => {
	const abort = new AbortController();
	await begin();
	key("a");
	call("select", [...DIALOGS.select, { signal: abort.signal }]);
	await elapse(TICK_MS);
	abort.abort();
	await elapse(DEBOUNCE_MS * 2);
	assert.equal(shown.length, 0);
	assert.equal(results.select.value, null);
	assert.ok(results.select.at < DEBOUNCE_MS);
});

test("hold time is subtracted from the dialog timeout", async () => {
	const timeout = DEBOUNCE_MS * 5;
	await begin();
	key("a");
	call("confirm", [...DIALOGS.confirm, { timeout }]);
	await elapse(DEBOUNCE_MS * 2);
	const shownTimeout = shown[0].args[2].timeout;
	assert.ok(shownTimeout <= timeout - DEBOUNCE_MS / 2 && shownTimeout > 0);
});

test("a dialog whose timeout ends during the hold is never shown", async () => {
	await begin();
	key("a");
	call("confirm", [...DIALOGS.confirm, { timeout: DEBOUNCE_MS / 2 }]);
	await elapse(DEBOUNCE_MS * 2);
	assert.equal(shown.length, 0);
	assert.equal(results.confirm.value, null);
	assert.ok(results.confirm.at < DEBOUNCE_MS);
});

test("a dialog with an already aborted signal is not shown", async () => {
	const abort = new AbortController();
	await begin();
	key("a");
	abort.abort();
	call("select", [...DIALOGS.select, { signal: abort.signal }]);
	await elapse(TICK_MS);
	assert.equal(shown.length, 0);
	assert.equal(results.select.value, null);
});

test("a zero timeout means no timeout and is left alone", async () => {
	await begin();
	key("a");
	call("confirm", [...DIALOGS.confirm, { timeout: 0 }]);
	await elapse(DEBOUNCE_MS * 2);
	assert.deepEqual(shown[0].args[2], { timeout: 0 });
});

test("printable keys are swallowed briefly after a dialog mounts", async () => {
	await begin({ swallowMs: DEBOUNCE_MS });
	key("a");
	call("select");
	await elapse(DEBOUNCE_MS + TICK_MS);
	const swallowed = [key("b"), key("\x1b[A"), key("\r")];
	await elapse(DEBOUNCE_MS);
	assert.deepEqual([...swallowed, key("c")], [true, false, false, false]);
});

test("zero in the environment turns deferral off", async () => {
	process.env.PI_POPUP_DEFER_MS = "0";
	await begin();
	key("a");
	call("select");
	await elapse(TICK_MS);
	assert.equal(shown.length, 1);
	assert.equal(key("b"), false);
});

describe("/popup-defer", () => {
	for (const [env, args, held] of [
		[DEBOUNCE_MS, "off", false],
		[DEBOUNCE_MS, "on", true],
		[0, "on", true],
		[0, String(DEBOUNCE_MS), true],
	] as const) {
		test(`${args} with PI_POPUP_DEFER_MS=${env} ${held ? "holds" : "shows"} a dialog`, async () => {
			process.env.PI_POPUP_DEFER_MS = String(env);
			const pi = await begin();
			await command(pi, args);
			key("a");
			call("select");
			await elapse(TICK_MS);
			assert.equal(shown.length === 0, held);
		});
	}

	test("turning deferral off releases dialogs already held", async () => {
		const pi = await begin();
		key("a");
		call("select");
		await elapse(TICK_MS);
		await command(pi, "off");
		await elapse(TICK_MS);
		assert.equal(shown.length, 1);
	});

	test("reports state and rejects bad input", async () => {
		const pi = await begin();
		for (const args of ["", "soon", "off"]) await command(pi, args);
		assert.deepEqual(notices, [`popup-defer on, ${DEBOUNCE_MS} ms`, "Usage: /popup-defer [on|off|<ms>]", "popup-defer off"]);
	});
});

test("starting a session again does not stack wrappers or subscriptions", async () => {
	const pi = await begin();
	await start(pi);
	const reloaded = makePi();
	await start(reloaded);
	assert.equal(inputs.size, 1);
	call("select");
	await elapse(DEBOUNCE_MS * 2);
	assert.equal(shown.length, 1);
	await command(reloaded, "off");
	key("b");
	call("select");
	await elapse(TICK_MS);
	assert.equal(shown.length, 2);
});
