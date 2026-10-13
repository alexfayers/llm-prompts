// Falls back to the ty or ruff language server for Python when pyright is missing.
import { accessSync, constants, readFileSync } from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const LANGUAGES = [
	{ id: "python", default: "pyright-langserver", fallbacks: [["ty", "server"], ["ruff", "server"]] },
	{ id: "typescript", default: "typescript-language-server", fallbacks: [] },
	{ id: "typescriptreact", default: "typescript-language-server", fallbacks: [] },
	{ id: "javascript", default: "typescript-language-server", fallbacks: [] },
	{ id: "javascriptreact", default: "typescript-language-server", fallbacks: [] },
];

type ProjectConfig = { servers?: Record<string, { command?: string }> };

function executable(file: string): boolean {
	try {
		accessSync(file, constants.X_OK);
		return true;
	} catch {
		return false;
	}
}

function installed(command: string, cwd: string): boolean {
	if (command.includes("/")) return executable(path.resolve(cwd, command));
	return (process.env.PATH ?? "").split(path.delimiter).some((dir) => executable(path.join(dir, command)));
}

function projectConfig(cwd: string): ProjectConfig | undefined {
	try {
		return JSON.parse(readFileSync(path.join(cwd, ".pi-lsp.json"), "utf8"));
	} catch {
		return undefined;
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
		const servers = projectConfig(ctx.cwd)?.servers;
		for (const language of LANGUAGES) {
			const fallback = language.fallbacks.find((command) => installed(command[0], ctx.cwd));
			if (servers?.[language.id] !== undefined || installed(language.default, ctx.cwd) || !fallback) continue;
			await pi.sendUserMessage(`/lsp-config ${language.id} ${fallback.join(" ")}`, { expandPromptTemplates: true });
		}
	});
}
