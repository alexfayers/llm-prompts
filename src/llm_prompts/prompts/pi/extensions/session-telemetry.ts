// Sends one session's totals (model calls, cost, context, cache reads, compactions, wall time and its split into model calls, tool calls and user waits) to `llm-prompts session-telemetry` when the session ends, and a `pr_opened` event after each `gh pr create` call that returns a PR URL. `llm-prompts session-telemetry` applies the telemetry opt-out and sends only numbers.
import { spawn } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type Clock = { inference?: number; tools: number; userTools: number; prompts: number; last: number; idleSince?: number; prCalls: Set<string> };
type Totals = { model: string; calls: number; cost: number; context: number; peak: number; cacheRead: number; compactions: number; inferenceMs: number; commandMs: number; userMs: number; startedAt: number; clock: Clock };

const TOTALS = Symbol.for("llm-prompts.session-telemetry");
const SESSION_START_ENV = "LLM_PROMPTS_SESSION_START_MS";
const USER_TOOLS = new Set(["ask_user"]);
const USER_INPUT = new Set(["interactive", "rpc"]);
const PR_CREATE = /\bgh\s+pr\s+create\b/;
const PR_URL = /\/pull\/\d+/;
const store = globalThis as { [TOTALS]?: Totals };
const fresh = (now = Date.now()): Totals => ({
	...{ model: "", calls: 0, cost: 0, context: 0, peak: 0, cacheRead: 0, compactions: 0, inferenceMs: 0, commandMs: 0, userMs: 0, startedAt: now },
	clock: { tools: 0, userTools: 0, prompts: 0, last: now, idleSince: now, prCalls: new Set() },
});
const send = (stats: object) =>
	spawn("llm-prompts", ["session-telemetry", JSON.stringify(stats)], { detached: true, stdio: "ignore" })
		.on("error", () => {})
		.unref();
const resultText = (result: unknown) =>
	((result as { content?: { type: string; text?: string }[] } | undefined)?.content ?? []).map((part) => (part.type === "text" ? part.text : "")).join("\n");

export default function (pi: ExtensionAPI) {
	const totals = () => (store[TOTALS] ??= fresh());
	/** Outside idle time, adds the time since the last tool or prompt change to user wait while a user prompt or user tool is open, else to command wait while any tool runs, then applies `change`. */
	const tick = (change: (clock: Clock) => void) => {
		const sums = totals();
		const { clock } = sums;
		const now = Date.now();
		const idle = clock.idleSince !== undefined;
		if (!idle && (clock.prompts || clock.userTools)) sums.userMs += now - clock.last;
		else if (!idle && clock.tools) sums.commandMs += now - clock.last;
		clock.last = now;
		change(clock);
	};
	pi.on("session_start", (event) => {
		if (event.reason !== "reload") store[TOTALS] = fresh();
		process.env[SESSION_START_ENV] = String(totals().startedAt);
	});
	pi.on("input", (event) => {
		const sums = totals();
		if (sums.clock.idleSince !== undefined && USER_INPUT.has(event.source)) sums.userMs += Date.now() - sums.clock.idleSince;
		sums.clock.idleSince = undefined;
	});
	pi.on("agent_start", () => void (totals().clock.idleSince = undefined));
	pi.on("agent_settled", () => void (totals().clock.idleSince = Date.now()));
	pi.on("before_provider_request", () => {
		const { clock } = totals();
		if (clock.idleSince === undefined && !clock.tools && !clock.userTools) clock.inference ??= Date.now();
	});
	pi.on("message_end", (event) => {
		const message = event.message;
		if (message.role !== "assistant") return;
		const sums = totals();
		if (sums.clock.inference !== undefined) sums.inferenceMs += Date.now() - sums.clock.inference;
		sums.clock.inference = undefined;
		if (!message.usage) return;
		const { input, cacheRead, cacheWrite, cost } = message.usage;
		const context = input + cacheRead + cacheWrite;
		Object.assign(sums, { model: `${message.provider}/${message.model}`, calls: sums.calls + 1, cost: sums.cost + (cost?.total ?? 0), context: sums.context + context, peak: Math.max(sums.peak, context), cacheRead: sums.cacheRead + cacheRead });
	});
	pi.on("ui_prompt_start", () => tick((clock) => clock.prompts++));
	pi.on("ui_prompt_end", () => tick((clock) => (clock.prompts = Math.max(0, clock.prompts - 1))));
	pi.on("tool_execution_start", (event) => {
		const user = USER_TOOLS.has(event.toolName);
		if (!event.parentToolCallId) tick((clock) => (user ? clock.userTools++ : clock.tools++));
		const command = (event.args as { command?: unknown } | undefined)?.command;
		if (event.toolName === "bash" && typeof command === "string" && PR_CREATE.test(command)) totals().clock.prCalls.add(event.toolCallId);
	});
	pi.on("tool_execution_end", (event) => {
		const user = USER_TOOLS.has(event.toolName);
		if (!event.parentToolCallId) tick((clock) => (user ? clock.userTools-- : clock.tools--));
		if (totals().clock.prCalls.delete(event.toolCallId) && !event.isError && PR_URL.test(resultText(event.result))) send({ event: "pr_opened" });
	});
	pi.on("session_compact", () => {
		const sums = totals();
		sums.compactions++;
		sums.clock.inference = undefined;
	});
	pi.on("session_shutdown", (event) => {
		if (event.reason === "reload") return;
		const { startedAt, clock, ...sums } = totals();
		store[TOTALS] = undefined;
		if (!sums.calls) return;
		send({ role: process.env.PI_CONTEXT_ROLE ?? "main", ...sums, wallMs: Date.now() - startedAt });
	});
}
