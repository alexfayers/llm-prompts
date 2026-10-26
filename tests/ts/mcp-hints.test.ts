import assert from "node:assert/strict";
import { join } from "node:path";
import { test } from "node:test";
import { loadExtension, useMemoryFs } from "./helpers.ts";

type Json = Record<string, any>;
type Step = [string, any];

const memory = useMemoryFs();
const agentDir = join(memory.root, "agent");
const text = (value: string) => ({ type: "text", text: value });
const tool = (server: string, name: string, parameters: Json = { type: "object", properties: { id: { type: "string" } } }, description = "Does the thing."): Json => ({
	name: `mcp__${server}__${name}`,
	description,
	parameters,
});
const wide = (description: string) => tool("docs", "read_sites", { type: "object", properties: { inputs: { type: "array", items: { type: "string" }, description: "x".repeat(9_000) } }, required: ["inputs"] }, description);
const SEARCH = tool("docs", "search_pages");
const NAME = SEARCH.name;
const COMPACT = "Required args only, full schema too large: read_sites(inputs*: string[])";
const SHAPE = " Script result .structuredContent: ";

const ask = (prompt: string): Step => ["before_agent_start", { messageType: "user", prompt }];
const use = ask(`use ${NAME}`);
const call: Step = ["tool_call", { toolName: NAME, toolCallId: "run/1", parentToolCallId: "run" }];
const finish: Step = ["tool_result", { toolName: "codemode", toolCallId: "run", content: [text("done")], isError: false }];
const observed = (inner?: unknown, fields: Json = {}): Step => [
	"tool_result",
	{ toolName: NAME, toolCallId: "run/1", parentToolCallId: "run", isError: false, content: [], structuredContent: { content: [text("{}")], structuredContent: inner }, ...fields },
];

async function play(steps: Step[], tools: Json[] = [SEARCH], active: string[] = []): Promise<Json[]> {
	const start = (allTools: Json[]) => loadExtension("mcp-hints", { agentDir, pi: { allTools, activeTools: active } });
	let ext = await start(tools);
	const out: Json[] = [];
	for (const [event, payload] of steps) {
		if (event === "load") ext = await start(payload);
		else if (event === "tools") ext.pi.allTools = payload;
		out.push(event === "load" || event === "tools" ? undefined : await ext.fire(event, payload));
	}
	return out;
}

const parts = (result?: Json): string[] => (result?.message ? result.message.content.split("\n\n") : (result?.content ?? []).slice(1).map((block: Json) => block.text));
const notes = (result?: Json) => parts(result).filter((part) => part.startsWith("Schema of"));
const names = (result?: Json) => parts(result).find((part) => part.startsWith("MCP tools"))?.split("\n").slice(1) ?? [];
const fullNote = (each: Json) => `Schema of ${each.name}: ${each.description} Parameters (JSON Schema): ${JSON.stringify(each.parameters)}`;

const LONG = tool("docs", "GetPageById");
const BASE = [SEARCH, tool("docs", "GetPage"), LONG, tool("docs", "searchpages"), tool("docs", "get_it")];

for (const [label, prompt, expected, tools = BASE, active = []] of [
	["full-name", `use ${NAME} now`, [SEARCH]],
	["snake-case, camel-case and order", "use GetPageById, then `search_pages`.", [LONG, SEARCH]],
	["short or plain names", "use GetPage now or searchpages", []],
	["inside-longer-word", "use my_search_pages or search_pagesx", []],
	["fenced-code", "fix:\n```\nsearch_pages(1)\n```", []],
	["already-declared", "use search_pages now", [], BASE, [NAME]],
	["bare-name-on-two-servers", "use search_pages now", [], [SEARCH, tool("wiki", "search_pages")]],
] as [string, string, Json[], Json[]?, string[]?][]) {
	test(`a distinctive name in a user message adds a note: ${label}`, async () => {
		const [result, custom] = await play([ask(prompt), ["before_agent_start", { messageType: "custom", message: {} }]], tools, active);
		assert.deepEqual([notes(result), result.message.display, custom], [expected.map(fullNote), false, undefined]);
	});
}

