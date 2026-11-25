import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { join } from "node:path";
import { afterEach, describe, test } from "node:test";
import { RpcChild } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/runner.ts";

const STUB = join(import.meta.dirname, "fixtures/rpc-stub.mjs");
const children: RpcChild[] = [];

const RUNNER = join(import.meta.dirname, "../../src/llm_prompts/prompts/pi/extensions/pi-context/runner.ts");

function start(options: Partial<Parameters<typeof RpcChild.start>[0]> = {}) {
	const child = RpcChild.start({ command: [process.execPath, STUB], args: [], cwd: process.cwd(), ...options });
	children.push(child);
	return child;
}

afterEach(() => {
	for (const child of children.splice(0)) child.kill();
});

describe("RpcChild.prompt", { timeout: 10_000 }, () => {
	test("resolves with the reply, summed usage and the first request's usage when the child settles", async () => {
		const turn = await start().prompt("hello");
		assert.equal(turn.error, undefined);
		assert.equal(turn.text, "echo: hello");
		assert.deepEqual(turn.usage, { input: 20, output: 10, cacheRead: 300, cacheWrite: 2 });
		assert.equal(turn.firstUsage?.cacheRead, 100);
	});

	test("gives the arguments of the turn's last successful reply call, and none without one", async () => {
		const child = start();
		assert.deepEqual((await child.prompt("reply")).reply, { outcome: "done", ref: "r1" });
		assert.equal((await child.prompt("hello")).reply, undefined);
	});

	test("ignores malformed and non-protocol lines", async () => {
		const turn = await start().prompt("garbage");
		assert.equal(turn.text, "echo: garbage");
	});

	test("relays a dialog to onUi and sends its answer back", async () => {
		const asked: unknown[] = [];
		const turn = await start({
			onUi: async (request) => {
				asked.push(request.method);
				return { confirmed: true };
			},
		}).prompt("ui");
		assert.deepEqual(asked, ["confirm"]);
		assert.equal(turn.text, 'echo: ui:{"confirmed":true}');
	});

	test("cancels a dialog when no onUi is given", async () => {
		const turn = await start().prompt("ui");
		assert.equal(turn.text, 'echo: ui:{"cancelled":true}');
	});

	test("passes notifications to onUi without answering", async () => {
		const seen: string[] = [];
		const turn = await start({ onUi: (request) => void seen.push(request.method) }).prompt("notify");
		assert.deepEqual(seen, ["notify"]);
		assert.equal(turn.text, "echo: notify");
	});

	test("reports a crash as the turn's error", async () => {
		const child = start();
		const turn = await child.prompt("crash");
		assert.match(turn.error ?? "", /exited.*code 3/);
		assert.equal((await child.exited).code, 3);
		assert.match((await child.prompt("again")).error ?? "", /exited/);
	});

	test("reports a child that cannot start as the turn's error", async () => {
		const turn = await start({ command: ["/nonexistent/pi"] }).prompt("hello");
		assert.match(turn.error ?? "", /ENOENT/);
	});

	test("does not wait for a prompt the child handled itself", async () => {
		const turn = await start().prompt("handled");
		assert.equal(turn.text, "");
		assert.equal(turn.error, undefined);
	});
});

describe("RpcChild shutdown", { timeout: 10_000 }, () => {
	test("abort makes the running turn end as aborted", async () => {
		const child = start();
		const turn = child.prompt("hang");
		child.abort();
		assert.equal((await turn).error, "aborted");
	});

	test("close ends the child by closing its input", async () => {
		const child = start();
		child.close();
		assert.equal((await child.exited).code, 0);
	});

	test("close terminates a child that ignores the closed input after the grace period", async () => {
		const child = start({ env: { ...process.env, STUB_IGNORE_EOF: "1" } });
		child.close(50);
		assert.equal((await child.exited).signal, "SIGTERM");
	});

	test("an aborted signal aborts the turn and closes the child", async () => {
		const controller = new AbortController();
		const child = start({ signal: controller.signal });
		const turn = child.prompt("hang");
		controller.abort();
		assert.equal((await turn).error, "aborted");
		assert.equal((await child.exited).code, 0);
	});

	test("children are terminated when the parent process exits", async () => {
		const driver = `import { RpcChild } from ${JSON.stringify(RUNNER)};
			const child = RpcChild.start({ command: [process.execPath, ${JSON.stringify(STUB)}], args: [], cwd: process.cwd() });
			console.log(child.pid);
			process.exit(0);`;
		const pid = await new Promise<number>((resolve, reject) =>
			execFile(process.execPath, ["--input-type=module", "-e", driver], (error, stdout) => (error ? reject(error) : resolve(Number(stdout)))),
		);
		const alive = () => {
			try {
				process.kill(pid, 0);
				return true;
			} catch {
				return false;
			}
		};
		for (let tries = 0; alive() && tries < 100; tries++) await new Promise((resolve) => setTimeout(resolve, 50));
		assert.equal(alive(), false);
	});
});

describe("RpcChild shutdown", { timeout: 10_000 }, () => {
	test("close kills a child that ignores both the closed input and SIGTERM", async () => {
		const child = start({ env: { ...process.env, STUB_IGNORE_EOF: "1", STUB_IGNORE_TERM: "1" } });
		await child.prompt("handled");
		child.close(50);
		assert.equal((await child.exited).signal, "SIGKILL");
	});

	test("a second error event on the child does not go unhandled", async () => {
		const child = start();
		const process_ = (child as unknown as { child: { emit(event: string, error: Error): boolean } }).child;
		assert.doesNotThrow(() => (process_.emit("error", new Error("first")), process_.emit("error", new Error("second"))));
		assert.match((await child.exited).reason ?? "", /first/);
	});
});

describe("RpcChild scope", { timeout: 10_000 }, () => {
	test("is stopped when the child exits, before an orphan holding its output lets it close", async () => {
		const orphanMs = 1500;
		const orphan = `require('node:child_process').spawn(process.execPath, ['-e', 'setTimeout(() => {}, ${orphanMs})'], { stdio: 'inherit' }).unref()`;
		const started = Date.now();
		let releasedAfter = Infinity;
		const child = start({
			command: [process.execPath, "-e", orphan],
			limits: {},
			cap: (command) => ({ command, release: async () => void (releasedAfter = Date.now() - started) }),
		});
		await child.exited;
		assert.ok(releasedAfter < orphanMs / 2, `released after ${releasedAfter}ms`);
		assert.ok(Date.now() - started >= orphanMs / 2);
	});
});
