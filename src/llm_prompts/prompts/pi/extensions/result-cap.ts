// Caps long tool results to a head and tail and adds the result_fetch and result_query tools to read the full text or filter a list back.
// Env: RESULT_CAP_CHARS (longest result kept whole, default 6000)
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const DEFAULT_CAP = 6000;
const HEAD_SHARE = 2 / 3;
const EXEMPT = new Set(["read", "edit", "write", "result_fetch", "result_query", "checkpoint", "ask_user", "asks"]);
const HANDOFF_LINE = /^(ASK:|DENIED:)/m;
const LIST_MIN_ROWS = 20;
const LIST_PREVIEW_ROWS = 20;
const LIST_MATCH_SHARE = 0.9;
const LIST_TOP_FILES = 10;
const DEFAULT_QUERY_LIMIT = 50;
const CODEMODE_HEADER = /^Script completed\n(?:Wall time[^\n]*\n)?Output:\n/;

const capChars = (): number => Number(process.env.RESULT_CAP_CHARS) || DEFAULT_CAP;

export function shape(full: string, ref: string, cap: number): string {
	const head = Math.floor(cap * HEAD_SHARE);
	const marker = `[capped: ${full.length} chars, ref ${ref}; result_fetch({ref, offset?, limit?, pattern?})]`;
	return `${full.slice(0, head)}\n${marker}\n${full.slice(full.length - (cap - head))}`;
}

export type Row = { raw: string; values: Record<string, unknown> };
export type Rows = { format: "json" | "grep" | "paths" | "gitlog"; fields: string[]; rows: Row[]; path?: string };

const LINE_FORMATS = [
	{ format: "grep" as const, fields: ["file", "line", "text"], pattern: /^([^\s:]*[./][^\s:]*):(\d+)[:-](.*)$/ },
	{ format: "gitlog" as const, fields: ["sha", "subject"], pattern: /^([0-9a-f]{7,40}) (.*)$/ },
	{ format: "paths" as const, fields: ["path"], pattern: /^(\S*\/\S*)$/ },
];

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isRecordList = (value: unknown): value is Record<string, unknown>[] => Array.isArray(value) && value.length > 0 && value.every(isRecord);

function parseJson(body: string): Rows | undefined {
	let data: unknown;
	try {
		data = JSON.parse(body);
	} catch {
		return;
	}
	let path: string | undefined;
	if (isRecord(data)) {
		const lists = Object.entries(data).filter(([, value]) => isRecordList(value));
		if (lists.length !== 1) return;
		[path, data] = lists[0];
	}
	if (!isRecordList(data)) return;
	return { format: "json", fields: [...new Set(data.flatMap(Object.keys))], rows: data.map((values) => ({ raw: JSON.stringify(values), values })), path };
}

function parseLines(body: string): Rows | undefined {
	const lines = body.split("\n").filter((line) => line.trim());
	for (const { format, fields, pattern } of LINE_FORMATS) {
		const rows = lines.flatMap((raw) => {
			const match = pattern.exec(raw);
			return match ? [{ raw, values: Object.fromEntries(fields.map((field, i) => [field, match[i + 1]])) }] : [];
		});
		if (rows.length >= lines.length * LIST_MATCH_SHARE) return { format, fields, rows };
	}
}

