// Keeps the prompt cache warm while a tower-do task this session owns is in progress or a fork run is live, for up to 2 hours after the last request.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { forkRegistry } from "./pi-context/registry.ts";
import { foldBoard, loadTowerDo } from "./tower-do-patch.ts";

const MAX_IDLE_MS = 2 * 60 * 60 * 1000;
const liveForkCount = (): number => forkRegistry()?.live().length ?? 0;

export default function (pi: ExtensionAPI) {
	let lastRequestAt = Date.now();
	const markRequest = () => {
		lastRequestAt = Date.now();
	};
	pi.on("session_start", markRequest);
	pi.on("turn_end", markRequest);

	pi.on("cache_warming_decision", async (_event, ctx) => {
		if (Date.now() - lastRequestAt >= MAX_IDLE_MS) return { action: "stop" };
		if (liveForkCount()) return { action: "warm" };
		try {
			const { BoardCache } = await loadTowerDo<{ BoardCache: new () => { entryFor(cwd: string): { config: { identity?: string } } } }>("paths.ts");
			const { config } = new BoardCache().entryFor(ctx.cwd);
			const identity = config.identity?.trim() || pi.getSessionName()?.trim() || ctx.sessionManager.getSessionId() || "main";
			const view = await foldBoard(ctx.cwd);
			return { action: view.tasks.some((task) => task.status === "in_progress" && task.owner === identity) ? "warm" : "stop" };
		} catch {
			return undefined;
		}
	});
}
