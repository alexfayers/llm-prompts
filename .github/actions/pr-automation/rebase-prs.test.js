const test = require('node:test');
const assert = require('node:assert/strict');
const { isRebaseCandidate, rebase } = require('./rebase-prs.js');

const eligible = {
  autoMergeRequest: { enabledAt: '2026-01-01T00:00:00Z' },
  isDraft: false,
  isCrossRepository: false,
  mergeable: 'MERGEABLE',
};

test('auto-merge PR that is mergeable is a candidate', () => {
  assert.equal(isRebaseCandidate(eligible), true);
});

test('PR without auto-merge is rejected', () => {
  assert.equal(isRebaseCandidate({ ...eligible, autoMergeRequest: null }), false);
});

test('draft PR is rejected', () => {
  assert.equal(isRebaseCandidate({ ...eligible, isDraft: true }), false);
});

test('cross-repository PR is rejected', () => {
  assert.equal(isRebaseCandidate({ ...eligible, isCrossRepository: true }), false);
});

test('conflicting PR is rejected', () => {
  assert.equal(isRebaseCandidate({ ...eligible, mergeable: 'CONFLICTING' }), false);
});

test('PR with unknown mergeability is a candidate', () => {
  assert.equal(isRebaseCandidate({ ...eligible, mergeable: 'UNKNOWN' }), true);
});

const context = { repo: { owner: 'octo', repo: 'r' }, ref: 'refs/heads/main' };

function pr(number, overrides = {}) {
  return { ...eligible, id: `id${number}`, number, headRefOid: `oid${number}`, ...overrides };
}

function setup(nodes, failing = []) {
  const calls = [];
  const warnings = [];
  const github = {
    graphql: async (query, vars) => {
      calls.push({ query, vars });
      if (query.includes('updatePullRequestBranch')) {
        if (failing.includes(vars.id)) {
          throw new Error('boom');
        }
        return {};
      }
      return { repository: { pullRequests: { nodes } } };
    },
  };
  const core = { warning: (message) => warnings.push(message) };
  return { calls, warnings, github, core };
}

test('open PRs are listed for the pushed base branch', async () => {
  const { calls, github, core } = setup([]);
  await rebase({ github, context, core });
  assert.deepEqual(calls[0].vars, { owner: 'octo', repo: 'r', base: 'main' });
});

test('eligible PRs are rebased in order and others are skipped', async () => {
  const { calls, github, core } = setup([pr(1), pr(2, { autoMergeRequest: null }), pr(3)]);
  await rebase({ github, context, core });
  assert.deepEqual(
    calls.slice(1).map((call) => call.vars),
    [{ id: 'id1', head: 'oid1' }, { id: 'id3', head: 'oid3' }],
  );
});

test('a failed rebase warns and the remaining PRs are still rebased', async () => {
  const { calls, warnings, github, core } = setup([pr(1), pr(3)], ['id1']);
  await rebase({ github, context, core });
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /#1/);
  assert.equal(calls.length, 3);
  assert.deepEqual(calls[2].vars, { id: 'id3', head: 'oid3' });
});

test('no candidates runs only the list query', async () => {
  const { calls, github, core } = setup([pr(1, { isDraft: true })]);
  await rebase({ github, context, core });
  assert.equal(calls.length, 1);
});
