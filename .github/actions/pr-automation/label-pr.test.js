const test = require('node:test');
const assert = require('node:assert/strict');
const { hasBreakingChange, labelBlocked, labelAutoRebase } = require('./label-pr.js');

test('bang before colon marks breaking regardless of body', () => {
  assert.equal(hasBreakingChange('feat!: drop old api', ''), true);
});

test('scoped bang before colon marks breaking', () => {
  assert.equal(hasBreakingChange('feat(scope)!: drop old api', ''), true);
});

test('BREAKING CHANGE footer marks breaking', () => {
  assert.equal(
    hasBreakingChange('feat: add widget', 'Some body.\n\nBREAKING CHANGE: removes old api'),
    true
  );
});

test('no bang and no footer is not breaking', () => {
  assert.equal(hasBreakingChange('feat: add widget', 'Just a normal change.'), false);
});

test('missing body does not throw', () => {
  assert.equal(hasBreakingChange('feat: add widget', undefined), false);
});

function blockedFixture({ reviewDecision = null, labels = [], state = 'OPEN', createLabelError = null }) {
  const calls = [];
  const issues = {
    createLabel: async (args) => {
      calls.push(['createLabel', args.name]);
      if (createLabelError) throw createLabelError;
    },
    addLabels: async (args) => calls.push(['addLabels', args.labels]),
    removeLabel: async (args) => calls.push(['removeLabel', args.name]),
  };
  const github = {
    graphql: async () => ({
      repository: {
        pullRequest: {
          id: 'PR_1',
          number: 7,
          state,
          isDraft: true,
          reviewDecision,
          headRefOid: 'abc',
          labels: { nodes: labels.map((name) => ({ name })) },
        },
      },
    }),
    rest: {
      issues,
    },
  };
  const context = { repo: { owner: 'o', repo: 'r' }, payload: { pull_request: { number: 7 } } };
  const core = { info() {}, warning: (message) => calls.push(['warning', message]) };
  return { github, context, core, calls };
}

test('blocked PR gets the blocked label, creating it first', async () => {
  const { github, context, core, calls } = blockedFixture({ reviewDecision: 'CHANGES_REQUESTED' });
  await labelBlocked({ github, context, core });
  assert.deepEqual(calls, [['createLabel', 'blocked'], ['addLabels', ['blocked']]]);
});

test('already-labelled blocked PR is left alone', async () => {
  const { github, context, core, calls } = blockedFixture({ reviewDecision: 'CHANGES_REQUESTED', labels: ['blocked'] });
  await labelBlocked({ github, context, core });
  assert.deepEqual(calls, []);
});

test('unblocked PR without the label is left alone', async () => {
  const { github, context, core, calls } = blockedFixture({});
  await labelBlocked({ github, context, core });
  assert.deepEqual(calls, []);
});

test('closed PR is left alone', async () => {
  const { github, context, core, calls } = blockedFixture({ state: 'CLOSED', reviewDecision: 'CHANGES_REQUESTED' });
  await labelBlocked({ github, context, core });
  assert.deepEqual(calls, []);
});

test('existing blocked label does not stop labelling', async () => {
  const { github, context, core, calls } = blockedFixture({
    reviewDecision: 'CHANGES_REQUESTED',
    createLabelError: Object.assign(new Error('already exists'), { status: 422 }),
  });
  await labelBlocked({ github, context, core });
  assert.deepEqual(calls.at(-1), ['addLabels', ['blocked']]);
  assert.equal(calls.some(([kind]) => kind === 'warning'), false);
});

function rebaseFixture({ status = 'success', labels = [], draft = false, autoMerge = true }) {
  const calls = [];
  const pr = { number: 7, draft, auto_merge: autoMerge && {}, head: { sha: 'abc' }, labels: labels.map((name) => ({ name })) };
  const rest = {
    pulls: { get: async () => ({ data: pr }) },
    repos: { getCombinedStatusForRef: async () => ({ data: { statuses: [{ context: 'codeowner-review', state: status }] } }) },
    issues: { createLabel: async () => calls.push('createLabel'), addLabels: async (args) => calls.push(args.labels) },
  };
  const outputs = {};
  const core = { setOutput: (name, value) => { outputs[name] = value; } };
  return { github: { rest }, core, outputs, context: { repo: { owner: 'o', repo: 'r' }, payload: { pull_request: { number: 7 } } }, calls };
}

test('approved ready auto-merge PR gets the auto-rebase label', async () => {
  const f = rebaseFixture({});
  await labelAutoRebase(f);
  assert.deepEqual(f.calls, ['createLabel', ['auto-rebase']]);
  assert.deepEqual(f.outputs, { labelled: 'true' });
});

test('PR missing any auto-rebase condition is left alone', async () => {
  for (const options of [{ status: 'pending' }, { labels: ['blocked'] }, { draft: true }, { autoMerge: false }, { labels: ['auto-rebase'] }]) {
    const f = rebaseFixture(options);
    await labelAutoRebase(f);
    assert.deepEqual(f.calls, [], JSON.stringify(options));
  }
});
