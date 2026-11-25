import assert from "node:assert/strict";
import os from "node:os";
import { describe, test } from "node:test";
import { CPU_QUOTA_SHARE, forkCapper, MEMORY_MAX_SHARE, stopUnit, type SystemctlLauncher } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/cap.ts";

const COMMAND = ["pi", "--mode", "rpc"];

describe("forkCapper", () => {
	test("wraps the command in a scope with the given limits where scopes work", () => {
		const capped = forkCapper(() => true, () => undefined)(COMMAND, { memoryMax: "2G", cpuQuota: "150%" }).command;
		assert.match(capped[4], /^--unit=pi-fork-/);
		assert.deepEqual(capped.filter((_, index) => index !== 4), ["systemd-run", "--user", "--scope", "--quiet", "-p", "MemoryMax=2G", "-p", "CPUQuota=150%", ...COMMAND]);
	});

	test("defaults to shares of the host's memory and cores", () => {
		const capped = forkCapper(() => true, () => undefined)(COMMAND).command;
		assert.ok(capped.includes(`MemoryMax=${Math.floor(os.totalmem() * MEMORY_MAX_SHARE)}`));
		assert.ok(capped.includes(`CPUQuota=${Math.floor(os.availableParallelism() * CPU_QUOTA_SHARE * 100)}%`));
	});

	test("leaves the command uncapped and logs once where scopes do not work", () => {
		const logged: string[] = [];
		let probes = 0;
		const cap = forkCapper(() => (probes++, false), (line) => logged.push(line));
		assert.deepEqual(cap(COMMAND, {}).command, COMMAND);
		assert.deepEqual(cap(COMMAND, {}).command, COMMAND);
		assert.equal(probes, 1);
		assert.equal(logged.length, 1);
		assert.match(logged[0], /without a memory or CPU cap/);
	});

	test("probes once where scopes work", () => {
		let probes = 0;
		const cap = forkCapper(() => (probes++, true), () => undefined);
		cap(COMMAND);
		cap(COMMAND);
		assert.equal(probes, 1);
	});
});

describe("scope release", () => {
	const unitOf = (command: string[]) => command[4].slice("--unit=".length);

	test("stops the named unit once, however often it is released", async () => {
		const stopped: string[][] = [];
		const launch: SystemctlLauncher = async (args) => (stopped.push(args), { status: 0, stderr: "" });
		const capped = forkCapper(() => true, () => undefined, launch)(COMMAND);
		await capped.release();
		await capped.release();
		assert.deepEqual(stopped, [["--user", "stop", `${unitOf(capped.command)}.scope`]]);
	});

	test("gives each fork its own unit", () => {
		const cap = forkCapper(() => true, () => undefined);
		assert.notEqual(unitOf(cap(COMMAND).command), unitOf(cap(COMMAND).command));
	});

	test("releases nothing where the command is uncapped", async () => {
		const launch: SystemctlLauncher = async () => assert.fail("no unit to stop") as never;
		await forkCapper(() => false, () => undefined, launch)(COMMAND).release();
	});

	test("ignores a unit that is already gone and warns on any other failure", async () => {
		const logged: string[] = [];
		await stopUnit("pi-fork-a", async () => ({ status: 5, stderr: "Failed to stop pi-fork-a.scope: Unit pi-fork-a.scope not loaded." }), (line) => logged.push(line));
		assert.equal(logged.length, 0);
		await stopUnit("pi-fork-a", async () => ({ status: 1, stderr: "Access denied\n" }), (line) => logged.push(line));
		assert.deepEqual(logged, ["pi-context: could not stop pi-fork-a: Access denied"]);
	});
});
