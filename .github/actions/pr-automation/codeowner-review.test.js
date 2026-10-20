const test = require('node:test');
const assert = require('node:assert/strict');
const { gate } = require('./codeowner-review.js');

const CODEOWNERS = '*.md @Owner\n/src/*/prompts/**/rules/ @Owner @friend\n/src/*/prompts/**/skills/ @Owner @friend\n/src/*/prompts/**/skills/pi-help/ @Owner\n/src/*/prompts/**/rules/hooks*.md @Owner\na**b/ @friend\na?c @friend\n';

function fixture({ author, files, reviews = [] }) {
  const calls = [];
  const github = {
    paginate: async (method) => method.items,
    rest: {
      pulls: { listFiles: { items: files.map((file) => (typeof file === 'string' ? { filename: file } : file)) }, listReviews: { items: reviews.map(([login, state]) => ({ user: { login }, state })) } },
      repos: {
        getContent: async ({ path, ref }) => ({ data: { content: Buffer.from(CODEOWNERS).toString('base64'), path, ref } }),
        createCommitStatus: async ({ sha, context, state }) => calls.push([sha, context, state]),
      },
    },
  };
  const context = { repo: { owner: 'owner', repo: 'r' }, payload: { pull_request: { number: 7, user: { login: author }, head: { sha: 'abc' }, base: { ref: 'main' } } } };
  return { github, context, calls };
}

const PROMPT_FILE = 'src/llm_prompts/prompts/shared/rules/a.md';
const check = (state, files) => async () => {
  for (const file of files) {
    const f = fixture({ author: 'Owner', files: [].concat(file) });
    await gate(f);
    assert.deepEqual(f.calls, [['abc', 'codeowner-review', state]], JSON.stringify(file));
  }
};

test('owner change outside prompts succeeds without review', async () => {
  const { github, context, calls } = fixture({ author: 'owner', files: ['src/llm_prompts/cli.py', 'src/llm_prompts/prompts/pi/extensions/x.ts'] });
  await gate({ github, context });
  assert.deepEqual(calls, [['abc', 'codeowner-review', 'success']]);
});

test('owner prompt change waits for another code owner to approve', async () => {
  const waiting = fixture({ author: 'owner', files: [PROMPT_FILE], reviews: [['owner', 'APPROVED']] });
  await gate(waiting);
  assert.deepEqual(waiting.calls, [['abc', 'codeowner-review', 'pending']]);

  const approved = fixture({ author: 'owner', files: [PROMPT_FILE], reviews: [['Friend', 'APPROVED']] });
  await gate(approved);
  assert.deepEqual(approved.calls, [['abc', 'codeowner-review', 'success']]);
});

test('exempt and unmatched files need no review', check('success', [
  'src/llm_prompts/prompts/pi/skills/pi-help/SKILL.md', 'src/llm_prompts/prompts/pi/skills/pi-help/a/b.md', 'src/llm_prompts/prompts/kiro/rules/hooks-kiro.md', 'src/llm_prompts/prompts/shared/rules/hooks-llm-prompts.md', 'src/llm_prompts/cli.py', 'a/x/b/f', 'a/c',
]));

test('a mixed change, a rename from a covered path or any file under another owner needs review', check('pending', [
  ['src/llm_prompts/prompts/pi/skills/pi-help/SKILL.md', PROMPT_FILE], { filename: 'x.py', previous_filename: PROMPT_FILE }, 'src/llm_prompts/prompts/pi/skills/pi-help-x/a.md', 'src/llm_prompts/prompts/shared/rules/nothooks.md', 'axyb/f', 'abc',
]));

test('other author needs a code owner approval even outside prompts', async () => {
  const stranger = fixture({ author: 'stranger', files: ['README.md'], reviews: [['bystander', 'APPROVED']] });
  await gate(stranger);
  assert.deepEqual(stranger.calls, [['abc', 'codeowner-review', 'pending']]);

  const approved = fixture({ author: 'stranger', files: ['README.md'], reviews: [['owner', 'APPROVED']] });
  await gate(approved);
  assert.deepEqual(approved.calls, [['abc', 'codeowner-review', 'success']]);
});

test('renovate bot PRs pass without review but other bots do not', async () => {
  const renovate = fixture({ author: 'renovate[bot]', files: ['README.md'] });
  await gate(renovate);
  assert.deepEqual(renovate.calls, [['abc', 'codeowner-review', 'success']]);

  const other = fixture({ author: 'dependabot[bot]', files: ['README.md'] });
  await gate(other);
  assert.deepEqual(other.calls, [['abc', 'codeowner-review', 'pending']]);
});

test('requested changes keep the status pending until the review is dismissed', async () => {
  const blocked = fixture({ author: 'stranger', files: ['README.md'], reviews: [['owner', 'APPROVED'], ['friend', 'CHANGES_REQUESTED']] });
  await gate(blocked);
  assert.deepEqual(blocked.calls, [['abc', 'codeowner-review', 'pending']]);

  const dismissed = fixture({ author: 'stranger', files: ['README.md'], reviews: [['owner', 'APPROVED'], ['friend', 'CHANGES_REQUESTED'], ['friend', 'DISMISSED']] });
  await gate(dismissed);
  assert.deepEqual(dismissed.calls, [['abc', 'codeowner-review', 'success']]);
});

test('an API error sets the error status and still fails', async () => {
  const { github, context, calls } = fixture({ author: 'stranger', files: [] });
  github.paginate = async () => { throw new Error('boom'); };
  await assert.rejects(gate({ github, context }), /boom/);
  assert.deepEqual(calls, [['abc', 'codeowner-review', 'error']]);
});
