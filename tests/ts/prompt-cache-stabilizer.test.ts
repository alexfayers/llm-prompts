import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension } from "./helpers.ts";

type Sections = Record<string, string | null>;

const system = (timestamp: number, sections: Sections, content = "") => ({ role: "system", content, sections, timestamp });
const user = (timestamp: number) => ({ role: "user", content: "hi", timestamp });
const entries = (...messages: object[]) => messages.map((message) => ({ type: "message", message }));
const folded = (messages: any[]) => {
	const sections = new Map<string, string>();
	for (const message of messages.filter((m) => m.role === "system"))
		for (const [name, text] of Object.entries<string | null>(message.sections ?? {})) text === null ? sections.delete(name) : sections.set(name, text);
	return Object.fromEntries(sections);
};

const LEAD = system(1, { skills: "S", custom: "C" }, "base");
const FOLDING_MODEL = { api: "anthropic-messages", compat: {} };
const { module } = await loadExtension("prompt-cache-stabilizer");

describe("stabilizeSystemMessages", () => {
	const stabilize = (messages: object[], triggered: boolean, since = 0) => module.stabilizeSystemMessages(messages, { triggered, since });

	test("a removal with a later re-add is dropped even when prompted", () => {
		const out = stabilize([LEAD, system(3, { custom: null }), user(4), system(5, { custom: "C" })], false);
		assert.deepEqual(out.slice(1).filter((m: any) => m.role === "system").map((m: any) => m.sections), [{ custom: "C" }]);
	});

	for (const [label, messages, triggered, since] of [
		["built-in", [LEAD, user(2), system(3, { skills: null })], true, 2],
		["before-prompt", [LEAD, system(1, { custom: null }), user(2)], true, 2],
		["update", [LEAD, user(2), system(3, { custom: "C2" })], true, 2],
	] as const) {
		test(`a legitimate removal is left alone: ${label}`, () => {
			assert.equal(stabilize([...messages], triggered, since), undefined);
		});
	}

	test("the leading system message is never changed", () => {
		assert.equal(stabilize([system(1, { custom: null }), system(2, { custom: "C" })], true), undefined);
	});
});

async function handle(model: object, messages: object[], prompted: boolean, branch: object[] = []) {
	const ext = await loadExtension("prompt-cache-stabilizer");
	const ctx = (entriesOf: object[]) => ext.makeCtx({ model, sessionManager: { getBranch: () => entries(...entriesOf) } as any });
	await ext.fire("session_start", {}, ctx([user(2), system(3, {})]));
	if (prompted) await ext.fire("before_agent_start");
	await ext.fire("agent_start");
	return ext.fire("context_with_system", { messages }, ctx(branch));
}

describe("handler", () => {
	for (const [label, model, prompted, dropped] of [
		["folds", FOLDING_MODEL, false, true],
		["bedrock", { api: "bedrock-converse-stream", compat: { supportsMidConvoSystemMessages: true } }, false, true],
		["mid-convo", { api: "anthropic-messages", compat: { supportsMidConvoSystemMessages: true } }, false, false],
		["prompted-run", FOLDING_MODEL, true, false],
	] as const) {
		test(`removals are dropped only in triggered runs on folding models: ${label}`, async () => {
			const out = await handle(model, [LEAD, user(2), system(5, { custom: null })], prompted);
			assert.equal(out !== undefined, dropped);
			if (out) assert.deepEqual(folded(out.messages), folded([LEAD]));
		});
	}
});

describe("merged head", () => {
	const head = (sections: Sections) => system(1, sections, "base");
	const branch = [LEAD, user(2), system(3, { custom: null })];

	test("a dropped removal is restored in the merged head", async () => {
		const out = await handle(FOLDING_MODEL, [head({ skills: "S" }), user(2)], false, branch);
		assert.deepEqual(out.messages, [head({ skills: "S", custom: "C" }), user(2)]);
	});

	for (const [label, prompted, sections] of [
		["head-not-from-branch", false, { skills: "S", other: "O" }],
	] as const) {
		test(`the merged head is left alone when legitimate: ${label}`, async () => {
			assert.equal(await handle(FOLDING_MODEL, [head(sections), user(2)], prompted, branch), undefined);
		});
	}
});

const MID_CONVO_MODEL = { api: "anthropic-messages", compat: { supportsMidConvoSystemMessages: true } };
const cwdSection = (path: string) => `<cwd>\n${path}\n</cwd>`;
const withCwd = (path: string) => [system(1, { skills: "S", cwd: cwdSection(path) }, "base"), user(2)];
const systemText = (messages: any[]) => JSON.stringify([messages.filter((m) => m.role === "system").map((m) => m.content), folded(messages)]);

describe("cwd move", () => {
	test("system text is identical across working directories", async () => {
		for (const model of [FOLDING_MODEL, MID_CONVO_MODEL]) {
			const outs = [];
			for (const path of ["/work/one", "/work/two"]) {
				const out = await handle(model, withCwd(path), true);
				assert.ok(out);
				outs.push(out.messages);
			}
			assert.equal(systemText(outs[0]), systemText(outs[1]));
			assert.ok(!systemText(outs[0]).includes("cwd"));
		}
	});
});
