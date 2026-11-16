// Stands in for `pi --mode rpc`: the prompt text picks the behaviour.
const out = (record) => process.stdout.write(`${JSON.stringify(record)}\n`);
const usage = (cacheRead) => ({ input: 10, output: 5, cacheRead, cacheWrite: 1 });
const respond = (cmd, data) => out({ id: cmd.id, type: "response", command: cmd.type, success: true, data });
let lastText = null;
let pendingUi = null;

function runTurn(text) {
	lastText = `echo: ${text}`;
	const assistant = (cacheRead) => out({ type: "message_end", message: { role: "assistant", usage: usage(cacheRead) } });
	assistant(100);
	assistant(200);
	out({ type: "agent_settled", aborted: false });
}

function onPrompt(cmd) {
	const text = cmd.message;
	if (text === "crash") process.exit(3);
	respond(cmd, { disposition: text === "handled" ? "handled" : "started" });
	if (text === "handled") lastText = "stale";
	if (text === "handled" || text === "hang") return;
	if (text === "garbage") {
		process.stdout.write("not json\n{\"type\":\n");
		out({ type: "message_end", message: { role: "user", content: "x" } });
	}
	if (text === "ui") {
		pendingUi = text;
		out({ type: "extension_ui_request", id: "ui-1", method: "confirm", title: "ok?" });
		return;
	}
	if (text === "notify") out({ type: "extension_ui_request", id: "ui-n", method: "notify", message: "hi" });
	runTurn(text);
}

function onLine(line) {
	const cmd = JSON.parse(line);
	if (cmd.type === "prompt") onPrompt(cmd);
	else if (cmd.type === "extension_ui_response") {
		if (pendingUi) runTurn(`ui:${JSON.stringify({ confirmed: cmd.confirmed, cancelled: cmd.cancelled })}`);
		pendingUi = null;
	} else if (cmd.type === "get_last_assistant_text") respond(cmd, { text: lastText });
	else if (cmd.type === "abort") {
		respond(cmd);
		out({ type: "agent_settled", aborted: true });
	}
}

let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
	buffer += chunk;
	for (let at = buffer.indexOf("\n"); at >= 0; at = buffer.indexOf("\n")) {
		const line = buffer.slice(0, at);
		buffer = buffer.slice(at + 1);
		if (line) onLine(line);
	}
});
if (process.env.STUB_IGNORE_TERM) process.on("SIGTERM", () => undefined);
if (process.env.STUB_IGNORE_EOF) setInterval(() => undefined, 1000);
else process.stdin.on("end", () => process.exit(0));
