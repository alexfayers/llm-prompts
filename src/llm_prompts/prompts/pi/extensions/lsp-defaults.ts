import { accessSync, constants, readFileSync } from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const LANGUAGES = [{ id: "python", default: "pyright-langserver", fallback: ["ty", "server"] }];

function onPath(binary: string): boolean {
	return (process.env.PATH ?? "").split(path.delimiter).some((dir) => {
		try {
			accessSync(path.join(dir, binary), constants.X_OK);
			return true;
		} catch {
			return false;
		}
	});
}

function projectConfigures(cwd: string, languageId: string): boolean {
	try {
		const config = JSON.parse(readFileSync(path.join(cwd, ".pi-lsp.json"), "utf8"));
		return config?.servers?.[languageId] !== undefined;
	} catch {
		return false;
	}
}

export default function (pi: ExtensionAPI) {
	let applied = false;
	pi.on("session_start", () => {
		applied = false;
	});
	pi.on("before_agent_start", async (_event, ctx) => {
		if (applied || !pi.getCommands().some((command) => command.name === "lsp-config")) return;
		applied = true;
		for (const language of LANGUAGES) {
			if (projectConfigures(ctx.cwd, language.id) || onPath(language.default) || !onPath(language.fallback[0])) continue;
			await pi.sendUserMessage(`/lsp-config ${language.id} ${language.fallback.join(" ")}`, { expandPromptTemplates: true });
		}
	});
}
