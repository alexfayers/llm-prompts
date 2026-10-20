import assert from "node:assert/strict";
import { join } from "node:path";
import { after, describe, test } from "node:test";
import { loadExtension, restoreMocks, useEnv } from "./helpers.ts";

const BIN = "/bin";
const PROJECT = "/project";
const PYRIGHT = "pyright-langserver";

type Options = { commands?: string[]; projectConfig?: object; events?: string[] };

async function sentAfterPrompts(
	installed: string[],
	{ commands = ["lsp-config"], projectConfig, events = ["session_start", "before_agent_start"] }: Options = {},
) {
	const ext = await loadExtension("lsp-defaults", {
		pi: { commandNames: commands },
		ctx: { cwd: PROJECT },
		mocks: {
			"node:fs": {
				accessSync: (file: string) => {
					if (!installed.some((binary) => join(BIN, binary) === file)) throw new Error("ENOENT");
				},
				readFileSync: (file: string) => {
					if (!projectConfig || file !== join(PROJECT, ".pi-lsp.json")) throw new Error("ENOENT");
					return JSON.stringify(projectConfig);
				},
			},
		},
	});
	for (const event of events) await ext.fire(event);
	return ext.pi.sent;
}

useEnv({ PATH: BIN });
after(restoreMocks);

describe("python fallback", () => {
	for (const server of ["ty", "ruff"]) {
		test(`${server} replaces missing pyright once per session`, async () => {
			const sent = await sentAfterPrompts([server], { events: ["session_start", "before_agent_start", "before_agent_start"] });
			assert.deepEqual(sent, [[`/lsp-config python ${server} server`, { expandPromptTemplates: true }]]);
		});
	}

	for (const [label, installed, options] of [
		["pyright is installed", ["ty", PYRIGHT], {}],
		["no fallback is installed", [], {}],
		["the project configures python", ["ty"], { projectConfig: { servers: { python: { command: "pylsp" } } } }],
		["the lsp-config command is missing", ["ty"], { commands: ["lsp"] }],
	] as [string, string[], Options][]) {
		test(`nothing is sent when ${label}`, async () => {
			assert.deepEqual(await sentAfterPrompts(installed, options), []);
		});
	}

	test("a new session applies the switch again", async () => {
		const sent = await sentAfterPrompts(["ty"], { events: ["session_start", "before_agent_start", "session_start", "before_agent_start"] });
		const message = ["/lsp-config python ty server", { expandPromptTemplates: true }];
		assert.deepEqual(sent, [message, message]);
	});
});
