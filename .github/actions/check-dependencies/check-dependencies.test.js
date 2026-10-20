const test = require('node:test');
const assert = require('node:assert/strict');
const { check } = require('./check-dependencies.js');

function fixture({ body, labels = [], states = {} }) {
  const calls = [];
  const github = {
    graphql: async () => ({ repository: { pullRequest: { reviewDecision: github.reviewDecision, mergeable: github.mergeable ?? 'MERGEABLE' } } }),
    paginate: async (fn) => (fn === github.rest.repos.getBranchRules ? [{ type: 'required_status_checks', parameters: { required_status_checks: [{ context: 'ci' }] } }] : fn === github.rest.checks.listForRef ? [{ name: 'ci', conclusion: github.ciConclusion ?? 'success' }] : []),
    rest: {
      pulls: { list() {} },
      checks: { listForRef() {} },
      repos: { getBranchRules() {}, createCommitStatus: async ({ state }) => calls.push(['status', state]) },
      issues: {
        get: async ({ owner, repo, issue_number }) => ({ data: { state: states[`${owner}/${repo}#${issue_number}`] ?? 'closed' } }),
        createLabel: async () => calls.push('createLabel'),
        addLabels: async ({ labels }) => calls.push(['addLabels', labels]),
        removeLabel: async ({ name }) => calls.push(['removeLabel', name]),
      },
    },
  };
  const context = { repo: { owner: 'o', repo: 'r' }, payload: { pull_request: { number: 7, head: { sha: 'abc' }, base: { ref: 'main' }, body, labels: labels.map((name) => ({ name })) } } };
  const core = { warning() {} };
  return { github, context, core, calls };
}

test('open dependencies in every link style add the blocked label and never fail', async () => {
  const body = 'Depends on #1\nBlocked by a/b#2\ndepends on https://github.com/c/d/pull/3';
  const states = { 'o/r#1': 'open', 'a/b#2': 'open', 'c/d#3': 'open' };
  const { github, context, core, calls } = fixture({ body, states });
  await check({ github, context, core });
  assert.deepEqual(calls, [['status', 'pending'], 'createLabel', ['addLabels', ['blocked']]]);
});

test('cleared dependencies remove the blocked label unless changes are requested', async () => {
  const { github, context, core, calls } = fixture({ body: 'Depends on #1', labels: ['blocked'] });
  github.reviewDecision = 'CHANGES_REQUESTED';
  await check({ github, context, core });
  github.reviewDecision = null;
  await check({ github, context, core });
  assert.deepEqual(calls, [['status', 'success'], ['status', 'success'], ['removeLabel', 'blocked']]);
});

for (const [name, state, removed] of [
  ['a merge conflict', { mergeable: 'CONFLICTING' }, false],
  ['an unknown merge state', { mergeable: 'UNKNOWN' }, false],
  ['a failed required check', { ciConclusion: 'failure' }, false],
  ['a mergeable PR with passing checks', {}, true],
]) {
  test(`cleared dependencies ${removed ? 'remove' : 'keep'} the blocked label for ${name}`, async () => {
    const { github, context, core, calls } = fixture({ body: 'Depends on #1', labels: ['blocked'] });
    Object.assign(github, state);
    await check({ github, context, core, delay: async () => {} });
    assert.deepEqual(calls, removed ? [['status', 'success'], ['removeLabel', 'blocked']] : [['status', 'success']]);
  });
}

test('removing a blocked label that is already gone does not fail', async () => {
  const { github, context, core, calls } = fixture({ body: 'Depends on #1', labels: ['blocked'] });
  github.rest.issues.removeLabel = async () => { throw Object.assign(new Error('Label does not exist'), { status: 404 }); };
  await check({ github, context, core });
  assert.deepEqual(calls, [['status', 'success']]);
});

test('an API error sets the error status and still fails', async () => {
  const { github, context, core, calls } = fixture({ body: 'Depends on #1' });
  github.rest.issues.get = async () => { throw new Error('boom'); };
  await assert.rejects(check({ github, context, core }), /boom/);
  assert.deepEqual(calls, [['status', 'error']]);
});

