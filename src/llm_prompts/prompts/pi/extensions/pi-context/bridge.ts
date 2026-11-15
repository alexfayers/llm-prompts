// Lets a delegate call main's MCP tools over a unix socket, so a fork starts no MCP servers of its own.
// Env: PI_CONTEXT_MCP_PROXY (set to 1 to start forks with --no-mcp and proxy tools)
import { createHash } from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { decide, type Role } from "./roles.ts";

export type BridgeResult = { content: { type: string; text?: string }[]; details?: unknown; structuredContent?: unknown; isError: boolean };
type Request = { id: number; tool: string; args: unknown };
type Reply = { id: number; result?: BridgeResult; error?: string };

export type BridgeOptions = {
	role: Role;
	/** Runs the call in main, through its hooks. */
	execute: (tool: string, args: unknown, signal?: AbortSignal) => Promise<BridgeResult>;
	onPrefix?: (hash: string) => void;
};

const SOCKET = "b.sock";
const MCP_RESOURCE_TOOLS = new Set(["list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource"]);
const isProxied = (name: string) => name.startsWith("mcp__") || MCP_RESOURCE_TOOLS.has(name);

/** Calls `onRecord` for every complete LF-terminated JSON record on the socket. */
function readRecords(socket: net.Socket, onRecord: (record: Record<string, unknown>) => void): void {
	let buffer = "";
	socket.setEncoding("utf8");
	socket.on("data", (chunk: string) => {
		buffer += chunk;
		for (let end = buffer.indexOf("\n"); end >= 0; end = buffer.indexOf("\n")) {
			const line = buffer.slice(0, end);
			buffer = buffer.slice(end + 1);
			try {
				onRecord(JSON.parse(line));
			} catch {
				socket.destroy();
			}
		}
	});
	socket.on("error", () => undefined);
}

const send = (socket: net.Socket, record: Reply | { prefix: string } | Request) => void (!socket.destroyed && socket.write(`${JSON.stringify(record)}\n`));

/** Serves the role's MCP calls on a socket in `dir`, which must be private to the user. */
export async function serveBridge(dir: string, { role, execute, onPrefix }: BridgeOptions): Promise<{ socket: string; close(): Promise<void> }> {
	const socketPath = path.join(dir, SOCKET);
	const connections = new Set<net.Socket>();
	const server = net.createServer((connection) => {
		connections.add(connection);
		connection.once("close", () => connections.delete(connection));
		readRecords(connection, (record) => {
			if (typeof record.prefix === "string") return onPrefix?.(record.prefix);
			const { id, tool, args } = record as Request;
			if (!isProxied(tool)) return send(connection, { id, error: `${tool} is not an MCP tool` });
			const blocked = decide(role, tool, (args ?? {}) as Record<string, unknown>);
			if (blocked) return send(connection, { id, error: blocked.reason });
			execute(tool, args).then(
				(result) => send(connection, { id, result }),
				(error: Error) => send(connection, { id, error: error.message }),
			);
		});
	});
	await new Promise<void>((resolve, reject) => {
		server.once("error", reject);
		server.listen(socketPath, () => resolve());
	});
	server.on("error", () => undefined);
	fs.chmodSync(socketPath, 0o600);
	return {
		socket: socketPath,
		close: () =>
			new Promise<void>((resolve) => {
				for (const connection of connections) connection.destroy();
				server.close(() => resolve());
			}),
	};
}

export type BridgeClient = {
	call(tool: string, args: unknown): Promise<BridgeResult>;
	report(prefixHash: string): void;
	close(): void;
};

/** Connects to a bridge. A call rejects with the refusal or failure text. */
export async function connectBridge(socketPath: string): Promise<BridgeClient> {
	const socket = net.connect(socketPath);
	await new Promise<void>((resolve, reject) => {
		socket.once("error", reject);
		socket.once("connect", () => resolve());
	});
	const pending = new Map<number, { resolve: (result: BridgeResult) => void; reject: (error: Error) => void }>();
	let nextId = 0;
	readRecords(socket, (record) => {
		const { id, result, error } = record as Reply;
		const waiting = pending.get(id);
		pending.delete(id);
		if (!waiting) return;
		if (result) waiting.resolve(result);
		else waiting.reject(new Error(error ?? "empty bridge reply"));
	});
	socket.once("close", () => {
		for (const waiting of pending.values()) waiting.reject(new Error("the MCP bridge to the parent session closed"));
		pending.clear();
	});
	return {
		call: (tool, args) =>
			new Promise<BridgeResult>((resolve, reject) => {
				const id = nextId++;
				pending.set(id, { resolve, reject });
				send(socket, { id, tool, args });
			}),
		report: (prefix) => send(socket, { prefix }),
		close: () => void socket.destroy(),
	};
}

