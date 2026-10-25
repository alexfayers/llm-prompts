// Hides rarely used LSP and AST tools from the model, and the task board and process tools in non-interactive sessions; lsp_diagnostics stays.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const HIDDEN = new Set([
	"lsp_hover", "lsp_definition", "lsp_references", "lsp_symbols", "lsp_rename",
	"lsp_code_actions", "lsp_completions", "code_overview", "ast_search", "code_rewrite",
]);
const HEADLESS_HIDDEN = ["tower_do", "tower_do_status", "tower_do_talk", "tower_do_patch", "process"];
const ENTRY_TYPE = "hide-tools";

export default function (pi: ExtensionAPI) {
	pi.on("session_start", (_event, ctx) => {
		const active = pi.getActiveTools();
		const saved = ctx.sessionManager
			.getBranch()
			.flatMap((entry) => (entry.type === "custom" && entry.customType === ENTRY_TYPE ? [entry.data as { hidden: string[] }] : []))
			.pop();
		const extra = saved?.hidden ?? (ctx.mode === "tui" ? [] : HEADLESS_HIDDEN.filter((name) => active.includes(name)));
		if (!saved) pi.appendEntry(ENTRY_TYPE, { hidden: extra });
		pi.setActiveTools(active.filter((name) => !HIDDEN.has(name) && !extra.includes(name)));
	});
}
