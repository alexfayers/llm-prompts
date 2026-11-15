import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { Registry, registryOf, type Run } from "../../src/llm_prompts/prompts/pi/extensions/pi-context/registry.ts";

const run = (id: string, patch: Partial<Run> = {}): Run => ({ id, name: id, role: "reader", background: true, state: "running", task: "t", startedAt: 1, ...patch });

describe("Registry", () => {
	test("tracks runs, lists the live ones and tells listeners about each change", () => {
		const registry = new Registry();
		const seen: string[] = [];
		const off = registry.onChange((changed) => seen.push(`${changed.id}:${changed.state}`));
		registry.start(run("a"));
		registry.start(run("b"));
		registry.update("a", { state: "landing" });
		registry.update("a", { state: "done", endedAt: 2 });
		assert.deepEqual(registry.live().map((r) => r.id), ["b"]);
		assert.deepEqual(registry.all().map((r) => [r.id, r.state]), [["a", "done"], ["b", "running"]]);
		off();
		registry.update("b", { state: "failed" });
		assert.deepEqual(seen, ["a:running", "b:running", "a:landing", "a:done"]);
		assert.equal(registry.update("nope", { state: "done" }), undefined);
	});

	test("rebuilds from saved records: the last record per run wins and a run that was running or landing is lost", () => {
		const rebuilt = Registry.rebuild([run("a"), run("b"), run("a", { state: "done" }), run("c", { state: "landing" }), run("d", { state: "blocked" })]);
		assert.deepEqual(rebuilt.all().map((r) => [r.id, r.state]), [["a", "done"], ["b", "lost"], ["c", "lost"], ["d", "blocked"]]);
		assert.deepEqual(rebuilt.live(), []);
	});

	test("registryOf gives every caller the same registry", () => {
		assert.equal(registryOf(), registryOf());
	});

	test("registryOf replaces a registry that an older version of the code left behind", () => {
		const holder = globalThis as { [key: symbol]: unknown };
		const key = Symbol.for("pi-context.registry");
		const current = holder[key];
		holder[key] = { version: 0 };
		try {
			assert.ok(registryOf() instanceof Registry);
			assert.equal(registryOf(), registryOf());
		} finally {
			holder[key] = current;
		}
	});
});
