// Sends only the first pi-herdsman delegation-guidance message to the model.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const GUIDANCE_TYPE = "pi-herdsman-delegation-guidance";

type Message = { role: string; customType?: string };

export function dropRepeatedGuidance(messages: Message[]): Message[] | undefined {
	let seen = false;
	const kept = messages.filter((message) => {
		if (message.role !== "custom" || message.customType !== GUIDANCE_TYPE) return true;
		const repeated = seen;
		seen = true;
		return !repeated;
	});
	return kept.length === messages.length ? undefined : kept;
}

export default function (pi: ExtensionAPI) {
	pi.on("context_with_system", (event) => {
		const messages = dropRepeatedGuidance(event.messages as Message[]);
		return messages && { messages: messages as typeof event.messages };
	});
}
