// Defines the roles of delegated pi sessions and the tool_call guard that enforces them.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { ExtensionContext, ToolCallEvent } from "@earendil-works/pi-coding-agent";

export type Role = {
	name: "reader" | "writer" | "btw";
	card: string;
	/** Allowed non-MCP tool names, as globs. */
	tools: string[];
	/** Allowed MCP tool names (`mcp__<server>__<tool>`), as globs. */
	mcp: string[];
	skills: string[];
	/** The role writes in its own worktree. */
	writes: boolean;
};

export type Block = { block: true; reason: string };

const OUTCOME = "Open the final reply with `OUTCOME <code> ref:<ref>`. Put any question for the user on a line starting `ASK:` and do not ask the user directly.";
const READ_TOOLS = ["read", "grep", "find", "ls", "bash", "codemode", "lsp_diagnostics", "web_search", "fetch_content", "get_search_content", "result_fetch", "result_query"];
const READ_MCP = [
	"mcp__semble__*",
	"mcp__memory__read_*",
	"mcp__memory__search_*",
	"mcp__memory__get_*",
	"mcp__memory__list_*",
];

export const ROLES: Record<Role["name"], Role> = {
	reader: {
		name: "reader",
		card: `You are a read-only delegate. Investigate and report. Do not change files, git state or memory. ${OUTCOME}`,
		tools: READ_TOOLS,
		mcp: READ_MCP,
		skills: [],
		writes: false,
	},
	writer: {
		name: "writer",
		card: `You are a delegate that works in its own git worktree. Commit your work there. Do not touch other paths or memory. ${OUTCOME}`,
		tools: [...READ_TOOLS, "edit", "write", "process"],
		mcp: READ_MCP,
		skills: [],
		writes: true,
	},
	btw: {
		name: "btw",
		card: "You answer one side question for the user. Read-only. Answer briefly and do not continue the main task.",
		tools: READ_TOOLS,
		mcp: READ_MCP,
		skills: [],
		writes: false,
	},
};

const globRegExp = (pattern: string) => new RegExp(`^${pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*")}$`);
const matches = (globs: string[], name: string) => globs.some((glob) => globRegExp(glob).test(name));

const WRITE_TOOLS = ["edit", "write"];
const PATH_KEYS = ["path", "file_path"];
const PATH_ARGS = [...PATH_KEYS, "cwd"];
const startsProcess = (toolName: string, input: Record<string, unknown>) => toolName === "process" && input.action === "start";

const inside = (root: string, target: string) => target === root || target.startsWith(root + path.sep);
const expandHome = (target: string) => (target === "~" || target.startsWith("~/") ? path.join(os.homedir(), target.slice(1)) : target);

/** Returns a block when the role may not make this call. A role with `writes` may write only inside its worktree. */
export function decide(role: Role, toolName: string, input: Record<string, unknown>, worktree?: string): Block | undefined {
	const allowed = matches(toolName.startsWith("mcp__") ? role.mcp : role.tools, toolName);
	if (!allowed) return { block: true, reason: `role ${role.name} may not use ${toolName}` };
	if (!role.writes || !(WRITE_TOOLS.includes(toolName) || startsProcess(toolName, input))) return undefined;
	if (!worktree) return { block: true, reason: `role ${role.name} has no worktree to write in` };
	const target = PATH_ARGS.map((key) => input[key]).find((value) => typeof value === "string");
	if (typeof target === "string" && inside(worktree, path.resolve(worktree, expandHome(target)))) return undefined;
	return { block: true, reason: `role ${role.name} may write only inside ${worktree}` };
}

const shellQuote = (text: string) => `'${text.replaceAll("'", "'\\''")}'`;

/** Points main-directory paths in the call at the worktree, in place. Bash and started processes also run in the worktree. */
export function rewriteForWorktree(toolName: string, input: Record<string, unknown>, worktree: string, mainCwd: string): void {
	const mainPath = new RegExp(`${mainCwd.replace(/[.+?^${}()|[\]\\]/g, "\\$&")}(?![\\w.-])`, "g");
	const shell = toolName === "bash" || toolName === "process";
	if (startsProcess(toolName, input)) input.cwd = worktree;
	if (shell && typeof input.command === "string") {
		const prefix = `cd ${shellQuote(worktree)} && `;
		const command = input.command.split(worktree).map((part) => part.replace(mainPath, worktree)).join(worktree);
		input.command = toolName === "process" || command.startsWith(prefix) ? command : prefix + command;
	}
	if (shell) return;
	for (const key of PATH_ARGS) {
		const value = typeof input[key] === "string" ? expandHome(input[key]) : undefined;
		if (value === undefined || inside(worktree, value)) continue;
		input[key] = inside(mainCwd, value) ? worktree + value.slice(mainCwd.length) : path.resolve(worktree, value);
	}
}

function readHandshake(file: string): { role: Role; worktree?: string } | undefined {
	try {
		const { role, worktree } = JSON.parse(fs.readFileSync(file, "utf8")) as { role?: string; worktree?: string };
		if (role === undefined || !Object.hasOwn(ROLES, role)) return undefined;
		return { role: ROLES[role as Role["name"]], worktree: typeof worktree === "string" ? worktree : undefined };
	} catch {
		return undefined;
	}
}

/** Builds the tool_call handler of a delegated session from its handshake file. A bad handshake blocks every call. */
export function childGuard(handshakeFile: string): (event: ToolCallEvent, ctx: ExtensionContext) => Block | undefined {
	const child = readHandshake(handshakeFile);
	return ({ toolName, input }, { cwd }) => {
		if (!child) return { block: true, reason: `pi-context handshake ${handshakeFile} is unreadable or names an unknown role` };
		const worktree = child.role.writes ? child.worktree : undefined;
		if (worktree) rewriteForWorktree(toolName, input, worktree, cwd);
		return decide(child.role, toolName, input, worktree);
	};
}
