// Adds the tower_do_patch tool, which changes single tasks on the board without resending all of them.
// Also gives the first agent start of a main session a short board summary.
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import type { ExtensionAPI, ExtensionContext, ExtensionToolContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

export type TaskRow = { key: string; [field: string]: unknown };

function duplicates(keys: string[]): string[] {
	return keys.filter((key, index) => keys.indexOf(key) !== index);
}

export function mergeTasks(currentKeys: string[], upserts: TaskRow[], removes: string[]): TaskRow[] {
	const upserted = upserts.map((row) => row.key);
	if (upserted.length + removes.length === 0) throw new Error("tower_do_patch: nothing to change");
	const repeated = duplicates([...upserted, ...removes]);
	if (repeated.length > 0) {
		const both = repeated.filter((key) => upserted.includes(key) && removes.includes(key));
		const kind = both.length > 0 ? "in both tasks and remove" : "duplicate";
		throw new Error(`tower_do_patch: key ${kind}: ${repeated.join(", ")}`);
	}
	const unknown = removes.filter((key) => !currentKeys.includes(key));
	if (unknown.length > 0) throw new Error(`tower_do_patch: cannot remove unknown key: ${unknown.join(", ")}`);
	const touched = new Set([...upserted, ...removes]);
	return [...upserts, ...currentKeys.filter((key) => !touched.has(key)).map((key) => ({ key }))];
}

export type PatchParams = { tasks?: TaskRow[]; remove?: string[]; baseRevision?: number; as?: string };
export type BoardState = { revision: number; keys: string[] };
export type WriteArgs = { tasks: TaskRow[]; baseRevision: number; as?: string };
export type ToolOutcome = { isError: boolean; result: { content: { type: string; text?: string }[]; details?: unknown } };
export type PatchDeps = {
	readBoard: () => Promise<BoardState>;
	write: (args: WriteArgs) => Promise<ToolOutcome>;
};

export const MAX_STALE_RETRIES = 3;
const STALE_REVISION = "stale tower-do revision";

function isStale(outcome: ToolOutcome): boolean {
	return outcome.isError && outcome.result.content.some((block) => block.text?.includes(STALE_REVISION));
}

export async function applyPatch(params: PatchParams, deps: PatchDeps): Promise<ToolOutcome> {
	const retries = params.baseRevision === undefined ? MAX_STALE_RETRIES : 0;
	for (let attempt = 0; ; attempt++) {
		const board = await deps.readBoard();
		const tasks = mergeTasks(board.keys, params.tasks ?? [], params.remove ?? []);
		const outcome = await deps.write({ tasks, baseRevision: params.baseRevision ?? board.revision, as: params.as });
		if (attempt >= retries || !isStale(outcome)) return outcome;
	}
}

export type BoardTask = { key: string; status: string; owner?: string };

export const SUMMARY_MAX_CHARS = 600;
const STATUS_ORDER = ["in_progress", "pending", "blocked", "completed"];
const DONE_STATUS = "completed";

export function boardSummary(tasks: BoardTask[], maxChars = SUMMARY_MAX_CHARS): string | undefined {
	if (tasks.length === 0) return undefined;
	const counts = new Map<string, number>();
	for (const task of tasks) counts.set(task.status, (counts.get(task.status) ?? 0) + 1);
	const statuses = [...counts.keys()].sort((a, b) => STATUS_ORDER.indexOf(a) - STATUS_ORDER.indexOf(b));
	const head = `Task board: ${statuses.map((status) => `${counts.get(status)} ${status}`).join(", ")}.`;
	const open = tasks
		.filter((task) => task.status !== DONE_STATUS)
		.map((task) => `${task.key} ${task.status}${task.owner ? ` @${task.owner}` : ""}`);
	if (open.length === 0) return head;
	const render = (shown: number) =>
		`${head}\nOpen: ${open.slice(0, shown).join("; ")}${shown < open.length ? `; +${open.length - shown} more` : ""}`;
	let shown = open.length;
	while (shown > 0 && render(shown).length > maxChars) shown--;
	return shown > 0 ? render(shown) : `${head}\n${open.length} open`;
}

const PARAMETERS = Type.Object({
	tasks: Type.Optional(
		Type.Array(Type.Object({ key: Type.String() }, { additionalProperties: true }), {
			description:
				"Rows to add or update, with the same fields as tower_do tasks. Only the fields you send change.",
		}),
	),
	remove: Type.Optional(Type.Array(Type.String(), { description: "Keys of tasks to remove." })),
	baseRevision: Type.Optional(
		Type.Integer({ minimum: 0, description: "Board revision you last observed. Omit it to patch the latest board." }),
	),
	as: Type.Optional(Type.String({ description: "Identity to act as, as in tower_do." })),
});

type BoardModule = {
	TowerBoard: new (file: string) => { fold(): Promise<{ revision: number; tasks: BoardTask[] }> };
};
type TowerDoModule = { boardFileFor(cwd: string): string };

const FIRST_TURN_MESSAGE_TYPE = "tower-do-first-turn-board";

export function isMainSession(env: NodeJS.ProcessEnv): boolean {
	return !env.PI_SUBAGENT_CHILD && !env.PI_HERDSMAN_MAILBOX;
}

export default function (pi: ExtensionAPI) {
	const loadTowerDoModule = async <T>(file: string): Promise<T> => {
		const source = pi.getAllTools().find((tool) => tool.name === "tower_do")?.sourceInfo.path;
		if (source === undefined) throw new Error("tower_do_patch: the tower_do tool is not available");
		return import(pathToFileURL(join(dirname(source), file)).href);
	};
	const loadBoardModule = () => loadTowerDoModule<BoardModule>("board.ts");

	const depsFor = (ctx: ExtensionToolContext): PatchDeps => ({
		async readBoard() {
			const status = await ctx.executeTool("tower_do_status", { view: "mine" });
			const file = (status.result.details as { board?: string } | undefined)?.board;
			if (file === undefined) throw new Error("tower_do_patch: could not find the board file");
			const { TowerBoard } = await loadBoardModule();
			const view = await new TowerBoard(file).fold();
			return { revision: view.revision, keys: view.tasks.map((task) => task.key) };
		},
		write: (args) => ctx.executeTool("tower_do", args),
	});

	const readTasks = async (ctx: ExtensionContext): Promise<BoardTask[]> => {
		try {
			const { boardFileFor } = await loadTowerDoModule<TowerDoModule>("index.ts");
			const { TowerBoard } = await loadBoardModule();
			return (await new TowerBoard(boardFileFor(ctx.cwd)).fold()).tasks;
		} catch (error) {
			if (ctx.hasUI) ctx.ui.notify(`tower_do_patch: could not read the board: ${String(error)}`, "warning");
			return [];
		}
	};

	let firstStartPending = true;
	pi.on("session_start", (event) => {
		firstStartPending = event.reason === "startup" || event.reason === "new";
	});
	pi.on("before_agent_start", async (_event, ctx) => {
		if (!firstStartPending) return;
		firstStartPending = false;
		if (!isMainSession(process.env)) return;
		const content = boardSummary(await readTasks(ctx));
		if (content === undefined) return;
		return { message: { customType: FIRST_TURN_MESSAGE_TYPE, content, display: false } };
	});

	pi.registerTool({
		name: "tower_do_patch",
		label: "Patch task board",
		description:
			"Add, update or remove single tasks on the shared tower-do board without sending the whole board. `tasks` holds only the rows that change and `remove` the keys to delete. Every other task stays as it is.",
		promptSnippet: "Add, update or remove single board tasks without replaying the board",
		promptGuidelines: [
			"Use tower_do_patch to add, update or remove single tasks - send only the rows that change.",
			"Use tower_do only for action gc or a full re-plan.",
		],
		parameters: PARAMETERS,
		executionMode: "sequential",
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const outcome = await applyPatch(params, depsFor(ctx));
			if (outcome.isError) {
				throw new Error(outcome.result.content.map((block) => block.text ?? "").join("\n"));
			}
			return { content: outcome.result.content as { type: "text"; text: string }[], details: outcome.result.details };
		},
	});
}
