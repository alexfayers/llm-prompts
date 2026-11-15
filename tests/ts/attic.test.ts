import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import { loadExtension, useEnv } from "./helpers.ts";

const dir = mkdtempSync(join(tmpdir(), "attic-"));
const skillFile = join(dir, "SKILL.md");
const manifestFile = join(dir, "attic.json");
const ENTRY_TYPE = "attic";
const UNLOCK_TYPE = "attic-unlock";

const manifest = {
	built_at: "2026-11-15T00:00:00Z",
	window_days: 7,
	items: [
		{ kind: "skill", name: "region-build", uses: 0, stub: "Bring a service up in a new region" },
		{ kind: "tool", name: "ast_search", uses: 0, stub: "Search code by AST" },
		{ kind: "tool", name: "not_installed", uses: 0, stub: "absent tool" },
	],
};

before(() => {
	writeFileSync(skillFile, "# Region build\nSteps.\n");
	writeFileSync(manifestFile, JSON.stringify(manifest));
});
after(() => rmSync(dir, { recursive: true }));
useEnv(() => ({ PI_ATTIC: manifestFile }));

const skills = () => [
	{ name: "region-build", description: "d", filePath: skillFile },
	{ name: "git-usage", description: "d", filePath: "/x/git-usage/SKILL.md" },
	{ name: "tdd", description: "d", filePath: "/x/tdd/SKILL.md" },
];

async function start(branch: unknown[] = []) {
	const ext = await loadExtension("attic/index", {
		pi: { activeTools: ["read", "ast_search", "unlock", "bash"] },
		ctx: { sessionManager: { getBranch: () => branch } as any },
	});
	const options = { skills: skills(), sections: {} as Record<string, string>, selectedTools: ["read", "ast_search", "unlock", "bash"] };
	await ext.fire("before_agent_start", { systemPromptOptions: options });
	return { ext, options };
}

test("hides the listed skills and tools behind stubs and saves the set", async () => {
	const { ext, options } = await start();
	assert.deepEqual(options.skills.map((skill) => skill.name), ["git-usage", "tdd"]);
	assert.deepEqual(options.selectedTools, ["read", "unlock", "bash"]);
	assert.deepEqual(ext.pi.activeTools, ["read", "unlock", "bash"]);
	assert.match(options.sections.attic, /- ast_search: Search code by AST\n- region-build: Bring a service up in a new region/);
	assert.doesNotMatch(options.sections.attic, /not_installed/);
	assert.deepEqual(ext.pi.appended, [[ENTRY_TYPE, { hidden: ["ast_search", "region-build"] }]]);
});

test("unlock activates a hidden tool and saves it", async () => {
	const { ext } = await start();
	await ext.callTool("unlock", { name: "ast_search" });
	assert.deepEqual(ext.pi.activeTools, ["read", "unlock", "bash", "ast_search"]);
	assert.deepEqual(ext.pi.appended.at(-1), [UNLOCK_TYPE, { name: "ast_search" }]);
});

test("a hidden tool stays hidden and unlockable on the next turn", async () => {
	const { ext } = await start();
	const branch = ext.pi.appended.map(([customType, data]) => ({ type: "custom", customType, data }));
	(ext.ctx.sessionManager as any).getBranch = () => branch;
	const options = { skills: skills(), sections: {} as Record<string, string>, selectedTools: [...ext.pi.activeTools] };
	await ext.fire("before_agent_start", { systemPromptOptions: options });
	assert.match(options.sections.attic, /- ast_search: Search code by AST/);
	await ext.callTool("unlock", { name: "ast_search" });
	assert.deepEqual(ext.pi.activeTools, ["read", "unlock", "bash", "ast_search"]);
});
