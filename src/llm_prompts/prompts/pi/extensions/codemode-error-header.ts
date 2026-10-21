// Puts the first error line of a failed codemode script into the result header and makes reading a missing tool give undefined.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const FAILED_HEADER = "Script failed";
const ERROR_MARKER = "Script error:";
const OBJECT_PRINTED = "[object Object]";
const HINTS = [
	{ error: /invalid redefinition of parameter name/, hint: "Hint: `tools` is reserved in codemode scripts - do not declare a variable named `tools`." },
	{ error: /^TypeError: .*of undefined/, code: /\.structuredContent\b/, hint: "Hint: this result is text: read r.content[0].text" },
	{ error: /^TypeError: .*not a function/, code: /\btools\.mcp__/, hint: "Hint: an MCP result is an object, not a string: read its fields, or JSON.stringify it first" },
	{ error: /MCP request timed out/, hint: "Hint: MCP call timed out: retry it inside this script (loop with a short backoff), not in a new turn" },
];

const OPTIONS_PREFIX = "// @options:";
const DIRECTIVE_PROLOGUE = /^(?:\s*(?:\/\/[^\n]*\n\s*)*(?:"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')[ \t]*;)*/;
const SHADOW_TOOLS = ';tools=new Proxy(tools,{get:(t,p)=>typeof p!=="string"||p in t?t[p]:void 0});';

type Block = { type: string; text?: string };
type ToolInfo = { name: string; parameters?: { properties?: Record<string, unknown>; required?: string[] } };

export function prependToScript(code: string, snippet: string): string {
	const lines = code.split("\n");
	const bodyStart = lines[0].trimStart().startsWith(OPTIONS_PREFIX) ? lines[0].length + 1 : 0;
	const misplacedOptions = lines.slice(1).some((line) => line.trimStart().startsWith(OPTIONS_PREFIX));
	if (misplacedOptions || bodyStart >= code.length) return code;
	const insertAt = bodyStart + (DIRECTIVE_PROLOGUE.exec(code.slice(bodyStart))?.[0].length ?? 0);
	return code.slice(0, insertAt) + snippet + code.slice(insertAt);
}

function firstErrorLine(content: Block[]): string | undefined {
	const lines = content.flatMap((block) => (block.type === "text" ? (block.text ?? "").split("\n") : []));
	const marker = lines.lastIndexOf(ERROR_MARKER);
	return marker < 0 ? undefined : lines.slice(marker + 1).find((line) => line.trim() !== "")?.trim();
}

function hintsFor(error: string, code: unknown, tools: ToolInfo[]): string[] {
	const name = /Validation failed for tool "([^"]+)"/.exec(error)?.[1];
	const { properties = {}, required = [] } = tools.find((tool) => tool.name === name)?.parameters ?? {};
	const args = Object.keys(properties);
	const argsHint = args.length > 0 ? [`Hint: ${name!.replace(/^mcp__.+?__/, "")} args: ${args.join(", ")}${required.length > 0 ? ` (required: ${required.join(", ")})` : ""}`] : [];
	const matching = HINTS.filter((row) => row.error.test(error) && (!row.code || (typeof code === "string" && row.code.test(code))));
	return [...argsHint, ...matching.map((row) => row.hint)];
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", (event) => {
		if (event.toolName !== "codemode" || typeof event.input.code !== "string") return;
		event.input.code = prependToScript(event.input.code, SHADOW_TOOLS);
	});
	pi.on("tool_result", (event) => {
		if (event.toolName !== "codemode") return;
		const [header, ...rest] = event.content as Block[];
		const [title, ...headerRest] = (header?.text ?? "").split("\n");
		const error = event.isError ? firstErrorLine(event.content as Block[]) : undefined;
		const printed = !event.isError && title === "Script completed" && rest.some((block) => block.text?.includes(OBJECT_PRINTED));
		const lines = error && title === FAILED_HEADER ? [`${title}: ${error}`, ...hintsFor(error, event.input.code, pi.getAllTools() as ToolInfo[])] : printed ? [title, `Hint: a value printed as ${OBJECT_PRINTED}: read its fields or JSON.stringify it`] : undefined;
		if (header?.type !== "text" || !lines) return;
		return { content: [{ ...header, text: [...lines, ...headerRest].join("\n") }, ...rest] as typeof event.content };
	});
}
