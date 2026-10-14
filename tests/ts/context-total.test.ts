import assert from "node:assert/strict";
import { join } from "node:path";
import { after, beforeEach, describe, test } from "node:test";
import { loadExtension, makeEvents, restoreMocks, useMemoryFs } from "./helpers.ts";

const BYTES_PER_TOKEN = 4;
const line = (entry: object) => JSON.stringify(entry) + "\n";
const usage = (total: number) => ({ input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: total });
const assistant = (total: number, stopReason = "stop") =>
	line({ type: "message", message: { role: "assistant", provider: "prov", model: "mod", stopReason, usage: usage(total) } });
const toolResult = (text: string) => line({ type: "message", message: { role: "toolResult", text } });

const spawn = (child: string, request: string, { owner = "owner", toolName = "delegate_agent", isError = false, sessions = "/sessions" } = {}) =>
	line({
		type: "message",
		message: {
			role: "toolResult",
			toolName,
			isError,
			details: {
				ok: true,
				owner_session_id: owner,
				session_id: child,
				session_path: `${sessions}/${child}.jsonl`,
				agent: `label-${child}`,
				definition: "worker",
				request_id: request,
			},
		},
	});

const result = (child: string, request: string, tokens: number, owner = "owner") =>
	line({
		type: "custom_message",
		customType: "pi-herdsman-agent-result",
		details: { ownerSessionId: owner, piSessionId: child, requestId: request, contextUsage: { tokens, contextWindow: 1000, percent: tokens / 10 } },
	});

const costed = (cost: number, kind = "assistant", stopReason = "stop") => {
	const used = { input: 10, output: 5, cacheRead: 3, cacheWrite: 2, cost: { total: cost } };
	return kind === "usage"
		? line({ type: "usage", provider: "p", model: "m", usage: used })
		: line({ type: "message", message: { role: kind, stopReason, usage: used } });
};

const node = (label: string, depth: number, state: string, tokens: number | null, contextWindow: number | null, percent: number | null) => ({
	sessionId: label,
	label,
	definition: "worker",
	depth,
	state,
	tokens,
	contextWindow,
	percent,
});

const memory = useMemoryFs();
const dir = memory.root;
const { write: writeFileSync, append: appendFileSync } = memory;

let ext: Awaited<ReturnType<typeof loadExtension>>;
let scan: any;
const session = () => join(dir, "session.jsonl");
const read = (file = session(), target = scan) => ext.module.readNew(target, file);

beforeEach(async () => {
	ext = await loadExtension("context-total", { agentDir: join(dir, "agent") });
	scan = ext.module.createScan("owner");
});
after(restoreMocks);

test("context estimate is the last usage plus trailing bytes, ignoring failed replies until compaction", async () => {
	const trailing = toolResult("x".repeat(100));
	writeFileSync(session(), assistant(1000) + assistant(9000, "aborted") + assistant(9000, "error") + trailing);
	await read();
	const trailingBytes = 2 * assistant(9000, "error").trim().length + trailing.trim().length;
	assert.equal(ext.module.scanTokens(scan), 1000 + Math.ceil(trailingBytes / BYTES_PER_TOKEN));
	appendFileSync(session(), line({ type: "compaction", summary: "s" }));
	await read();
	assert.equal(ext.module.scanTokens(scan), null);
	appendFileSync(session(), assistant(500));
	await read();
	assert.equal(ext.module.scanTokens(scan), 500);
});

test("usage totals sum every usage-bearing entry, including failed replies and tools", async () => {
	writeFileSync(session(), costed(1.5) + costed(0.25, "assistant", "aborted") + costed(0.125, "toolResult") + costed(0.0625, "usage") + toolResult("no usage here"));
	await read();
	assert.deepEqual(ext.module.scanUsage(scan), { tokens: 20, cost: 1.9375 });
});

test("a half-written line waits and a shrunken file restarts", async () => {
	const full = assistant(5000);
	const half = full.length / 2;
	const tokens = async () => (await read(), ext.module.scanTokens(scan));
	writeFileSync(session(), assistant(1000) + full.slice(0, half));
	assert.equal(await tokens(), 1000);
	appendFileSync(session(), full.slice(half));
	assert.equal(await tokens(), 5000);
	writeFileSync(session(), assistant(200));
	assert.equal(await tokens(), 200);
});

