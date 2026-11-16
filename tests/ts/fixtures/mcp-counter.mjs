// Stands in for a stdio MCP server that has one tool, `ping`, and appends a line to MCP_SPAWN_LOG each time it starts.
import { appendFileSync } from "node:fs";
import { createInterface } from "node:readline";

appendFileSync(process.env.MCP_SPAWN_LOG, `spawn ${process.pid}\n`);
const out = (record) => process.stdout.write(`${JSON.stringify(record)}\n`);
const results = {
	initialize: { protocolVersion: "2025-03-26", capabilities: { tools: {} }, serverInfo: { name: "counter", version: "1" } },
	"tools/list": { tools: [{ name: "ping", description: "Returns pong", inputSchema: { type: "object", properties: {} } }] },
	"tools/call": { content: [{ type: "text", text: "pong" }] },
};

for await (const line of createInterface({ input: process.stdin })) {
	const request = JSON.parse(line);
	if (request.id !== undefined && results[request.method]) out({ jsonrpc: "2.0", id: request.id, result: results[request.method] });
}
