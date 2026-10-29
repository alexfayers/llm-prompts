// Helps codemode scripts call MCP tools: parses JSON results, lists tool names and schemas, and learns result shapes.
// Cache: mcp-hints-cache.json in the pi agent directory, holding the schemas and result shapes seen in earlier sessions
import fs from "node:fs";
import path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const MCP_NAME = /^mcp__(.+?)__(.+)$/;
const SHAPE_KEY = /^[A-Za-z_$][\w$]{0,39}$/;
const DISTINCTIVE_NAME = /_|[a-z][A-Z]/;
const CODE_FENCE = /```[\s\S]*?(```|$)/g;
const LIMITS = { bareName: 8, notes: 3, noteChars: 8000, enumValues: 6, shapeKeys: 8, shapeDepth: 3, shapeChars: 300 };

type Json = Record<string, unknown>;
type Schema = { name: string; description: string; parameters?: unknown; resultShape?: string };
type Cache = Record<string, Schema>;

const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const serverOf = (name: string) => MCP_NAME.exec(name)?.[1];
const bareName = (name: string) => MCP_NAME.exec(name)?.[2] ?? name;
const cacheFile = () => path.join(getAgentDir(), "mcp-hints-cache.json");

function parseJson(text: string, depth = 2): object | undefined {
	let parsed: unknown;
	try {
		parsed = /^[{["]/.test(text.trim()) ? JSON.parse(text) : undefined;
	} catch {
		return undefined;
	}
	if (typeof parsed === "string") return depth > 1 ? parseJson(parsed, depth - 1) : undefined;
	return typeof parsed === "object" && parsed !== null ? parsed : undefined;
}

function parseFields(fields: Json): Json | undefined {
	const parsed = Object.entries(fields).map(([key, value]) => [key, typeof value === "string" ? parseJson(value) : undefined] as const);
	return parsed.some(([, value]) => value) ? Object.fromEntries(parsed.map(([key, value]) => [key, value ?? fields[key]])) : undefined;
}

function scriptValue(result: Json): Json | undefined {
	const { content, structuredContent: structured } = result as { content: Json[]; structuredContent?: unknown };
	const fromText = structured === undefined && content.length === 1 && content[0].type === "text" ? parseJson(String(content[0].text)) : undefined;
	const source = structured ?? fromText;
	const structuredContent = (isRecord(source) ? parseFields(source) : undefined) ?? fromText;
	return structuredContent && { ...result, structuredContent };
}

function shapeOf(value: unknown, depth: number): string {
	if (value === null || typeof value !== "object") return value === null ? "null" : typeof value;
	if (Array.isArray(value)) return value.length === 0 ? "[]" : `${shapeOf(value[0], depth)}[]`;
	if (depth === 0) return "{...}";
	const entries = Object.entries(value);
	if (entries.some(([key]) => !SHAPE_KEY.test(key))) return `{[key: string]: ${shapeOf(entries[0][1], depth - 1)}}`;
	const listed = entries.slice(0, LIMITS.shapeKeys).map(([key, item]) => `${key}: ${shapeOf(item, depth - 1)}`);
	return `{${[...listed, ...(entries.length > LIMITS.shapeKeys ? ["..."] : [])].join(", ")}}`;
}

function resultShape(value: unknown): string | undefined {
	const keys = isRecord(value) ? Object.keys(value) : [];
	const failure = keys.length > 0 && keys.every((key) => key === "error" || key === "status") && (keys.includes("error") || (value as Json).status === "error");
	if (value === undefined || failure) return undefined;
	return Array.from({ length: LIMITS.shapeDepth }, (_, i) => shapeOf(value, LIMITS.shapeDepth - i)).find((shape) => shape.length <= LIMITS.shapeChars);
}

function typeOf(schema: unknown): string | undefined {
	if (!isRecord(schema)) return undefined;
	const choices = (Array.isArray(schema.enum) ? schema.enum : []).filter((value) => typeof value === "string" || typeof value === "number");
	if (choices.length > 0) return [...choices.slice(0, LIMITS.enumValues), ...(choices.length > LIMITS.enumValues ? ["..."] : [])].join("|");
	const type = [schema.type].flat().find((each) => typeof each === "string" && each !== "null");
	if (type !== undefined) return type === "array" ? `${typeOf(schema.items) ?? "any"}[]` : String(type);
	const options = [schema.anyOf, schema.oneOf].find(Array.isArray) as unknown[] | undefined;
	return options && (options.map(typeOf).find((each) => each !== undefined) ?? "any");
}

function toolLabel({ name, parameters }: Schema): string {
	const { required, properties } = (parameters ?? {}) as { required?: unknown[]; properties?: Json };
	const args = (Array.isArray(required) ? required : []).filter((arg) => typeof arg === "string").map((arg) => [`${arg}*`, typeOf(properties?.[arg])].filter(Boolean).join(": "));
	return args.length > 0 ? `${bareName(name)}(${args.join(", ")})` : bareName(name);
}

function hintText(tool: Schema): string | undefined {
	const shape = tool.resultShape === undefined ? "" : ` Script result .structuredContent: ${tool.resultShape}`;
	const full = `Schema of ${tool.name}: ${tool.description} Parameters (JSON Schema): ${JSON.stringify(tool.parameters)}${shape}`;
	if (full.length <= LIMITS.noteChars) return full;
	const head = `Schema of ${tool.name}:`;
	const tail = `Required args only, full schema too large: ${toolLabel(tool)}${shape}`;
	const room = LIMITS.noteChars - head.length - tail.length - 2;
	const description = tool.description.length <= room ? tool.description : `${tool.description.slice(0, Math.max(room - 3, 0))}...`;
	const compact = [head, description, tail].filter(Boolean).join(" ");
	return compact.length <= LIMITS.noteChars ? compact : undefined;
}

function mentionPosition(prompt: string, tool: Schema, tools: Schema[]): number {
	const find = (name: string) => prompt.search(new RegExp(`(?<![A-Za-z0-9_])${name.replace(/[.*+?^${}()|[\]\\-]/g, "\\$&")}(?![A-Za-z0-9_])`));
	const bare = bareName(tool.name);
	const bareIsUsable = bare.length >= LIMITS.bareName && DISTINCTIVE_NAME.test(bare) && tools.filter((other) => bareName(other.name) === bare).length === 1;
	const found = [find(tool.name), bareIsUsable ? find(bare) : -1].filter((position) => position >= 0);
	return found.length === 0 ? -1 : Math.min(...found);
}

function readCache(): Cache {
	try {
		return JSON.parse(fs.readFileSync(cacheFile(), "utf8"));
	} catch {
		return {};
	}
}

function writeCache(cache: Cache): void {
	try {
		fs.writeFileSync(cacheFile(), JSON.stringify(cache));
	} catch {}
}

function loadCache(live: Schema[]): Cache {
	const saved = readCache();
	const servers = new Set(live.map(({ name }) => serverOf(name)));
	const kept = Object.entries(saved).filter(([name]) => !servers.has(serverOf(name)));
	const seen = live.map(({ name, description, parameters }) => [name, { name, description, parameters: parameters ?? saved[name]?.parameters, resultShape: saved[name]?.resultShape }] as const);
	const next = Object.fromEntries([...kept, ...seen]);
	if (JSON.stringify(saved) !== JSON.stringify(next)) writeCache(next);
	return next;
}

const newState = () => ({ listed: new Set<string>(), seen: new Set<string>(), pending: new Map<string, string[]>() });

function learnShape(live: Schema[], name: string, shape: string): void {
	const cache = loadCache(live);
	if (cache[name] && (cache[name].resultShape?.length ?? 0) < shape.length) writeCache({ ...cache, [name]: { ...cache[name], resultShape: shape } });
}

export default function (pi: ExtensionAPI) {
	let state = newState();
	const liveTools = () => (pi.getAllTools() as Schema[]).filter(({ name }) => serverOf(name) !== undefined);
	pi.on("session_start", () => void (state = newState()));
	pi.on("tool_call", ({ toolName, parentToolCallId: parent }) => {
		const tool = parent !== undefined && serverOf(toolName) && !state.seen.has(toolName) && !pi.getActiveTools().includes(toolName) ? loadCache(liveTools())[toolName] : undefined;
		const text = tool && hintText(tool);
		if (parent !== undefined && text !== undefined) state.pending.set(parent, [...(state.pending.get(parent) ?? []), text]);
		state.seen.add(toolName);
	});
	pi.on("tool_result", (event) => {
		const hints = state.pending.get(event.toolCallId);
		state.pending.delete(event.toolCallId);
		const server = event.structuredContent;
		const scripted = event.parentToolCallId !== undefined && serverOf(event.toolName) !== undefined && isRecord(server) && Array.isArray(server.content) ? server : undefined;
		const next = scripted && scriptValue(scripted);
		const shape = event.isError ? undefined : resultShape((next ?? scripted)?.structuredContent);
		if (shape) learnShape(liveTools(), event.toolName, shape);
		if (!next && !hints) return undefined;
		return { ...(next && { structuredContent: next as typeof event.structuredContent }), ...(hints && { content: [...event.content, { type: "text" as const, text: hints.join("\n\n") }] }) };
	});
	pi.on("before_agent_start", (event) => {
		if (!("prompt" in event)) return undefined;
		const live = liveTools();
		const cache = loadCache(live);
		const declared = new Set(pi.getActiveTools());
		const unlisted = live.filter(({ name }) => !declared.has(name) && !state.listed.has(name)).map(({ name }) => cache[name]);
		unlisted.forEach(({ name }) => state.listed.add(name));
		const prompt = event.prompt.replace(CODE_FENCE, "");
		const tools = Object.values(cache);
		const noted = tools
			.filter(({ name }) => !declared.has(name) && !state.seen.has(name))
			.map((tool) => ({ tool, position: mentionPosition(prompt, tool, tools) }))
			.filter(({ position }) => position >= 0)
			.sort((a, b) => a.position - b.position)
			.map(({ tool }) => ({ name: tool.name, text: hintText(tool) }))
			.filter(({ text }) => text !== undefined)
			.slice(0, LIMITS.notes);
		noted.forEach(({ name }) => state.seen.add(name));
		const servers = new Map<string, string[]>();
		unlisted.forEach((tool) => servers.set(serverOf(tool.name)!, [...(servers.get(serverOf(tool.name)!) ?? []), toolLabel(tool)]));
		const names = servers.size > 0 ? [["MCP tools, callable ONLY inside codemode as tools.mcp__<server>__<tool>(args), never as direct tool calls:", ...[...servers].map(([server, labels]) => `${server}: ${labels.join(", ")}`)].join("\n")] : [];
		const content = [...names, ...noted.map(({ text }) => text)].join("\n\n");
		return content === "" ? undefined : { message: { customType: "mcp-hints", content, display: false } };
	});
}
