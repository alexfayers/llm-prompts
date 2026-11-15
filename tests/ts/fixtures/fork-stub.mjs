// Stands in for `pi --mode rpc` as a fork child: the task text picks the reply, and STUB_INSPECT reports how the child was started.
import { readFileSync, statSync } from "node:fs";
import { createInterface } from "node:readline";

const out = (record) => process.stdout.write(`${JSON.stringify(record)}\n`);
const usage = (cacheRead) => ({ input: 10, output: 5, cacheRead, cacheWrite: 1 });
const seed = process.argv[process.argv.indexOf("--session") + 1];
const handshake = process.env.PI_CONTEXT_CHILD;
let reply = "";

function replyTo(text) {
	if (text.includes("STUB_CRASH")) process.exit(3);
	if (text.includes("STUB_REPORT")) return "OUTCOME done ref:rc-fork-x\nbody line";
	if (!text.includes("STUB_INSPECT")) return `echo: ${text}`;
	return JSON.stringify({
		args: process.argv.slice(2),
		cwd: process.cwd(),
		handshake: JSON.parse(readFileSync(handshake, "utf8")),
		handshakeMode: statSync(handshake).mode & 0o777,
		seed: readFileSync(seed, "utf8").trim().split("\n").map((line) => JSON.parse(line)),
		prompt: text,
	});
}

for await (const line of createInterface({ input: process.stdin })) {
	const command = JSON.parse(line);
	const respond = (data) => out({ id: command.id, type: "response", command: command.type, success: true, data });
	if (command.type === "prompt") {
		reply = replyTo(command.message);
		respond({ disposition: "started" });
		out({ type: "message_end", message: { role: "assistant", usage: usage(100) } });
		out({ type: "message_end", message: { role: "assistant", usage: usage(200) } });
		out({ type: "agent_settled", aborted: false });
	} else if (command.type === "get_last_assistant_text") respond({ text: reply });
}