test("at most three tools are noted, and an oversized one gets a compact note that truncates a long description", async () => {
	const big = wide("Reads.");
	const small = [0, 1, 2, 3].map((n) => tool("docs", `small_tool_${n}`));
	const [result] = await play([ask([big, ...small].map((each) => each.name).join(" "))], [big, ...small]);
	assert.deepEqual(notes(result).map((note) => note.split(":")[0]), [big, ...small.slice(0, 2)].map((each) => `Schema of ${each.name}`));
	assert.equal(notes(result)[0], `Schema of ${big.name}: Reads. ${COMPACT}`);
	const long = wide("Reads. " + "filler ".repeat(2_000));
	const [note] = notes((await play([ask(long.name)], [long]))[0]);
	assert.ok(note.length <= 8_000 && note.startsWith(`Schema of ${long.name}: Reads. filler`) && note.endsWith(`... ${COMPACT}`));
	const shaped = await play([observed({ total: 2 }, { toolName: big.name }), ["load", [big]], ask(big.name)], [big]);
	assert.equal(notes(shaped.at(-1))[0], `Schema of ${big.name}: Reads. ${COMPACT}${SHAPE}{total: number}`);
});

for (const [label, sessions, expected] of [
	["a schema from an earlier session covers a prompt before servers connect", [[SEARCH], []], SEARCH],
	["the live schema wins over the cached one", [[tool("docs", "search_pages", { title: "old" })], [SEARCH]], SEARCH],
] as [string, Json[][], Json?][]) {
	test(label, async () => {
		const steps = sessions.flatMap((tools, i): Step[] => [["load", tools], i === sessions.length - 1 ? use : ask("hello")]);
		assert.deepEqual(notes((await play(steps, [])).at(-1)), expected ? [fullNote(expected)] : []);
	});
}

for (const [label, steps, expected] of [
	["a schema is shown once per session, to a user message or a script", [use, use, call, finish], [1, 0, 0, 0]],
	["a tool called in the session is not shown", [call, use], [0, 0]],
	["a new session shows schemas again", [use, ["session_start", {}], use], [1, 0, 1]],
	["a tool first called in a script is hinted once on the script result", [call, finish, call, finish, use], [0, 1, 0, 0, 0]],
] as [string, Step[], number[]][]) {
	test(label, async () => {
		assert.deepEqual((await play(steps)).map((result) => notes(result).length), expected);
	});
}

test("the names list is grouped per server and holds only new, undeclared MCP names", async () => {
	const all = [SEARCH, tool("docs", "GetPage"), tool("wiki", "find_page"), { name: "read", description: "Reads." }];
	const steps: Step[] = [["tools", all], ask("one"), ask("two"), ["tools", [...all, tool("docs", "put_page")]], ask("three"), ["session_start", {}], ask("four")];
	assert.deepEqual((await play(steps, [], ["read", "mcp__wiki__find_page"])).map(names), [[], ["docs: search_pages, GetPage"], [], [], ["docs: put_page"], [], ["docs: search_pages, GetPage, put_page"]]);
});

test("the names header says MCP tools are codemode only", async () => {
	const [result] = await play([ask("hi")], [tool("docs", "GetPage")]);
	assert.match(parts(result)[0], /^MCP tools, callable ONLY inside codemode as tools\.mcp__<server>__<tool>\(args\), never as direct tool calls:/);
});

const schema = (properties: string[], required: string[]) => ({ type: "object", properties: Object.fromEntries(properties.map((name) => [name, { type: "string" }])), required });

test("the names list marks required args, taking them from the cache only without a live schema", async () => {
	const tools = [tool("docs", "ReadSites", schema(["inputs", "mode"], ["inputs"])), tool("docs", "put_page", schema(["id", "body"], ["id", "body"])), tool("docs", "list_all", schema(["limit"], []))];
	const connecting = [{ name: tools[0].name, description: "Connecting." }, tool("docs", "get_page", schema(["id"], []))];
	const [first, second] = (await play([["load", tools], ask("hi"), ["load", connecting], ask("hi")], [])).filter(Boolean);
	assert.deepEqual(names(first), ["docs: ReadSites(inputs*: string), put_page(id*: string, body*: string), list_all"]);
	assert.deepEqual(names(second), ["docs: ReadSites(inputs*: string), get_page"]);
});