test("a spawn runs, its result finishes it, and a continue runs it again", async () => {
	const stages = [
		spawn("c1", "r1") + spawn("c2", "r2", { toolName: "agent_delegate" }) + spawn("c3", "r3", { owner: "other" }) + spawn("c4", "r4", { isError: true }),
		result("c1", "r1", 400) + result("c2", "stale", 50),
		spawn("c1", "r5", { toolName: "continue_agent" }),
	];
	const listed = [];
	for (const stage of stages) {
		appendFileSync(session(), stage);
		await read();
		listed.push(ext.module.listChildren(scan));
	}
	assert.deepEqual(
		listed.map((children) => Object.fromEntries(children.map((c: any) => [c.sessionId, c.done]))),
		[{ c1: false, c2: false }, { c1: true, c2: false }, { c1: false, c2: false }],
	);
	assert.deepEqual(listed[1][0], {
		sessionId: "c1",
		sessionPath: "/sessions/c1.jsonl",
		label: "label-c1",
		definition: "worker",
		requestId: "r1",
		done: true,
		usage: { tokens: 400, contextWindow: 1000, percent: 40 },
	});
});

describe("sampling the agent tree", () => {
	const lead = () => join(dir, "lead.jsonl");
	const spawned = (child: string, request: string, owner = "lead") => spawn(child, request, { owner, sessions: dir });
	const sample = async (options?: object) => {
		scan = ext.module.createScan("lead");
		await read(lead());
		return ext.module.sampleChildren(scan, new Map(), options);
	};

	test("nested agents are walked, tolerating cycles and unreadable files", async () => {
		writeFileSync(lead(), spawned("c1", "r1") + spawned("f1", "r2") + result("f1", "r2", 400, "lead") + spawned("n1", "r3"));
		writeFileSync(join(dir, "c1.jsonl"), spawned("g1", "r4", "c1") + assistant(2000));
		writeFileSync(join(dir, "g1.jsonl"), spawned("c1", "r5", "g1") + assistant(300));
		const { nodes, partial } = await sample({ windowOf: () => 10000 });
		assert.deepEqual(
			nodes.map((n: any) => [n.sessionId, n.depth, n.state, n.tokens, n.contextWindow]),
			[["c1", 0, "live", 2000, 10000], ["g1", 1, "live", 300, 10000], ["f1", 0, "finished", 400, 1000], ["n1", 0, "live", null, undefined]],
		);
		assert.equal(partial, false);
	});

	test("a running agent without a mailbox is lost unless mailboxes are unknown", async () => {
		writeFileSync(lead(), spawned("c1", "r1") + spawned("c2", "r2"));
		writeFileSync(join(dir, "c1.jsonl"), assistant(700));
		writeFileSync(join(dir, "c2.jsonl"), assistant(800));
		const mailboxes = join(dir, "agent", "pi-herdsman", "runtime", "mailboxes-v5");
		for (const [name, state] of [["aaa", '{"piSessionId":"c2"}'], ["bbb", "not json"]]) writeFileSync(join(mailboxes, name, "state.json"), state);
		writeFileSync(join(mailboxes, "ccc", "other"), "");
		const states = async (mailboxIds?: Set<string>) =>
			(await sample({ mailboxIds })).nodes.map((n: any) => [n.sessionId, n.state, n.tokens]);
		const ids = await ext.module.readMailboxIds(join(dir, "agent"));
		assert.deepEqual([...ids], ["c2"]);
		assert.equal(await ext.module.readMailboxIds(join(dir, "none")), undefined);
		assert.deepEqual(await states(ids), [["c1", "lost", 700], ["c2", "live", 800]]);
		assert.deepEqual(await states(), [["c1", "live", 700], ["c2", "live", 800]]);
	});

	test("tree usage counts the lead, live, finished and nested agents", async () => {
		writeFileSync(lead(), costed(1.0) + spawned("c1", "r1") + spawned("f1", "r2") + result("f1", "r2", 400, "lead"));
		writeFileSync(join(dir, "c1.jsonl"), costed(2.0) + spawned("g1", "r3", "c1"));
		writeFileSync(join(dir, "g1.jsonl"), assistant(50) + costed(4.0));
		writeFileSync(join(dir, "f1.jsonl"), costed(0.5) + spawned("h1", "r4", "f1"));
		writeFileSync(join(dir, "h1.jsonl"), costed(0.25));
		const { tree, session, nodes } = await sample();
		assert.deepEqual(tree, { tokens: 4 * 20 + 50, cost: 7.75 });
		assert.deepEqual(session, { tokens: 20, cost: 1.0 });
		assert.deepEqual(nodes.map((n: any) => n.sessionId), ["c1", "g1", "f1"]);
	});
});