export function parseRows(text: string): Rows | undefined {
	const body = text.replace(CODEMODE_HEADER, "").trim();
	const list = (/^[[{]/.test(body) && parseJson(body)) || parseLines(body);
	return list && list.rows.length >= LIST_MIN_ROWS ? list : undefined;
}

export function listShape(list: Rows, ref: string, cap: number): string {
	const header = `[list: ${list.rows.length} rows, ${list.format}${list.path ? ` at ${list.path}` : ""}, fields ${list.fields.join(",")}; ref ${ref}; result_query({ref, where?, fields?, sort?, count_by?, limit?, offset?}) or result_fetch for the raw text]`;
	const preview: string[] = [];
	let used = 0;
	for (const { raw } of list.rows.slice(0, LIST_PREVIEW_ROWS)) {
		used += raw.length + 1;
		if (used > cap / 2) break;
		preview.push(raw);
	}
	const counts = new Map<string, number>();
	if (list.format === "grep") for (const { values } of list.rows) counts.set(String(values.file), (counts.get(String(values.file)) ?? 0) + 1);
	const files = [...counts].sort((a, b) => b[1] - a[1]).slice(0, LIST_TOP_FILES);
	return [header, ...preview, ...(files.length ? [`files: ${files.map(([file, count]) => `${file} ${count}`).join(", ")}`] : [])].join("\n");
}

type Stored = { type: string; customType?: string; data?: { ref: string; text: string } };

const lookup = (ctx: ExtensionContext, ref: string) => (ctx.sessionManager.getBranch() as Stored[]).find((entry) => entry.customType === "result-cap" && entry.data?.ref === ref)?.data;

const cell = (row: Row, field: string): string => {
	const value = row.values[field];
	return typeof value === "string" ? value : JSON.stringify(value) ?? "";
};

function compare(a: string, b: string): number {
	return a !== "" && b !== "" && !Number.isNaN(Number(a)) && !Number.isNaN(Number(b)) ? Number(a) - Number(b) : a.localeCompare(b);
}

const reply = (text: string, isError = false) => ({ content: [{ type: "text" as const, text }], details: undefined, isError });

function select(full: string, pattern: string | undefined): string {
	if (!pattern) return full;
	const regex = new RegExp(pattern);
	return full
		.split("\n")
		.flatMap((line, index) => (regex.test(line) ? [`${index}: ${line}`] : []))
		.join("\n");
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "result_fetch",
		label: "Result fetch",
		description:
			"Read the full text of a capped tool result by its `ref`. `pattern` (regex) keeps only matching lines, as `<line>: <text>`. `offset` and `limit` slice the text in characters.",
		parameters: Type.Object({
			ref: Type.String(),
			offset: Type.Optional(Type.Integer({ minimum: 0 })),
			limit: Type.Optional(Type.Integer({ minimum: 1 })),
			pattern: Type.Optional(Type.String()),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const stored = lookup(ctx, params.ref);
			if (!stored) return reply(`Unknown ref ${params.ref}`, true);
			let selected: string;
			try {
				selected = select(stored.text, params.pattern);
			} catch {
				return reply(`Invalid pattern ${params.pattern}`, true);
			}
			const offset = params.offset ?? 0;
			const end = offset + (params.limit ?? capChars());
			return reply(selected.slice(offset, end) + (end < selected.length ? `\n[more: offset ${end}]` : ""));
		},
	});

	pi.registerTool({
		name: "result_query",
		label: "Result query",
		description:
			"Query a capped list result (JSON list, grep lines, paths or git log lines) by its `ref`. `where` maps a field to a regex it must match. `sort` is a field, or `-field` for descending. `count_by` counts the matching rows per value of a field. `fields` picks the fields to return as JSON lines.",
		parameters: Type.Object({
			ref: Type.String(),
			where: Type.Optional(Type.Record(Type.String(), Type.String())),
			fields: Type.Optional(Type.Array(Type.String())),
			sort: Type.Optional(Type.String()),
			count_by: Type.Optional(Type.String()),
			limit: Type.Optional(Type.Integer({ minimum: 1 })),
			offset: Type.Optional(Type.Integer({ minimum: 0 })),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const stored = lookup(ctx, params.ref);
			if (!stored) return reply(`Unknown ref ${params.ref}`, true);
			const list = parseRows(stored.text);
			if (!list) return reply(`Ref ${params.ref} is not a list; use result_fetch`, true);
			const where = Object.entries(params.where ?? {});
			const sortField = params.sort?.replace(/^-/, "");
			const unknown = [...where.map(([field]) => field), ...(params.fields ?? []), sortField, params.count_by].find((field) => field && !list.fields.includes(field));
			if (unknown) return reply(`Unknown field ${unknown}; fields: ${list.fields.join(", ")}`, true);
			let patterns: [string, RegExp][];
			try {
				patterns = where.map(([field, pattern]) => [field, new RegExp(pattern)]);
			} catch {
				return reply(`Invalid where pattern in ${JSON.stringify(params.where)}`, true);
			}
			const matched = list.rows.filter((row) => patterns.every(([field, pattern]) => pattern.test(cell(row, field))));
			if (sortField) matched.sort((a, b) => compare(cell(a, sortField), cell(b, sortField)) * (params.sort?.startsWith("-") ? -1 : 1));
			const offset = params.offset ?? 0;
			const page = <T>(items: T[]) => items.slice(offset, offset + (params.limit ?? DEFAULT_QUERY_LIMIT));
			if (params.count_by) {
				const counts = new Map<string, number>();
				for (const row of matched) counts.set(cell(row, params.count_by), (counts.get(cell(row, params.count_by)) ?? 0) + 1);
				return reply(page([...counts].sort((a, b) => b[1] - a[1])).map(([value, count]) => `${value}\t${count}`).join("\n"));
			}
			const shown = page(matched);
			const lines = shown.map((row) => (params.fields ? JSON.stringify(Object.fromEntries(params.fields.map((field) => [field, row.values[field]]))) : row.raw));
			return reply([`rows ${shown.length} of ${matched.length} matched, ${list.rows.length} total (offset ${offset}); omitted ${Math.max(0, matched.length - offset - shown.length)}`, ...lines].join("\n"));
		},
	});

	pi.on("tool_result", (event) => {
		if (event.parentToolCallId || event.isError || EXEMPT.has(event.toolName) || event.content.some((block) => block.type !== "text")) return;
		const full = event.content.map((block) => (block.type === "text" ? block.text : "")).join("\n");
		if (full.length <= capChars() || HANDOFF_LINE.test(full)) return;
		const ref = `rc-${event.toolCallId}`;
		try {
			pi.appendEntry("result-cap", { ref, text: full });
		} catch {
			return;
		}
		const list = parseRows(full);
		return { content: [{ type: "text" as const, text: list ? listShape(list, ref, capChars()) : shape(full, ref, capChars()) }] };
	});
}
