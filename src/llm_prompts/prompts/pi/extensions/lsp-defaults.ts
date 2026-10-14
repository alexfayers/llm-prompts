// Uses installed ty or ruff when pyright is absent and no Python server is configured.
// Config: .pi-lsp.json keys servers
import { accessSync, constants, readFileSync } from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const LANGUAGES = [{ id: "python", default: "pyright-langserver", fallbacks: [["ty", "server"], ["ruff", "server"]] }];

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
			const fallback = language.fallbacks.find((command) => onPath(command[0]));
			if (projectConfigures(ctx.cwd, language.id) || onPath(language.default) || !fallback) continue;
			await pi.sendUserMessage(`/lsp-config ${language.id} ${fallback.join(" ")}`, { expandPromptTemplates: true });
		}
	});
}
