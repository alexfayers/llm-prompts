// Adds the sleep tool, which codemode scripts await to pause between calls.
import { setTimeout } from "node:timers/promises";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const MAX_SLEEP_MS = 600_000;

const PARAMETERS = Type.Object({
	ms: Type.Integer({
		minimum: 0,
		maximum: MAX_SLEEP_MS,
		description: "Milliseconds to wait.",
	}),
});

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "sleep",
		label: "Sleep",
		description: `Wait \`ms\` milliseconds (up to ${MAX_SLEEP_MS}). For codemode scripts that poll a changing result, or use \`waitUntil(() => check, { intervalMs, timeoutMs })\`.`,
		parameters: PARAMETERS,
		exposure: "codemode",
		async execute(_toolCallId, params, signal) {
			await setTimeout(params.ms, undefined, { signal });
			return { content: [{ type: "text", text: `Slept ${params.ms} ms` }], details: undefined };
		},
	});
}
