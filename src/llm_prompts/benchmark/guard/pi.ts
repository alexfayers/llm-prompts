// Blocks pi bash tool calls that the benchmark guard command rejects, failing closed on any error.
// Env: PI_CODING_AGENT_DIR (holds bench-guard.json = {"argv": [...]})
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const FALLBACK_REASON = "Blocked by benchmark guard";

function block(reason: string): { block: true; reason: string } {
	return { block: true, reason };
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", (event) => {
		if (event.toolName !== "bash") return undefined;
		let argv: string[];
		try {
			const config = JSON.parse(fs.readFileSync(path.join(process.env.PI_CODING_AGENT_DIR ?? "", "bench-guard.json"), "utf8"));
			if (!Array.isArray(config.argv) || config.argv.length === 0) return block("Benchmark guard config has no argv.");
			argv = config.argv.map(String);
		} catch {
			return block("Cannot read the benchmark guard config.");
		}
		const input = JSON.stringify({ tool_name: "Bash", tool_input: event.input });
		const result = spawnSync(argv[0], argv.slice(1), { input, encoding: "utf8" });
		if (result.status === 0) return undefined;
		return block(result.stderr?.trim() || result.error?.message || FALLBACK_REASON);
	});
}
