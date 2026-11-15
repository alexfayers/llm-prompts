// Stands in for `pi --mode rpc` as a fork child: the task text picks the reply, and STUB_INSPECT reports how the child was started.
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import net from "node:net";
import { dirname } from "node:path";
import { createInterface } from "node:readline";

const out = (record) => process.stdout.write(`${JSON.stringify(record)}\n`);
const usage = (cacheRead) => ({ input: 10, output: 5, cacheRead, cacheWrite: 1 });
const flag = (name) => process.argv[process.argv.indexOf(name) + 1];
const seed = process.argv.includes("--session") ? flag("--session") : undefined;
const card = process.argv.includes("--append-system-prompt") ? flag("--append-system-prompt") : undefined;
const handshake = process.env.PI_CONTEXT_CHILD;
if (process.argv.includes("--session-dir")) mkdirSync(flag("--session-dir"), { recursive: true }), writeFileSync(`${flag("--session-dir")}/${process.pid}.jsonl`, "");
let reply = "";
let body = "";

/** Sends the bridge one prefix report and one MCP call, and returns the call's reply text. */
function callBridge(socketPath) {
	return new Promise((resolve, reject) => {
		const socket = net.connect(socketPath, () => {
			socket.write(`${JSON.stringify({ prefix: process.env.STUB_PREFIX })}\n`);
			socket.write(`${JSON.stringify({ id: 1, tool: "mcp__semble__search", args: { query: "q" } })}\n`);
		});
		socket.setEncoding("utf8");
		socket.once("data", (data) => {
			socket.destroy();
			resolve(JSON.parse(data).result.content[0].text);
		});
		socket.once("error", reject);
	});
}

async function replyTo(text) {
	if (text.includes("STUB_BRIDGE")) return `echo: ${await callBridge(JSON.parse(readFileSync(handshake, "utf8")).bridge.socket)}`;
	if (text.includes("STUB_CRASH")) process.exit(3);
	if (text.includes("STUB_HANG")) await new Promise(() => undefined);
	const gate = /STUB_GATE:(\S+)/.exec(text)?.[1];
	if (gate) {
		while (!existsSync(gate)) await new Promise((resolve) => setTimeout(resolve, 20));
		return `OUTCOME done ref:rc-fork-${gate.split("/").pop()}`;
	}
	if (text.includes("STUB_REPORT")) return "OUTCOME done ref:rc-fork-x\nbody line";
	if (text.includes("STUB_WRITE")) {
		const { worktree } = JSON.parse(readFileSync(handshake, "utf8"));
		body = `${readFileSync(handshake, "utf8")}\n${text}\ncwd ${process.cwd()}`;
		writeFileSync(`${worktree}/written-${process.pid}.txt`, "from the fork");
		execFileSync("git", ["-C", worktree, "add", "."]);
		execFileSync("git", ["-C", worktree, "commit", "-m", "write"]);
		return `OUTCOME done ref:rc-fork-w\n${body}`;
	}
	if (!text.includes("STUB_INSPECT")) return `echo: ${text}`;
	return JSON.stringify({
		socketExists: existsSync(JSON.parse(readFileSync(handshake, "utf8")).bridge?.socket ?? ""),
		args: process.argv.slice(2),
		cwd: process.cwd(),
		handshake: JSON.parse(readFileSync(handshake, "utf8")),
		handshakeMode: statSync(handshake).mode & 0o777,
		seed: seed && readFileSync(seed, "utf8").trim().split("\n").map((line) => JSON.parse(line)),
		card: card && readFileSync(card, "utf8"),
		prompt: text,
		env: { role: process.env.PI_CONTEXT_ROLE, runId: process.env.PI_CONTEXT_RUN_ID },
	});
}

for await (const line of createInterface({ input: process.stdin })) {
	const command = JSON.parse(line);
	const respond = (data) => out({ id: command.id, type: "response", command: command.type, success: true, data });
	if (command.type === "prompt") {
		const bridged = JSON.parse(readFileSync(handshake, "utf8")).bridge;
		if (process.env.STUB_PREFIX && !bridged) writeFileSync(`${dirname(handshake)}/prefix`, process.env.STUB_PREFIX);
		reply = await replyTo(command.message);
		respond({ disposition: "started" });
		out({ type: "message_end", message: { role: "assistant", usage: usage(100) } });
		out({ type: "message_end", message: { role: "assistant", usage: usage(200) } });
		out({ type: "agent_settled", aborted: false });
	} else if (command.type === "get_last_assistant_text") respond({ text: reply });
}