test('a scheduled run rechecks open PRs that are blocked or pending and skips the rest', async () => {
  const pull = (number, labels, body = 'Depends on #1') => ({ number, head: { sha: `sha${number}` }, base: { ref: 'main' }, body, labels: labels.map((name) => ({ name })) });
  const { github, context, core, calls } = fixture({ body: '' });
  delete context.payload.pull_request;
  const pulls = [pull(1, ['blocked']), pull(2, []), pull(3, [])];
  github.paginate = async (fn, params) => (fn === github.rest.pulls.list && params.state === 'open' ? pulls : []);
  github.rest.repos.createCommitStatus = async ({ sha, state }) => calls.push(['status', sha, state]);
  github.rest.repos.listCommitStatusesForRef = async ({ ref }) => ({ data: ref === 'sha2' ? [{ context: 'dependencies', state: 'pending' }] : [] });
  await check({ github, context, core });
  assert.deepEqual(calls, [['status', 'sha1', 'success'], ['removeLabel', 'blocked'], ['status', 'sha2', 'success']]);
});

test('closing a PR rechecks the open same-repo PRs that depend on it', async () => {
  const pull = (number, body) => ({ number, head: { sha: `sha${number}` }, body, labels: [] });
  const { github, context, core, calls } = fixture({ body: 'Merged work' });
  context.payload.action = 'closed';
  context.payload.pull_request.number = 5;
  github.paginate = async () => [pull(6, 'Depends on #5'), pull(7, 'Depends on a/b#5'), pull(8, 'Depends on o/r#4')];
  github.rest.repos.createCommitStatus = async ({ sha, state }) => calls.push(['status', sha, state]);
  await check({ github, context, core });
  assert.deepEqual(calls, [['status', 'abc', 'success'], ['status', 'sha6', 'success']]);
});

function searchClient(calls, resultsByQuery) {
  return {
    paginate: async (_, { q }) => (calls.push(['search', q]), resultsByQuery[q] ?? []),
    rest: {
      search: { issuesAndPullRequests() {} },
      repos: { createDispatchEvent: async ({ repo, event_type }) => calls.push(['dispatch', repo, event_type]) },
    },
  };
}

function closedFixture() {
  const fixtureArgs = fixture({ body: 'Merged work' });
  fixtureArgs.context.payload.action = 'closed';
  fixtureArgs.context.payload.pull_request.number = 5;
  fixtureArgs.github.paginate = async () => [];
  fixtureArgs.github.rest.repos.createCommitStatus = async () => {};
  return fixtureArgs;
}

const item = (slug, body) => ({ repository_url: `https://api.github.com/repos/${slug}`, body });

test('closing a PR dispatches a recheck to other repos whose open PRs depend on it by shorthand or URL', async () => {
  const { github, context, core, calls } = closedFixture();
  const client = searchClient(calls, {
    '"o/r#5" is:pr is:open user:o in:body': [item('o/x', 'Depends on o/r#5'), item('o/y', 'Depends on #5'), item('o/r', 'Depends on o/r#5')],
    '"https://github.com/o/r/pull/5" is:pr is:open user:o in:body': [item('o/z', 'blocked by https://github.com/o/r/pull/5')],
  });
  await check({ github, context, core, getOctokit: () => client, token: 't' });
  assert.deepEqual(calls.filter(([type]) => type === 'dispatch'), [['dispatch', 'x', 'dependencies-recheck'], ['dispatch', 'z', 'dependencies-recheck']]);
});

test('a refused dispatch only warns', async () => {
  const { github, context, core } = closedFixture();
  const warnings = [];
  core.warning = (message) => warnings.push(message);
  const client = searchClient([], { '"o/r#5" is:pr is:open user:o in:body': [item('o/x', 'Depends on o/r#5')] });
  client.rest.repos.createDispatchEvent = async () => { throw new Error('Forbidden'); };
  await check({ github, context, core, getOctokit: () => client, token: 't' });
  assert.match(warnings[0], /o\/x.*Forbidden/);
});
