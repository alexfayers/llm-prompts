// Sends one session's totals (model calls, cost, context, cache reads, compactions, wall time) to `llm-prompts session-telemetry` when the session ends, which applies the telemetry opt-out and sends only numbers.
import { spawn } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type Totals = { model: string; calls: number; cost: number; context: number; peak: number; cacheRead: number; compactions: number; startedAt: number };

const TOTALS = Symbol.for("llm-prompts.session-telemetry");
const store = globalThis as { [TOTALS]?: Totals };
const fresh = (): Totals => ({ model: "", calls: 0, cost: 0, context: 0, peak: 0, cacheRead: 0, compactions: 0, startedAt: Date.now() });

export default function (pi: ExtensionAPI) {
	const totals = () => (store[TOTALS] ??= fresh());
	pi.on("session_start", (event) => {
		if (event.reason !== "reload") store[TOTALS] = fresh();
	});
	pi.on("message_end", (event) => {
		const message = event.message;
		if (message.role !== "assistant" || !message.usage) return;
		const { input, cacheRead, cacheWrite, cost } = message.usage;
		const context = input + cacheRead + cacheWrite;
		const sums = totals();
		Object.assign(sums, { model: `${message.provider}/${message.model}`, calls: sums.calls + 1, cost: sums.cost + (cost?.total ?? 0), context: sums.context + context, peak: Math.max(sums.peak, context), cacheRead: sums.cacheRead + cacheRead });
	});
	pi.on("session_compact", () => void totals().compactions++);
	pi.on("session_shutdown", (event) => {
		if (event.reason === "reload") return;
		const { startedAt, ...sums } = totals();
		store[TOTALS] = undefined;
		if (!sums.calls) return;
		const stats = { role: process.env.PI_CONTEXT_ROLE ?? "main", ...sums, wallMs: Date.now() - startedAt };
		spawn("llm-prompts", ["session-telemetry", JSON.stringify(stats)], { detached: true, stdio: "ignore" })
			.on("error", () => {})
			.unref();
	});
}
