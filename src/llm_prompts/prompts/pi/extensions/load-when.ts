// Adds each rule listed in conditional-rules.json when its load_when condition holds or a read, grep, find, edit or write call touches a file matching its paths.
// Config: conditional-rules.json and rules/ in the pi agent directory, written by llm-prompts install
// Env: PI_CONTEXT_CHILD (a pi-context handshake without `inherited` marks a cold delegate, which skips audience:main rules)
import fs from "node:fs";
import path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

type ContextFile = { path: string; content: string };
type Entry = { id: string; type: string; customType?: string; details?: { rule?: string }; firstKeptEntryId?: string };

const PATHS_PREFIX = "paths:";
const CUSTOM_TYPE = "load-when";
const PATH_TOOLS = new Set(["read", "edit", "write"]);
const LISTING_TOOLS = new Set(["grep", "find"]);
const MAIN_ONLY_KEY = "audience:main";
const GREP_LINE = /^(.+?)[:-]\d+[:-] /;

function readConditional(): Record<string, string[]> {
	try {
		return JSON.parse(fs.readFileSync(path.join(getAgentDir(), "conditional-rules.json"), "utf8"));
	} catch {
		return {};
	}
}

function ruleFiles(names: Iterable<string>): ContextFile[] {
	return [...new Set(names)].sort().flatMap((name) => {
		const file = path.join(getAgentDir(), "rules", name);
		try {
			return [{ path: file, content: fs.readFileSync(file, "utf8") }];
		} catch {
			return [];
		}
	});
}

function heldNames(conditional: Record<string, string[]>, kind: string, holds: (value: string) => boolean): string[] {
	return Object.entries(conditional).flatMap(([condition, names]) => (condition.startsWith(`${kind}:`) && holds(condition.slice(kind.length + 1)) ? names : []));
}

function onPath(command: string): boolean {
	return (process.env.PATH ?? "").split(path.delimiter).some((dir) => {
		try {
			fs.accessSync(path.join(dir, command), fs.constants.X_OK);
			return true;
		} catch {
			return false;
		}
	});
}

function coldDelegate(): boolean {
	const handshake = process.env.PI_CONTEXT_CHILD;
	if (!handshake) return false;
	try {
		return !JSON.parse(fs.readFileSync(handshake, "utf8")).inherited;
	} catch {
		return true;
	}
}

function sentRules(ctx: ExtensionContext): Set<string> {
	const branch = ctx.sessionManager.getBranch() as Entry[];
	const compaction = [...branch].reverse().find((entry) => entry.type === "compaction");
	const kept = compaction ? branch.slice(Math.max(0, branch.findIndex((entry) => entry.id === compaction.firstKeptEntryId))) : branch;
	return new Set(kept.flatMap((entry) => (entry.type === "custom_message" && entry.customType === CUSTOM_TYPE && entry.details?.rule ? [entry.details.rule] : [])));
}

function touchedFiles(toolName: string, input: { path?: string }, text: string, cwd: string): string[] {
	const target = path.resolve(cwd, input.path ?? ".");
	if (PATH_TOOLS.has(toolName)) return [target];
	const listed = text.split("\n").flatMap((line) => (toolName === "grep" ? (GREP_LINE.exec(line)?.[1] ?? []) : line ? [line] : []));
	return [target, ...listed.map((file) => path.resolve(target, file))];
}

export default function (pi: ExtensionAPI) {
	let conditional: Record<string, string[]> | undefined;
	let fixed: { cwd: string; names: string[] } | undefined;
	let loaded: { key: string; files: ContextFile[] } | undefined;
	let sent = new Set<string>();
	let active = false;
	pi.on("session_start", (_event, ctx) => {
		conditional = undefined;
		fixed = undefined;
		loaded = undefined;
		sent = sentRules(ctx);
		active = false;
	});
	pi.on("session_compact", (_event, ctx) => void (sent = sentRules(ctx)));
	pi.on("session_tree", (_event, ctx) => void (sent = sentRules(ctx)));
	pi.on("before_agent_start", ({ systemPromptOptions: { cwd, contextFiles } }) => {
		active = contextFiles.some((file) => path.resolve(file.path) === path.join(getAgentDir(), "AGENTS.md"));
		if (!active) return;
		conditional ??= readConditional();
		if (fixed?.cwd !== cwd) fixed = { cwd, names: [...heldNames(conditional, "env", (name) => Boolean(process.env[name])), ...heldNames(conditional, "tool", onPath)] };
		const tools = new Set(pi.getAllTools().map((tool) => tool.name));
		const mainOnly = new Set(coldDelegate() ? (conditional[MAIN_ONLY_KEY] ?? []) : []);
		const held = [...fixed.names, ...heldNames(conditional, "tool", (name) => tools.has(name))];
		const names = [...new Set(held)].filter((name) => !mainOnly.has(name)).sort();
		if (loaded?.key !== names.join("\0")) loaded = { key: names.join("\0"), files: ruleFiles(names) };
		const present = new Set(contextFiles.map((file) => path.resolve(file.path)));
		contextFiles.push(...loaded.files.filter((file) => !present.has(file.path)));
	});
	pi.on("tool_result", (event, ctx) => {
		if (!active || !conditional || event.isError || !(PATH_TOOLS.has(event.toolName) || LISTING_TOOLS.has(event.toolName))) return;
		const text = event.content.flatMap((block) => (block.type === "text" ? [block.text] : [])).join("\n");
		const files = touchedFiles(event.toolName, event.input as { path?: string }, text, ctx.cwd);
		const matches = (glob: string) => files.some((file) => path.matchesGlob(file, glob) || path.matchesGlob(path.relative(ctx.cwd, file), glob));
		const names = Object.entries(conditional).flatMap(([key, rules]) => (key.startsWith(PATHS_PREFIX) && matches(key.slice(PATHS_PREFIX.length)) ? rules.filter((name) => !sent.has(name)) : []));
		for (const file of ruleFiles(names)) {
			const rule = path.basename(file.path);
			sent.add(rule);
			pi.sendMessage({ customType: CUSTOM_TYPE, content: file.content, display: false, details: { rule } }, { deliverAs: "steer" });
		}
	});
}
