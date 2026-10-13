const test = require('node:test');
const assert = require('node:assert/strict');
const { check } = require('./check-dependencies.js');

function fixture({ body, labels = [], states = {} }) {
  const calls = [];
  const github = {
    rest: {
      repos: { createCommitStatus: async ({ state }) => calls.push(['status', state]) },
      issues: {
        get: async ({ owner, repo, issue_number }) => ({ data: { state: states[`${owner}/${repo}#${issue_number}`] ?? 'closed' } }),
        createLabel: async () => calls.push('createLabel'),
        addLabels: async ({ labels }) => calls.push(['addLabels', labels]),
        removeLabel: async ({ name }) => calls.push(['removeLabel', name]),
      },
    },
  };
  const context = { repo: { owner: 'o', repo: 'r' }, payload: { pull_request: { number: 7, head: { sha: 'abc' }, body, labels: labels.map((name) => ({ name })) } } };
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

test('cleared dependencies remove the blocked label', async () => {
  const { github, context, core, calls } = fixture({ body: 'Depends on #1', labels: ['blocked'] });
  await check({ github, context, core });
  assert.deepEqual(calls, [['status', 'success'], ['removeLabel', 'blocked']]);
});

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