test("the total counts only live sessions and marks unknown and partial", () => {
	const sample = {
		nodes: [node("a", 0, "live", 2000, 10000, 20), node("b", 1, "live", null, null, null), node("c", 0, "finished", 400, 1000, 40), node("d", 0, "lost", 700, null, null)],
		partial: false,
		session: { tokens: 5000, cost: 1.2 },
		tree: { tokens: 9_000_000, cost: 8.4 },
	};
	const bare = { nodes: [], partial: true, session: { tokens: 0, cost: 0 }, tree: { tokens: 0, cost: 0 } };
	assert.equal(
		ext.module.formatReport({ tokens: 1000, contextWindow: 10000, percent: 10 }, sample),
		[
			"Live context: 3k+ across 3 sessions",
			"Running",
			"  lead  1k / 10k (10%)",
			"  a (worker)  2k / 10k (20%)",
			"    b (worker)  unknown",
			"Finished (last known)",
			"  c (worker)  400 / 1k (40%)",
			"  d (worker)  700 [lost]",
			"Tree cumulative: 9.0M tokens, $8.40",
			"Cumulative tokens and cost: /herdsman stats",
		].join("\n"),
	);
	assert.equal(ext.module.formatFooter(sample), "agents 2k+ \u00b7 tree 9.0M $1.20/$8.40");
	assert.equal(ext.module.formatFooter(bare), "agents 0 \u00b7 tree 0 $0.00/$0.00 partial");
});

describe("publishing the footer", () => {
	const keys = ["llm-prompts/context-total:ctx", "llm-prompts/context-total:cost"];
	const sample = { nodes: [], partial: false, session: { tokens: 0, cost: 1.2 }, tree: { tokens: 109_600_000, cost: 8.4 } };
	const publish = (active: string[]) => {
		const statuses: unknown[][] = [];
		const events = makeEvents();
		events.on("zentui:variable-capability", (payload) => {
			if (active.includes(payload.key)) payload.active = true;
		});
		ext.module.publishFooter({ events }, { setStatus: (...args: unknown[]) => statuses.push(args) }, sample);
		return { published: events.emitted.filter(([event]) => event === "zentui:variable").map(([, { key, text }]: any) => [key, text]), statuses };
	};

	test("active variables are published and the status line cleared", () => {
		assert.deepEqual(publish(keys), {
			published: [[keys[0], "agents 0 \u00b7 tree 109.6M"], [keys[1], "$1.20/$8.40"]],
			statuses: [["context-total", undefined]],
		});
	});

	test("inactive variables fall back to one status line", () => {
		assert.deepEqual(publish([]), { published: [], statuses: [["context-total", "agents 0 \u00b7 tree 109.6M $1.20/$8.40"]] });
	});
});

test("the lead tracker reads only new entries and restarts on a new session or a shorter list", () => {
	const tracker = ext.module.createLeadTracker();
	const entry = (owner: string, child: string) => JSON.parse(spawn(child, `r-${child}`, { owner }));
	const children = (sessionId: string, entries: object[]) =>
		ext.module.listChildren(ext.module.syncLead(tracker, sessionId, entries)).map((c: any) => c.sessionId);
	const first = entry("lead", "c1");
	assert.deepEqual(children("lead", [first]), ["c1"]);
	assert.deepEqual(children("lead", [first, entry("lead", "c2")]), ["c1", "c2"]);
	assert.deepEqual(children("other", [entry("other", "c3")]), ["c3"]);
	assert.deepEqual(children("other", []), []);
});

test("config clamps the interval and rewrites the footer keeping other keys", () => {
	const file = join(dir, "context-total.json");
	writeFileSync(file, '{"footer":false,"intervalSeconds":1,"x":1}');
	assert.deepEqual(ext.module.readConfig(file), { footer: false, intervalSeconds: 2 });
	ext.module.writeFooterSetting(file, true);
	assert.deepEqual(ext.module.readConfig(file), { footer: true, intervalSeconds: 2 });
	assert.deepEqual(JSON.parse(memory.read(file)), { footer: true, intervalSeconds: 1, x: 1 });
});

describe("headless modes", () => {
	const SETTLE_MS = 300;

	async function runSession(mode: string) {
		memory.write(join(dir, "agent/context-total.json"), '{"footer":true}');
		const ctx = ext.makeCtx({
			mode,
			sessionManager: { getSessionId: () => "lead", getEntries: () => [] } as any,
			modelRegistry: { find: () => undefined } as any,
			getContextUsage: () => undefined,
		});
		await ext.fire("session_start", {}, ctx);
		await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
		await ext.runCommand("context-total", "", ctx);
		await ext.fire("session_shutdown", {}, ctx);
		return { emitted: ext.pi.emitted, status: ctx.statuses, notices: ctx.notices };
	}

	test("footer, report and cleanup do nothing without the terminal UI", async () => {
		for (const mode of ["rpc", "json", "print"]) {
			const { emitted, status, notices } = await runSession(mode);
			assert.deepEqual(emitted.filter(([event]) => event === "zentui:variable"), []);
			assert.deepEqual(status, []);
			assert.deepEqual(notices, []);
		}
	});

});
