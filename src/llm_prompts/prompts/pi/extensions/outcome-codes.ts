// Shows the model only the header and OUTCOME line of a coded pi-herdsman agent result.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const RESULT_TYPE = "pi-herdsman-agent-result";
const OUTCOME = /^OUTCOME (done|blocked-on-user|failed|found-it)( notify)? ref:\S*$/;
const HEADER = /^(Agent result ·|Result ref:|To continue this session|Forwardable result evidence:|Continuation |Result file could not be saved)/;
const KEPT_ANYWHERE = /^(ASK:|DENIED: ")/;
const STATUS = /^Delegation status:/;
const MAX_FOUND_LINE = 200;

export function projectResult(text: string): string {
	const lines = text.split("\n");
	const at = lines.findIndex((line) => OUTCOME.test(line));
	if (at < 0) return text;
	const foundAt = lines[at].includes(" found-it ") ? lines.findIndex((line, i) => i > at && line.trim()) : -1;
	return lines
		.filter((line, i) => i === at || KEPT_ANYWHERE.test(line) || (i < at ? HEADER.test(line) : STATUS.test(line) || (i === foundAt && line.length <= MAX_FOUND_LINE)))
		.join("\n");
}

type Message = { role: string; customType?: string; content?: unknown };

export default function (pi: ExtensionAPI) {
	pi.on("context_with_system", (event) => {
		let changed = false;
		const messages = (event.messages as Message[]).map((message) => {
			if (message.role !== "custom" || message.customType !== RESULT_TYPE || typeof message.content !== "string") return message;
			const content = projectResult(message.content);
			if (content === message.content) return message;
			changed = true;
			return { ...message, content };
		});
		return changed ? { messages: messages as typeof event.messages } : undefined;
	});
}
