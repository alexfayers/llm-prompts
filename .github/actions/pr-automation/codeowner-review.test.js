const test = require('node:test');
const assert = require('node:assert/strict');
const { gate } = require('./codeowner-review.js');

const CODEOWNERS = '*.md @Owner\n/src/*/prompts/**/rules/ @Owner @friend\n/src/*/prompts/**/skills/ @Owner @friend\n/src/*/prompts/**/skills/pi-help/ @Owner\n/src/*/prompts/**/rules/hooks*.md @Owner\na**b/ @friend\na?c @friend\n';

function fixture({ author, files, reviews = [], labels = [], branch = 'feature', requested = [], draft = false }) {
  const calls = [];
  const requests = [];
  const github = {
    paginate: async (method) => method.items,
    rest: {
      pulls: { listFiles: { items: files.map((file) => (typeof file === 'string' ? { filename: file } : file)) }, listReviews: { items: reviews.map(([login, state, copilot]) => ({ user: { login }, state, is_copilot_code_review: copilot })) }, requestReviewers: async ({ pull_number, reviewers }) => requests.push([pull_number, reviewers]) },
      repos: {
        getContent: async ({ path, ref }) => ({ data: { content: Buffer.from(CODEOWNERS).toString('base64'), path, ref } }),
        createCommitStatus: async ({ sha, context, state }) => calls.push([sha, context, state]),
      },
    },
  };
  const context = { repo: { owner: 'owner', repo: 'r' }, payload: { pull_request: { number: 7, user: { login: author }, labels: labels.map((name) => ({ name })), draft, requested_reviewers: requested.map((login) => ({ login })), requested_teams: [], head: { sha: 'abc', ref: branch }, base: { ref: 'main' } } } };
  return { github, context, calls, requests };
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

test('files no CODEOWNERS rule matches belong to the repo owner', async () => {
  for (const [author, reviews, state] of [
    ['owner', [], 'success'],
    ['stranger', [], 'pending'],
    ['stranger', [['bystander', 'APPROVED']], 'pending'],
    ['stranger', [['Owner', 'APPROVED']], 'success'],
  ]) {
    const f = fixture({ author, files: ['src/llm_prompts/cli.py'], reviews });
    await gate(f);
    assert.deepEqual(f.calls, [['abc', 'codeowner-review', state]], `${author} ${JSON.stringify(reviews)}`);
  }
});

test('the repo owner is asked to review only when the gate waits and the owner has not reviewed', async () => {
  for (const [name, options, reviewers] of [
    ['stranger PR', { author: 'stranger' }, ['owner']],
    ['major renovate PR', { author: 'renovate[bot]', branch: 'renovate/major-updates', labels: ['needs-review'] }, ['owner']],
    ['pi-extensions renovate PR', { author: 'renovate[bot]', branch: 'renovate/pi-extensions' }, []],
    ['safe renovate PR', { author: 'renovate[bot]', branch: 'renovate/all-minor-patch' }, []],
    ['owner PR', { author: 'owner' }, []],
    ['approved PR', { author: 'stranger', reviews: [['owner', 'APPROVED']] }, []],
    ['already requested', { author: 'stranger', requested: ['friend'] }, []],
    ['draft PR', { author: 'stranger', draft: true }, []],
    ['owner already commented', { author: 'stranger', reviews: [['Owner', 'COMMENTED']] }, []],
    ['owner already requested changes', { author: 'stranger', reviews: [['owner', 'CHANGES_REQUESTED']] }, []],
    ['someone else reviewed', { author: 'stranger', reviews: [['friend', 'COMMENTED']] }, ['owner']],
  ]) {
    const f = fixture({ files: ['README.md'], ...options });
    await gate(f);
    assert.deepEqual(f.requests, reviewers.length ? [[7, reviewers]] : [], name);
  }
});

test('renovate bot PRs pass without review only from known-safe branches', async () => {
  for (const [author, branch, labels, reviews, state] of [
    ['renovate[bot]', 'renovate/all-minor-patch', [], [], 'success'],
    ['renovate[bot]', 'renovate/github-actions', [], [], 'success'],
    ['renovate[bot]', 'renovate/lock-file-maintenance', ['ci'], [], 'success'],
    ['renovate[bot]', 'renovate/pi-extensions', [], [], 'success'],
    ['renovate[bot]', 'renovate/major-updates', ['needs-review'], [], 'pending'],
    ['renovate[bot]', 'renovate/major-updates', [], [['owner', 'APPROVED']], 'success'],
    ['renovate[bot]', 'renovate/all-minor-patch-2', [], [], 'pending'],
    ['renovate[bot]', 'feature/all-minor-patch', [], [], 'pending'],
    ['dependabot[bot]', 'renovate/all-minor-patch', [], [], 'pending'],
    ['stranger', 'renovate/all-minor-patch', [], [], 'pending'],
  ]) {
    const f = fixture({ author, files: ['README.md'], labels, reviews, branch });
    await gate(f);
    assert.deepEqual(f.calls, [['abc', 'codeowner-review', state]], `${author} ${branch} ${labels} ${JSON.stringify(reviews)}`);
  }
});

test('requested changes keep the status pending until the review is dismissed', async () => {
  const blocked = fixture({ author: 'stranger', files: ['README.md'], reviews: [['owner', 'APPROVED'], ['friend', 'CHANGES_REQUESTED']] });
  await gate(blocked);
  assert.deepEqual(blocked.calls, [['abc', 'codeowner-review', 'pending']]);

  const dismissed = fixture({ author: 'stranger', files: ['README.md'], reviews: [['owner', 'APPROVED'], ['friend', 'CHANGES_REQUESTED'], ['friend', 'DISMISSED']] });
  await gate(dismissed);
  assert.deepEqual(dismissed.calls, [['abc', 'codeowner-review', 'success']]);
});

test('a min-reviews label needs that many approvals from anyone but the author', async () => {
  const owner = ['owner', 'APPROVED'];
  for (const [reviews, labels, state] of [
    [[owner], ['min-reviews:2'], 'pending'],
    [[owner, ['stranger', 'APPROVED']], ['min-reviews:2'], 'pending'],
    [[owner, ['alice', 'APPROVED']], ['min-reviews:2'], 'success'],
    [[owner, ['alice', 'APPROVED'], ['alice', 'CHANGES_REQUESTED']], ['min-reviews:2'], 'pending'],
    [[owner, ['alice', 'APPROVED']], ['min-reviews:1'], 'success'],
    [[owner], [], 'success'],
  ]) {
    const f = fixture({ author: 'stranger', files: ['README.md'], reviews, labels });
    await gate(f);
    assert.deepEqual(f.calls, [['abc', 'codeowner-review', state]], JSON.stringify([reviews, labels]));
  }
});

test('a Copilot code review approval does not count toward min-reviews', async () => {
  const copilot = ['copilot-pull-request-reviewer[bot]', 'APPROVED', true];
  for (const [reviews, state] of [
    [[['owner', 'APPROVED'], copilot], 'pending'],
    [[['owner', 'APPROVED'], copilot, ['alice', 'APPROVED']], 'success'],
  ]) {
    const f = fixture({ author: 'stranger', files: ['README.md'], reviews, labels: ['min-reviews:2'] });
    await gate(f);
    assert.deepEqual(f.calls, [['abc', 'codeowner-review', state]], JSON.stringify(reviews));
  }
});

test('an API error sets the error status and still fails', async () => {
  const { github, context, calls } = fixture({ author: 'stranger', files: [] });
  github.paginate = async () => { throw new Error('boom'); };
  await assert.rejects(gate({ github, context }), /boom/);
  assert.deepEqual(calls, [['abc', 'codeowner-review', 'error']]);
});

test('a review relay run finds its PR by head sha', async () => {
  const { github, context, calls } = fixture({ author: 'owner', files: ['src/llm_prompts/cli.py'] });
  const pr = { ...context.payload.pull_request, head: { sha: 'abc', ref: 'fix', repo: { full_name: 'fork/r' } } };
  github.rest.pulls.list = { items: [{ ...pr, head: { ...pr.head, sha: 'other' } }, pr] };
  context.payload = { workflow_run: { head_sha: 'abc', head_branch: 'fix', head_repository: { full_name: 'fork/r' } } };
  await gate({ github, context });
  assert.deepEqual(calls, [['abc', 'codeowner-review', 'success']]);

  context.payload.workflow_run.head_sha = 'gone';
  await gate({ github, context });
  assert.equal(calls.length, 1);
});