export type ProxyTool = { name: string; description: string; parameters: unknown; exposure: string; namespace?: unknown; annotations?: unknown };
/** What a delegate needs to declare the same tools and MCP servers section as main. */
export type MainDescription = { activeTools: string[]; tools: ProxyTool[]; section?: string };
export type BridgeConfig = MainDescription & { socket: string };

const SERVERS_SECTION = "mcp_servers";
const SECTION_PATTERN = new RegExp(`<${SERVERS_SECTION}>\\n([\\s\\S]*?)\\n</${SERVERS_SECTION}>`);

export const mcpProxyEnabled = () => process.env.PI_CONTEXT_MCP_PROXY === "1";

/** Hashes the part of a provider request that precedes the messages: the system prompt and the tool declarations. */
export function prefixHash(payload: unknown): string {
	const { system, tools, toolConfig } = payload as Record<string, unknown>;
	return createHash("sha256").update(JSON.stringify([system, tools ?? toolConfig])).digest("hex");
}

/** Describes main's tools and servers section, cut to the tools `role` may use when given. */
export function describeMain(pi: ExtensionAPI, ctx: ExtensionContext, role?: Role): MainDescription {
	const allowed = (name: string) => !role || !decide(role, name, {});
	const tools = pi.getAllTools().filter(({ name }) => isProxied(name) && allowed(name));
	return {
		activeTools: pi.getActiveTools().filter(allowed),
		tools: tools.map(({ name, description, parameters, exposure, namespace, annotations }) => ({ name, description, parameters, exposure, namespace, annotations })),
		section: SECTION_PATTERN.exec(ctx.getSystemPrompt())?.[1],
	};
}

/** The bridge the handshake file describes, or undefined for a delegate that runs its own MCP servers. */
export function readBridgeConfig(handshakeFile: string): BridgeConfig | undefined {
	try {
		return (JSON.parse(fs.readFileSync(handshakeFile, "utf8")) as { bridge?: BridgeConfig }).bridge;
	} catch {
		return undefined;
	}
}

let lastPrefix: string | undefined;
export const lastPrefixHash = () => lastPrefix;

/** Remembers the prefix hash of main's latest provider request. */
export function trackPrefix(pi: ExtensionAPI): void {
	pi.on("before_provider_request", ({ payload }) => void (lastPrefix = prefixHash(payload)));
}

/** In a delegate without MCP servers: registers main's MCP tools as proxies and declares main's tools and servers section. */
export function registerChildBridge(pi: ExtensionAPI, config: BridgeConfig): void {
	let connection: Promise<BridgeClient> | undefined;
	const connected = () =>
		(connection ??= connectBridge(config.socket).catch((error: Error) => {
			connection = undefined;
			throw error;
		}));
	for (const { name, description, parameters, exposure, namespace, annotations } of config.tools) {
		pi.registerTool({
			name,
			label: name,
			description,
			parameters: parameters as never,
			exposure: exposure as never,
			namespace: namespace as never,
			annotations: annotations as never,
			async execute(_id, params) {
				const { content, details, structuredContent, isError } = await (await connected()).call(name, params);
				if (isError) throw new Error(content.map((block) => block.text ?? "").join("\n"));
				return { content, details, structuredContent } as never;
			},
		});
	}
	pi.on("session_start", () => void pi.setActiveTools(config.activeTools));
	pi.on("before_agent_start", ({ systemPromptOptions: { sections } }) => {
		if (config.section) sections[SERVERS_SECTION] = config.section;
		else delete sections[SERVERS_SECTION];
	});
	let reported = false;
	pi.on("before_provider_request", async ({ payload }) => {
		if (reported) return;
		reported = true;
		(await connected()).report(prefixHash(payload));
	});
}
