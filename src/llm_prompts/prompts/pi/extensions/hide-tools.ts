// Hides rarely used LSP and AST tools from the model; lsp_diagnostics stays.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const HIDDEN = new Set([
	"lsp_hover", "lsp_definition", "lsp_references", "lsp_symbols", "lsp_rename",
	"lsp_code_actions", "lsp_completions", "code_overview", "ast_search", "code_rewrite",
]);

export default function (pi: ExtensionAPI) {
	pi.on("session_start", () => {
		pi.setActiveTools(pi.getActiveTools().filter((name) => !HIDDEN.has(name)));
	});
}
