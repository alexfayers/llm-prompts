// Shows the Herdr "?" state while a permission prompt waits for the user.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const BLOCKED_LABEL = "Permission prompt";

type PromptEvent = { requestId: string };

export default function (pi: ExtensionAPI) {
	const waiting = new Set<string>();
	let tui = false;
	pi.on("session_start", (_event, ctx) => {
		tui = ctx.mode === "tui";
	});
	pi.events.on("permissions:ui_prompt", (data) => {
		if (!tui) return;
		const { requestId } = data as PromptEvent;
		if (waiting.has(requestId)) return;
		waiting.add(requestId);
		pi.events.emit("herdr:blocked", { active: true, label: BLOCKED_LABEL });
	});
	pi.events.on("permissions:decision", (data) => {
		if (waiting.delete((data as PromptEvent).requestId)) pi.events.emit("herdr:blocked", { active: false });
	});
}
