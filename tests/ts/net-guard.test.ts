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
const configFile = join(agentDir, "net-guard.json");
fs.writeFileSync(configFile, "{}");
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

test("a call from pi itself is not blocked when pi is listed as a package, but an extension calling through pi is", async () => {
	const core = "@earendil-works/pi-coding-agent";
	const coreFile = join(work, "node_modules", core, "probe.mjs");
	const extensionFile = join(agentDir, "extensions", "probe-via-core.mjs");
	fs.mkdirSync(join(work, "node_modules", core), { recursive: true });
	fs.writeFileSync(coreFile, "export const call = () => fetch('http://pi-core.invalid/')\n");
	fs.writeFileSync(extensionFile, `import { call as core } from ${JSON.stringify(pathToFileURL(coreFile).href)}\nexport const call = () => core()\n`);
	fs.writeFileSync(join(agentDir, "settings.json"), JSON.stringify({ packages: [`npm:${core}@1.0.0`] }));
	await ext.fire("session_start", {}, ext.makeCtx({ mode: "rpc", cwd: work }));
	const messageOf = (probe: { call: () => Promise<unknown> }) => probe.call().then(() => "", (reason: Error) => String(reason.message));
	assert.ok(!(await messageOf(await import(pathToFileURL(coreFile).href))).includes("net-guard"));
	assert.ok((await messageOf(await import(pathToFileURL(extensionFile).href))).includes("from plugin probe-via-core"));
});

async function messageFromExtension(plugin: string, ctx = ext.makeCtx({ mode: "rpc", cwd: work })) {
	const file = join(agentDir, "extensions", `${plugin}.mjs`);
	fs.writeFileSync(file, "export const call = () => fetch('http://allow-probe.invalid/')\n");
	await ext.fire("session_start", {}, ctx);
	const probe = await import(pathToFileURL(file).href);
	return probe.call().then(() => "", (reason: Error) => String(reason.message));
}

test("config entries are allowed", async () => {
	fs.writeFileSync(configFile, JSON.stringify({ allow: ["probe-extra"] }));
	assert.ok(!(await messageFromExtension("probe-extra")).includes("net-guard"));
	assert.ok((await messageFromExtension("probe-other")).includes("blocked fetch"));
});

test("a missing or unparsable config warns in the terminal UI and the log, and nothing extra is allowed", async () => {
	for (const [content, problem] of [[undefined, "missing"], ["{ not json", "cannot be parsed"]] as const) {
		if (content === undefined) fs.rmSync(configFile, { force: true });
		else fs.writeFileSync(configFile, content);
		const ctx = ext.makeCtx({ mode: "tui", cwd: work });
		assert.ok((await messageFromExtension("probe-other", ctx)).includes("blocked fetch"));
		assert.ok(ctx.notices.some(([message, level]) => level === "warning" && message.includes(configFile) && message.includes(problem)));
		assert.ok(fs.readFileSync(join(agentDir, "net-guard.log"), "utf8").includes(problem));
	}
});