for (const [label, property, expected] of [
	["array-of-unknown", { type: "array", items: {} }, "arg*: any[]"],
	["capped-enum", { enum: ["a", "b", "c", "d", "e", "f", "g", "h"] }, "arg*: a|b|c|d|e|f|..."],
	["one-of-skips-null", { oneOf: [{ type: "null" }, { type: "array", items: { type: "string" } }] }, "arg*: string[]"],
] as [string, Json | undefined, string][]) {
	test(`the names list shows the type of a required arg: ${label}`, async () => {
		const parameters = { type: "object", properties: property ? { arg: property } : {}, required: ["arg"] };
		assert.deepEqual(names((await play([ask("hi")], [tool("docs", "do_it", parameters)]))[0]), [`docs: do_it(${expected})`]);
	});
}

const json = (value: string) => ({ content: [text(value)] });
const record = { content: [text('{"id": "a1"}')] };

for (const [label, server, parsed, fields] of [
	["object", { ...json('  \n{"id": "a1", "tags": ["x"]}\n'), isError: true }, { id: "a1", tags: ["x"] }],
	["array", json('[{"id": 1}, {"id": 2}]'), [{ id: 1 }, { id: 2 }]],
	["double-encoded", json(JSON.stringify(JSON.stringify({ id: "a1" }))), { id: "a1" }],
	...["plain words", '"plain"', "{oops"].map((value) => [`not-json ${JSON.stringify(value)}`, json(value)]),
	["json-strings-in-structured-content", { content: [], structuredContent: { result: '{"hits": [1]}', note: "plain", n: 3 } }, { result: { hits: [1] }, note: "plain", n: 3 }],
	["top-level-call", record, undefined, { parentToolCallId: undefined }],
] as [string, unknown, unknown?, Json?][]) {
	test(`JSON text in a script's MCP result is parsed: ${label}`, async () => {
		const event = { toolName: NAME, toolCallId: "run/1", parentToolCallId: "run", content: [text("trimmed")], structuredContent: server, ...fields };
		assert.deepEqual((await play([["tool_result", event]]))[0], parsed === undefined ? undefined : { structuredContent: { ...(server as Json), structuredContent: parsed } });
	});
}

const KEYS = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `k${n}`);
const WIDE = [0, 1, 2, 3, 4, 5, 6, 7].map((n) => `${"f".repeat(20)}_${n}`);

for (const [label, observations, shape] of [
	["key-cap", [observed(Object.fromEntries([...KEYS, "k9"].map((key) => [key, 1])))], `{${KEYS.map((key) => `${key}: number`).join(", ")}, ...}`],
	["depth-cap", [observed({ a: { b: { c: { d: 1 } } } })], "{a: {b: {c: {...}}}}"],
	["data-as-keys", [observed({ "first name": "x", n: 1 })], "{[key: string]: string}"],
	["empty-values", [observed({ none: null, list: [], empty: {} })], "{none: null, list: [], empty: {}}"],
	["shallower-to-fit", [observed({ list: [Object.fromEntries(WIDE.map((name) => [name, { x: 1 }]))] })], `{list: {${WIDE.map((name) => `${name}: {...}`).join(", ")}}[]}`],
	["error-body", [observed({ error: "not found" })], null],
	["status-error-body", [observed({ status: "error" })], null],
	["error", [observed({ total: 2 }, { isError: true })], null],
] as [string, Step[], string | null][]) {
	test(`an observed result shape is added to the note of a later session: ${label}`, async () => {
		const [note] = notes((await play([...observations, ["load", [SEARCH]], use])).at(-1));
		assert.equal(note.split(SHAPE)[1] ?? null, shape);
	});
}
