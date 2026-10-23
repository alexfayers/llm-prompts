import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { after, test } from "node:test";
import { loadExtension } from "./helpers.ts";

const work = fs.realpathSync(fs.mkdtempSync(join(os.tmpdir(), "net-guard-")));
const agentDir = join(work, "agent");
fs.mkdirSync(join(agentDir, "extensions"), { recursive: true });
const ext = await loadExtension("net-guard", { agentDir });
after(() => fs.rmSync(work, { recursive: true }));

async function blockedCall(mode: string) {
	const plugin = `probe-${mode}`;
	const file = join(agentDir, "extensions", `${plugin}.mjs`);
	fs.writeFileSync(file, "export const call = () => fetch('http://blocked.example/')\n");
	const ctx = ext.makeCtx({ mode, cwd: work });
	await ext.fire("session_start", {}, ctx);
	const probe = await import(pathToFileURL(file).href);
	const error = await probe.call().then(() => null, (reason: Error) => String(reason.message));
	const log = join(agentDir, "net-guard.log");
	return { plugin, error, notices: ctx.notices, logged: fs.existsSync(log) && fs.readFileSync(log, "utf8").includes(`"plugin":"${plugin}"`) };
}

test("a non-local call from an extension is blocked and logged in every mode, and noticed only in the terminal UI", async () => {
	for (const [mode, notified] of [["tui", true], ["rpc", false], ["json", false], ["print", false]] as const) {
		const { plugin, error, logged, notices } = await blockedCall(mode);
		assert.ok(error?.includes(`blocked fetch to blocked.example from plugin ${plugin}`));
		assert.ok(logged);
		assert.deepEqual(notices.map(([, level]) => level), notified ? ["warning"] : []);
	}
});

test("a call from pi itself is not blocked when pi is listed as a package", async () => {
	const core = "@earendil-works/pi-coding-agent";
	const file = join(work, "node_modules", core, "probe.mjs");
	fs.mkdirSync(join(work, "node_modules", core), { recursive: true });
	fs.writeFileSync(file, "export const call = () => fetch('http://pi-core.invalid/')\n");
	fs.writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ packages: [`npm:${core}@1.0.0`] }));
	await ext.fire("session_start", {}, ext.makeCtx({ mode: "rpc", cwd: work }));
	const probe = await import(pathToFileURL(file).href);
	const error = await probe.call().then(() => "", (reason: Error) => String(reason.message));
	assert.ok(!error.includes("net-guard"));
});
