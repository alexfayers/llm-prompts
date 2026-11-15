// Lowers the thinking level for turns started by a delegate result message and restores it at the next user prompt.
// Env: TURN_THINKING_WAKE_LEVEL (default low), TURN_THINKING_MAX_CONTEXT (tokens above which a wake-up keeps the level, default 20000)
import type { BeforeAgentStartEvent, ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

type Level = ReturnType<ExtensionAPI["getThinkingLevel"]>;
type Entry = { type: string; message?: { role: string; usage?: { input: number; cacheRead: number; cacheWrite: number } } };

const LEVELS: Level[] = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
const WAKE_TYPES = ["pi-herdsman-agent-result", "pi-herdsman-agent-ask", "pi-context-results"];
const RAISE_MARKER = "think:high";
const DEFAULT_MAX_CONTEXT = 20_000;

const wakeLevel = (): Level => LEVELS.find((level) => level === process.env.TURN_THINKING_WAKE_LEVEL) ?? "low";
const maxContext = (): number => Number(process.env.TURN_THINKING_MAX_CONTEXT) || DEFAULT_MAX_CONTEXT;

/** The prompt tokens of the branch's last assistant request, or 0 before the first one. */
function contextSize(ctx: ExtensionContext): number {
	const usage = [...(ctx.sessionManager.getBranch() as Entry[])].reverse().find((entry) => entry.type === "message" && entry.message?.role === "assistant")?.message?.usage;
	return usage ? usage.input + usage.cacheRead + usage.cacheWrite : 0;
}

/** The level a turn should run at, or undefined to leave it as is. */
export function levelFor(event: BeforeAgentStartEvent, saved: Level | undefined, wake: Level, current: Level): Level | undefined {
	if (event.messageType === "custom") return WAKE_TYPES.includes(event.message.customType) ? wake : undefined;
	const raises = event.prompt.includes(RAISE_MARKER) && LEVELS.indexOf(saved ?? current) < LEVELS.indexOf("high");
	return raises ? "high" : saved;
}

export default function (pi: ExtensionAPI) {
	let saved: Level | undefined;
	let applied: Level | undefined;
	pi.on("before_agent_start", (event, ctx) => {
		const current = pi.getThinkingLevel();
		if (event.messageType === "custom") {
			const level = levelFor(event, undefined, wakeLevel(), current);
			if (!level || LEVELS.indexOf(current) <= LEVELS.indexOf(level) || contextSize(ctx) > maxContext()) return;
			if (applied !== current) saved = undefined;
			saved ??= current;
			pi.setThinkingLevel(level);
			applied = pi.getThinkingLevel();
			return;
		}
		const baseline = applied === current ? saved : undefined;
		const level = levelFor(event, baseline, wakeLevel(), current);
		const raised = level !== undefined && level !== baseline;
		saved = raised ? (baseline ?? current) : undefined;
		if (level) pi.setThinkingLevel(level);
		applied = raised ? pi.getThinkingLevel() : undefined;
	});
}
