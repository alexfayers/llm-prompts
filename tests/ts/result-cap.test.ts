import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

useEnv({ RESULT_CAP_CHARS: "30" });

const text = (value: string) => [{ type: "text", text: value }];
const result = (overrides: Record<string, unknown> = {}) => ({ toolCallId: "t1", toolName: "bash", input: {}, content: text("a".repeat(40) + "b".repeat(20)), isError: false, ...overrides });

describe("tool_result", () => {
	test("caps an over-cap result to head, marker and tail and stores the full text", async () => {
		const ext = await loadExtension("result-cap");
		const out = await ext.fire("tool_result", result());
		assert.equal(out.content[0].text, `${"a".repeat(20)}\n[capped: 60 chars, ref rc-t1; result_fetch({ref, offset?, limit?, pattern?})]\n${"b".repeat(10)}`);
		assert.deepEqual(ext.pi.appended, [["result-cap", { ref: "rc-t1", text: "a".repeat(40) + "b".repeat(20) }]]);
	});
});

describe("list shape", () => {
	const rows = (count: number) => Array.from({ length: count }, (_, i) => ({ id: i, name: `item-${i}` }));
	const shaped = async (content: string, cap = "2000") => {
		process.env.RESULT_CAP_CHARS = cap;
		const ext = await loadExtension("result-cap");
		return (await ext.fire("tool_result", result({ content: text(content) }))).content[0].text as string;
	};

	test("shows a count, fields, ref and the first 20 rows of a JSON list, also inside a codemode wrapper", async () => {
		const list = rows(100);
		const header = "[list: 100 rows, json, fields id,name; ref rc-t1; result_query({ref, where?, fields?, sort?, count_by?, limit?, offset?}) or result_fetch for the raw text]";
		const expected = [header, ...list.slice(0, 20).map((row) => JSON.stringify(row))].join("\n");
		assert.equal(await shaped(JSON.stringify(list)), expected);
		assert.equal(await shaped(`Script completed\nWall time 0.1 seconds\nOutput:\n\n${JSON.stringify(list)}`), expected);
		assert.match(await shaped(JSON.stringify({ total: 100, items: list })), /^\[list: 100 rows, json at items, fields id,name;/);
	});

	test("shows line lists by format, with file counts for grep, and keeps other text as head and tail", async () => {
		const lines = (count: number, line: (i: number) => string) => Array.from({ length: count }, (_, i) => line(i)).join("\n");
		const grep = await shaped(lines(90, (i) => `${i % 3 ? "src/a.ts" : "src/b.ts"}:${i}:const value = ${i};`));
		assert.match(grep, /^\[list: 90 rows, grep, fields file,line,text; ref rc-t1;/);
		assert.match(grep, /\nfiles: src\/a\.ts 60, src\/b\.ts 30$/);
		assert.match(await shaped(lines(200, (i) => `src/dir/file-${i}.ts`)), /^\[list: 200 rows, paths, fields path;/);
		assert.match(await shaped(lines(200, (i) => `${(10000000 + i).toString(16)}0 fix thing ${i}`)), /^\[list: 200 rows, gitlog, fields sha,subject;/);
		assert.match(await shaped(lines(19, (i) => `src/dir/file-with-a-long-name-${i}.ts`), "300"), /^src\/dir[^[]*\n\[capped:/);
		assert.match(await shaped(lines(100, (i) => `plain sentence number ${i}`)), /\n\[capped:/);
		assert.match(await shaped(lines(100, (i) => `2026-11-15T04:50:${String(i % 60).padStart(2, "0")}.123Z INFO step ${i} done`)), /\n\[capped:/);
		assert.match(await shaped(lines(100, (i) => `04:50:${String(i % 60).padStart(2, "0")}: step ${i} done`)), /\n\[capped:/);
	});
});

describe("result_fetch", () => {
	const lines = Array.from({ length: 10 }, (_, i) => `line ${i} ${i % 3 ? "plain" : "match"}`).join("\n");

	async function capped() {
		const first = await loadExtension("result-cap");
		await first.fire("tool_result", result({ content: text(lines) }));
		const fresh = await loadExtension("result-cap");
		const branch = first.pi.appended.map(([customType, data]) => ({ type: "custom", customType, data }));
		const ctx = fresh.makeCtx({ sessionManager: { getBranch: () => branch } });
		return (params: object) => fresh.callTool("result_fetch", params, ctx);
	}

	test("returns the stored text from a fresh load, by offset and limit or by matching lines", async () => {
		const fetch = await capped();
		assert.equal((await fetch({ ref: "rc-t1", limit: 10000 })).content[0].text, lines);
		assert.equal((await fetch({ ref: "rc-t1", offset: 7, limit: 6 })).content[0].text, lines.slice(7, 13) + "\n[more: offset 13]");
		assert.equal((await fetch({ ref: "rc-t1", pattern: "match", limit: 10000 })).content[0].text, "0: line 0 match\n3: line 3 match\n6: line 6 match\n9: line 9 match");
	});

	test("a ref stored twice returns the later text", async () => {
		const { makeCtx, callTool } = await loadExtension("result-cap");
		const branch = ["old", "new"].map((stored) => ({ type: "custom", customType: "result-cap", data: { ref: "rc-fork-x", text: stored } }));
		const fetched = await callTool("result_fetch", { ref: "rc-fork-x" }, makeCtx({ sessionManager: { getBranch: () => branch } }));
		assert.equal(fetched.content[0].text, "new");
	});
});

describe("result_query", () => {
	const rows = Array.from({ length: 100 }, (_, i) => ({ id: i, name: `item-${i}`, kind: i % 3 ? "a" : "b" }));

	async function query() {
		process.env.RESULT_CAP_CHARS = "2000";
		const first = await loadExtension("result-cap");
		await first.fire("tool_result", result({ content: text(JSON.stringify(rows)) }));
		await first.fire("tool_result", result({ toolCallId: "t2", content: text("x".repeat(3000)) }));
		const fresh = await loadExtension("result-cap");
		const branch = first.pi.appended.map(([customType, data]) => ({ type: "custom", customType, data }));
		const ctx = fresh.makeCtx({ sessionManager: { getBranch: () => branch } });
		return async (params: object) => (await fresh.callTool("result_query", params, ctx)) as { content: { text: string }[]; isError: boolean };
	}

	test("answers the same as filtering, sorting and paging the rows by hand", async () => {
		const ask = await query();
		const matched = rows.filter((row) => row.kind === "b" && /7/.test(row.name)).sort((a, b) => b.id - a.id);
		const out = (await ask({ ref: "rc-t1", where: { kind: "^b$", name: "7" }, sort: "-id", fields: ["id", "name"], limit: 3, offset: 1 })).content[0].text;
		const shown = matched.slice(1, 4).map(({ id, name }) => JSON.stringify({ id, name }));
		assert.equal(out, [`rows 3 of ${matched.length} matched, 100 total (offset 1); omitted ${matched.length - 4}`, ...shown].join("\n"));
		assert.equal((await ask({ ref: "rc-t1", where: { id: "^5$" } })).content[0].text, `rows 1 of 1 matched, 100 total (offset 0); omitted 0\n${JSON.stringify(rows[5])}`);
	});
});
