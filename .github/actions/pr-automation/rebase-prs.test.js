const test = require('node:test');
const assert = require('node:assert/strict');
const { isRebaseCandidate, rebase, rebaseLabelled } = require('./rebase-prs.js');

const eligible = {
  mergeable: 'MERGEABLE',
  labels: { nodes: [{ name: 'auto-rebase' }] },
};

test('labelled mergeable PR is a candidate', () => {
  assert.equal(isRebaseCandidate(eligible), true);
});

test('PR without the auto-rebase label is rejected', () => {
  assert.equal(isRebaseCandidate({ ...eligible, labels: { nodes: [] } }), false);
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
  const { calls, github, core } = setup([pr(1), pr(2, { labels: { nodes: [] } }), pr(3)]);
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

test('Renovate PRs are not rebased', async () => {
  for (const login of ['renovate', 'renovate[bot]', 'app/renovate']) {
    const { calls, github, core } = setup([pr(1, { author: { login } }), pr(2, { author: { login: 'alice' } })]);
    await rebase({ github, context, core });
    assert.deepEqual(calls.slice(1).map((call) => call.vars), [{ id: 'id2', head: 'oid2' }], login);
  }
});

test('no candidates runs only the list query', async () => {
  const { calls, github, core } = setup([pr(1, { mergeable: 'CONFLICTING' })]);
  await rebase({ github, context, core });
  assert.equal(calls.length, 1);
});

const labelContext = { repo: { owner: 'octo', repo: 'r' }, payload: { pull_request: { number: 7 } } };

function setupLabelled(behindBy) {
  const calls = [];
  const github = {
    graphql: async (query, vars) => {
      calls.push({ query, vars });
      return query.includes('updatePullRequestBranch') ? {} : { repository: { pullRequest: pr(7, { baseRefName: 'main' }) } };
    },
    rest: {
      repos: {
        compareCommitsWithBasehead: async (params) => {
          calls.push({ compare: params });
          return { data: { behind_by: behindBy } };
        },
      },
    },
  };
  return { calls, github };
}

test('a labelled PR that is behind is rebased', async () => {
  const { calls, github } = setupLabelled(2);
  await rebaseLabelled({ github, context: labelContext, core: {} });
  assert.deepEqual(calls[1].compare, { owner: 'octo', repo: 'r', basehead: 'main...oid7' });
  assert.deepEqual(calls[2].vars, { id: 'id7', head: 'oid7' });
});

test('a labelled PR that is up to date is not rebased', async () => {
  const { calls, github } = setupLabelled(0);
  await rebaseLabelled({ github, context: labelContext, core: {} });
  assert.equal(calls.length, 2);
});
