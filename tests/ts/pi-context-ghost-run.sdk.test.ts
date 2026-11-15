import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, test } from "node:test";
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from "@earendil-works/pi-ai";
import { createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import { ghostResults, makeFixture, PUSH_REASON, type Seen, sessionExtension } from "./ghost-fixture.ts";
import { useEnv } from "./helpers.ts";

describe("ghost_run in a session", () => {
	useEnv({ PI_CONTEXT_CHILD: undefined });
	let fixture: Awaited<ReturnType<typeof makeFixture>>;
	let agentDir: string;
	before(async () => {
		agentDir = mkdtempSync(join(tmpdir(), "ghost-agent-"));
		process.env.PI_CODING_AGENT_DIR = agentDir;
		fixture = await makeFixture();
	});
	after(() => (fixture.cleanup(), rmSync(agentDir, { recursive: true })));

	/** Has the faux model call ghost_run for each name in turn, and returns the results and the tool calls seen. */
	async function replay(...names: string[]) {
		process.env.PI_CODING_AGENT_DIR = agentDir;
		const faux = fauxProvider();
		const modelRuntime = await ModelRuntime.create({ authPath: join(agentDir, "auth.json"), modelsPath: null, refreshOnCreate: false });
		modelRuntime.registerNativeProvider(faux.provider);
		const seen: Seen = { calls: [] };
		const resourceLoader = new DefaultResourceLoader({ cwd: fixture.work, agentDir, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, extensionFactories: [sessionExtension(seen)] });
		await resourceLoader.reload();
		const sessionManager = SessionManager.inMemory(fixture.work);
		const { session } = await createAgentSession({ cwd: fixture.work, agentDir, model: faux.getModel(), modelRuntime, resourceLoader, sessionManager, settingsManager: SettingsManager.inMemory({}), tools: ["bash", "read", "ghost_run"] });
		await session.bindExtensions({});
		faux.setResponses([...names.map((name) => fauxAssistantMessage([fauxToolCall("ghost_run", { name })])), fauxAssistantMessage("done")]);
		await session.prompt("go");
		session.dispose();
		return { results: ghostResults(sessionManager.getEntries()), seen };
	}

	test("a ghost replays green through the hooks of every step, a dirty tree diverges at the status step, and a blocked push returns the guard's reason word for word", async () => {
		const green = await replay("sync-main");
		assert.deepEqual(green.results.map((result) => [result.isError, result.text]), [[false, "ghost sync-main ok (4 steps)"]]);
		assert.equal(fixture.head(), "second");
		const [outer, ...nested] = green.seen.calls;
		assert.equal(outer, "ghost_run");
		assert.deepEqual(nested, Array(4).fill(nested[0]));
		assert.match(nested[0], /^bash<-/);

		fixture.dirty();
		const dirty = await replay("sync-main");
		assert.equal(dirty.results[0].isError, true);
		assert.match(dirty.results[0].text, /diverged at step 2 of 4 \(bash\)[\s\S]*git status --porcelain[\s\S]*M a\.txt[\s\S]*Done: 1\. bash/);
		assert.equal(dirty.seen.calls.filter((call) => call.startsWith("bash<-")).length, 2);

		const blocked = await replay("push-main");
		assert.equal(blocked.results[0].isError, true);
		assert.ok(blocked.results[0].text.includes(PUSH_REASON), blocked.results[0].text);
	});
});
