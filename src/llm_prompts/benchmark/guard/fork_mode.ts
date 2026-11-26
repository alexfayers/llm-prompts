// Runs every plain fork call of a benchmark run warm or cold, so the agent's own choice does not decide the side. A cold fork runs on the same model and thinking level as main.
// Env: PI_CODING_AGENT_DIR (holds bench-fork-mode.json = {"warm": boolean})
import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", (event, ctx) => {
		if (event.toolName !== "fork" || ["from", "shared", "tasks"].some((key) => event.input[key] !== undefined)) return undefined;
		let warm: unknown;
		try {
			warm = JSON.parse(fs.readFileSync(path.join(process.env.PI_CODING_AGENT_DIR ?? "", "bench-fork-mode.json"), "utf8")).warm;
		} catch {
			return { block: true, reason: "Cannot read the benchmark fork mode config." };
		}
		if (typeof warm !== "boolean") return { block: true, reason: "The benchmark fork mode config has no warm flag." };
		if (warm) delete event.input.model;
		else if (ctx.model) event.input.model = `${ctx.model.provider}/${ctx.model.id}:${pi.getThinkingLevel()}`;
		else return { block: true, reason: "Cannot run a cold fork without a model." };
		return undefined;
	});
}
