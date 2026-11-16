// Adds the transcript tool, which reads the session's own branch, including the entries that folds, checkpoint rewinds and compaction took out of context.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Block = { type: string; id?: string; name?: string; text?: string; arguments?: unknown };
type Message = { role: string; content?: string | Block[]; toolName?: string; customType?: string; details?: { action?: string; target?: string } };
type Entry = { id: string; type: string; message?: Message; content?: unknown };
type Projected = { sourceEntry: Entry; messages: unknown[] };
type Kind = "compacted" | "removed" | "folded";
type Region = { kind: Kind; entries: Entry[]; target?: string };

const DEFAULT_LIMIT = 6000;
const LINE_CHARS = 300;

const blocks = (message?: Message): Block[] => (Array.isArray(message?.content) ? message.content : []);
const plain = (content: unknown): string =>
	typeof content === "string" ? content : Array.isArray(content) ? content.map((block: Block) => block.text ?? "").join("\n") : "";

function render(entry: Entry): string {
	const message = entry.message;
	if (!message) return `[${entry.id} ${entry.type}] ${plain(entry.content)}`;
	const calls = blocks(message).flatMap((block) => (block.type === "toolCall" ? [`-> ${block.name} ${JSON.stringify(block.arguments)}`] : []));
	const label = message.role === "toolResult" ? `toolResult ${message.toolName}` : (message.customType ?? message.role);
	return [`[${entry.id} ${label}] ${plain(message.content)}`, ...calls].join("\n").trimEnd();
}

const isMessage = (entry: Entry) => entry.type === "message" || entry.type === "custom_message";
const rewindTarget = (entry: Entry) =>
	entry.message?.role === "toolResult" && entry.message.toolName === "checkpoint" && entry.message.details?.action === "rewind" ? entry.message.details.target : undefined;

/** Contiguous runs of branch entries whose model view is missing, empty or edited, by kind. */
function regions(branch: Entry[], projected: Projected[]): Region[] {
	const view = new Map(projected.map((entry) => [entry.sourceEntry.id, entry.messages]));
	const out: Region[] = [];
	let open: Region | undefined;
	for (const [index, entry] of branch.entries()) {
		if (!isMessage(entry)) continue;
		const messages = view.get(entry.id);
		const kind: Kind | undefined = !messages ? "compacted" : !messages.length ? "removed" : JSON.stringify(messages) !== JSON.stringify([entry.message]) ? "folded" : undefined;
		if (!kind) {
			if (open?.kind === "removed") open.target = branch.slice(index).map(rewindTarget).find(Boolean);
			open = undefined;
		} else if (open?.kind === kind) open.entries.push(entry);
		else out.push((open = { kind, entries: [entry] }));
	}
	return out;
}

function index(found: Region[]): string {
	if (!found.length) return "Nothing on this branch is folded, removed or compacted.";
	const lines = found.map((region) => {
		const ids = region.entries.map((entry) => entry.id);
		const tools = [...new Set(region.entries.flatMap((entry) => (entry.message?.toolName ? [entry.message.toolName] : [])))];
		const chars = region.entries.reduce((sum, entry) => sum + render(entry).length, 0);
		const range = ids.length > 1 ? `${ids[0]}..${ids.at(-1)}` : ids[0];
		return `${region.kind} ${range} (${ids.length} entries, ${chars} chars${tools.length ? `, tools ${tools.join(",")}` : ""}${region.target ? `, checkpoint "${region.target}"` : ""})`;
	});
	return `${lines.join("\n")}\nRead one with transcript({around: <entry id or checkpoint target>}), or search with transcript({pattern}).`;
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "transcript",
		label: "Transcript",
		description:
			"Read this session's own branch, including entries folds, checkpoint rewinds and compaction took out of your context. No arguments: an index of those regions. `around`: the raw entries of the region holding an entry id or checkpoint target. `pattern`: matching entries (regex). Page with `offset` and `limit` in characters.",
		parameters: Type.Object({
			pattern: Type.Optional(Type.String()),
			around: Type.Optional(Type.String()),
			offset: Type.Optional(Type.Integer({ minimum: 0 })),
			limit: Type.Optional(Type.Integer({ minimum: 1 })),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const branch = ctx.sessionManager.getBranch() as unknown as Entry[];
			const found = regions(branch, ctx.sessionManager.buildSessionProjection().entries as unknown as Projected[]);
			let body: string;
			if (params.pattern) {
				let regex: RegExp;
				try {
					regex = new RegExp(params.pattern, "i");
				} catch {
					return { content: [{ type: "text" as const, text: `Invalid pattern ${params.pattern}` }], details: {}, isError: true };
				}
				body = branch.map(render).filter((line) => regex.test(line)).map((line) => line.slice(0, LINE_CHARS)).join("\n") || `no entry matches /${params.pattern}/`;
			} else if (params.around) {
				const region = found.find((candidate) => candidate.target === params.around || candidate.entries.some((entry) => entry.id === params.around));
				if (!region) throw new Error(`no folded region holds "${params.around}". ${index(found)}`);
				body = region.entries.map(render).join("\n\n");
			} else body = index(found);
			const offset = params.offset ?? 0;
			const limit = params.limit ?? DEFAULT_LIMIT;
			const page = body.slice(offset, offset + limit);
			const more = offset + limit < body.length ? `\n[${body.length} chars; continue with offset: ${offset + limit}]` : "";
			return { content: [{ type: "text" as const, text: page + more }], details: {} };
		},
	});
}
