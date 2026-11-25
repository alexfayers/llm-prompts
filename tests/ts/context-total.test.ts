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

const costed = (cost: number, kind = "assistant", stopReason = "stop") => {
	const used = { input: 10, output: 5, cacheRead: 3, cacheWrite: 2, cost: { total: cost } };
	return kind === "usage"
		? line({ type: "usage", provider: "p", model: "m", usage: used })
		: line({ type: "message", message: { role: kind, stopReason, usage: used } });
};

const node = (label: string, state: string, tokens: number | null, contextWindow: number | null, percent: number | null) => ({
	sessionId: label,
	label,
	definition: "worker",
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

test("sampling reads live children and counts every child's usage in the tree", async () => {
	writeFileSync(join(dir, "c1.jsonl"), costed(2.0) + assistant(2000));
	writeFileSync(join(dir, "f1.jsonl"), costed(0.5));
	writeFileSync(session(), costed(1.0));
	await read();
	const child = (id: string, done: boolean) => ({ sessionId: id, sessionPath: join(dir, `${id}.jsonl`), label: id, definition: "worker", done, usage: done ? { tokens: 400, contextWindow: 1000, percent: 40 } : undefined });
	scan.children.set("c1", child("c1", false));
	scan.children.set("f1", child("f1", true));
	const { tree, session: lead, nodes } = await ext.module.sampleChildren(scan, new Map(), { windowOf: () => 10000 });
	assert.deepEqual(nodes.map((n: any) => [n.sessionId, n.state, n.tokens, n.contextWindow]), [["c1", "live", 2000, 10000], ["f1", "finished", 400, 1000]]);
	assert.deepEqual(lead, { tokens: 20, cost: 1.0 });
	assert.deepEqual(tree, { tokens: 20 + 2000 + 20, cost: 3.5 });
});

test("fork runs become children whose seed cost before the fork started is not counted", async () => {
	const startedAt = Date.parse("2026-01-02T00:00:00Z");
	const stamped = (cost: number, timestamp: string) => line({ ...JSON.parse(costed(cost)), timestamp });
	writeFileSync(join(dir, "f", "seed.jsonl"), stamped(5, "2026-01-01T00:00:00Z") + stamped(0.5, "2026-01-03T00:00:00Z") + assistant(3000));
	ext.module.addForkChildren(scan, new Map(), [
		{ id: "r1", name: "warm", role: "reader", state: "running", files: join(dir, "f"), startedAt },
		{ id: "r2", name: "gone", role: "writer", state: "done", files: join(dir, "none"), startedAt },
	]);
	const { tree, nodes } = await ext.module.sampleChildren(scan, new Map());
	assert.deepEqual(nodes.map((n: any) => [n.label, n.definition, n.state, n.tokens]), [["warm", "reader", "live", 3000], ["gone", "writer", "finished", null]]);
	assert.equal(tree.cost, 0.5);
});

test("a live cold worker's tokens come from its session directory", async () => {
	writeFileSync(join(dir, "c", "session", "s.jsonl"), assistant(7000));
	const run = { id: "r1", name: "cold", role: "reader", state: "running", model: "prov/mod", files: join(dir, "c"), startedAt: 0 };
	const tokens = async () => {
		ext.module.addForkChildren(scan, scans, [run]);
		return (await ext.module.sampleChildren(scan, scans)).nodes[0].tokens;
	};
	const scans = new Map();
	assert.equal(await tokens(), 7000);
	appendFileSync(join(dir, "c", "session", "s.jsonl"), assistant(9000));
	assert.equal(await tokens(), 9000);
});

test("the total counts only live sessions and marks unknown and partial", () => {
	const sample = {
		nodes: [node("a", "live", 2000, 10000, 20), node("b", "live", null, null, null), node("c", "finished", 400, 1000, 40)],
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
			"  b (worker)  unknown",
			"Finished (last known)",
			"  c (worker)  400 / 1k (40%)",
			"Tree cumulative: 9.0M tokens, $8.40",
		].join("\n"),
	);
	assert.equal(ext.module.formatFooter(sample), "agents 2 \u00b7 2k \u00b7 tree 9.0M $1.20/$8.40");
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
	const entry = (cost: number) => JSON.parse(costed(cost));
	const cost = (sessionId: string, entries: object[]) => ext.module.scanUsage(ext.module.syncLead(tracker, sessionId, entries)).cost;
	const first = entry(1);
	assert.equal(cost("lead", [first]), 1);
	assert.equal(cost("lead", [first, entry(2)]), 3);
	assert.equal(cost("other", [entry(4)]), 4);
	assert.equal(cost("other", []), 0);
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
