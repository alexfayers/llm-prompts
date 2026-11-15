// Answers /status, /board and the bare words status, board and asks from git, the task board and the pinned asks without a model call.
// Commands: /status [explain], /board
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { openAsks } from "./pending-asks.ts";
import { loadTowerDo } from "./tower-do-patch.ts";

export type Task = { key: string; subject?: string; status: string; owner?: string };

const UNAVAILABLE = "unavailable";
const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

export function formatGit(porcelain: string | undefined): string {
	if (porcelain === undefined) return UNAVAILABLE;
	const [header = "", ...changes] = porcelain.split("\n").filter(Boolean);
	const [, branch, tracking] = /^## (.+?)(?:\.\.\.\S+)?(?: \[(.+)\])?$/.exec(header) ?? [];
	return `${branch ?? header}${tracking ? ` [${tracking}]` : ""}, ${changes.length} dirty`;
}

export function formatStatus(porcelain: string | undefined, tasks: Task[] | undefined, asks: number): string {
	const inStatus = (status: string) => tasks?.filter((task) => task.status === status).length ?? 0;
	const board = tasks ? `${inStatus("in_progress")} in progress, ${inStatus("blocked")} blocked` : UNAVAILABLE;
	return [`git: ${formatGit(porcelain)}`, `board: ${board}`, `asks: ${count(asks, "pending ask")}`].join("\n");
}

export function formatBoard(tasks: Task[] | undefined): string {
	if (!tasks) return `board: ${UNAVAILABLE}`;
	const open = tasks.filter((task) => task.status === "in_progress" || task.status === "blocked");
	return open.map((task) => `[${task.status}] ${task.key}: ${task.subject ?? ""} @${task.owner ?? "-"}`).join("\n") || "no in-progress or blocked tasks";
}

async function readGit(pi: ExtensionAPI): Promise<string | undefined> {
	try {
		const result = await pi.exec("git", ["status", "--short", "--branch"]);
		return result.code === 0 ? result.stdout : undefined;
	} catch {
		return undefined;
	}
}

async function readBoard(cwd: string): Promise<Task[] | undefined> {
	try {
		const { boardFileFor } = await loadTowerDo<{ boardFileFor(cwd: string): string }>("paths.ts");
		const { TowerBoard } = await loadTowerDo<{ TowerBoard: new (file: string) => { fold(): Promise<{ tasks: Task[] }> } }>("board.ts");
		return (await new TowerBoard(boardFileFor(cwd)).fold()).tasks;
	} catch {
		return undefined;
	}
}

export default function (pi: ExtensionAPI) {
	const asks = (ctx: ExtensionContext) => openAsks(ctx.sessionManager.getBranch() as never);
	const views: Record<string, (ctx: ExtensionContext) => Promise<string>> = {
		status: async (ctx) => formatStatus(await readGit(pi), await readBoard(ctx.cwd), asks(ctx).length),
		board: async (ctx) => formatBoard(await readBoard(ctx.cwd)),
		asks: async (ctx) => asks(ctx).map(({ id, text }) => `${id}: ${text}`).join("\n") || "no pending asks",
	};

	pi.registerCommand("status", {
		description: "Show git, board and pending asks without a model call, or explain them with `explain`",
		handler: async (args, ctx) => {
			const text = await views.status(ctx);
			if (args.trim() === "explain") pi.sendUserMessage(`Explain this status briefly:\n${text}`);
			else ctx.ui.notify(text, "info");
		},
	});
	pi.registerCommand("board", { description: "List the in-progress and blocked board tasks without a model call", handler: async (_args, ctx) => ctx.ui.notify(await views.board(ctx), "info") });

	pi.on("input", async (event, ctx) => {
		const name = /^(status|board|asks)\??$/i.exec(event.text.trim())?.[1].toLowerCase();
		if (!name || event.source === "extension" || !ctx.hasUI) return undefined;
		ctx.ui.notify(await views[name](ctx), "info");
		return { action: "handled" as const };
	});
}
