const test = require('node:test');
const assert = require('node:assert/strict');
const { labelConflicts } = require('./label-conflicts.js');

async function run({ mergeable, labels = [], reviewDecision = null, actor = 'github-actions[bot]', open = [], rules = [], runs = [], statuses = [], payload = { pull_request: { number: 7, head: { sha: 'abc' }, base: { ref: 'main' } } } }) {
  const changes = [];
  const states = [].concat(mergeable);
  const record = (kind) => async (args) => changes.push([kind, args.issue_number, args.labels ?? args.name]);
  const labelEvent = (login, name = 'blocked') => ({ event: 'labeled', label: { name }, actor: { login } });
  const github = {
    graphql: async () => ({ repository: { pullRequest: { reviewDecision, mergeable: states.shift() ?? 'UNKNOWN', labels: { nodes: labels.map((name) => ({ name })) } } } }),
    paginate: async (method) => ({ pulls: open, rules, checks: runs })[method] ?? [labelEvent('someone'), labelEvent(actor), labelEvent('someone', 'other')],
    rest: { pulls: { list: 'pulls' }, repos: { getBranchRules: 'rules', listCommitStatusesForRef: async () => ({ data: statuses }) }, checks: { listForRef: 'checks' }, issues: { createLabel: record('createLabel'), addLabels: record('addLabels'), removeLabel: () => assert.fail('removal must use the token client') } },
  };
  const removeClient = { rest: { issues: { removeLabel: record('removeLabel') } } };
  const context = { repo: { owner: 'o', repo: 'r' }, ref: 'refs/heads/main', payload };
  await labelConflicts({ github, removeClient, context, core: { warning() {} }, delay: async () => {} });
  return changes;
}

test('blocked label follows merge conflicts, retrying unknown mergeability', async () => {
  const cases = [
    [{ mergeable: 'CONFLICTING' }, [['createLabel', undefined, 'blocked'], ['addLabels', 7, ['blocked']]]],
    [{ mergeable: 'CONFLICTING', labels: ['blocked'] }, []],
    [{ mergeable: 'MERGEABLE' }, []],
    [{ mergeable: 'MERGEABLE', labels: ['blocked'] }, [['removeLabel', 7, 'blocked']]],
    [{ mergeable: 'MERGEABLE', labels: ['blocked'], actor: 'alex' }, []],
    [{ mergeable: 'MERGEABLE', labels: ['blocked'], reviewDecision: 'CHANGES_REQUESTED' }, []],
    [{ mergeable: 'MERGEABLE', labels: ['blocked'], statuses: [{ context: 'dependencies', state: 'pending' }] }, []],
    [{ mergeable: 'MERGEABLE', labels: ['blocked'], statuses: [{ context: 'dependencies', state: 'success' }] }, [['removeLabel', 7, 'blocked']]],
    [{ mergeable: 'UNKNOWN', labels: ['blocked'] }, []],
    [{ mergeable: ['UNKNOWN', 'UNKNOWN', 'MERGEABLE'], labels: ['blocked'] }, [['removeLabel', 7, 'blocked']]],
  ];
  for (const [options, expected] of cases) {
    assert.deepEqual(await run(options), expected, JSON.stringify(options));
  }
});

test('a push checks every open PR on the pushed branch', async () => {
  const changes = await run({ mergeable: ['CONFLICTING', 'CONFLICTING'], open: [{ number: 3, head: { sha: 'a' }, base: { ref: 'main' } }, { number: 4, head: { sha: 'b' }, base: { ref: 'main' } }], payload: {} });
  assert.deepEqual(changes.filter(([kind]) => kind === 'addLabels').map(([, number]) => number), [3, 4]);
});

const required = [{ type: 'required_status_checks', parameters: { required_status_checks: [{ context: 'test' }] } }];
const added = [['createLabel', undefined, 'blocked'], ['addLabels', 7, ['blocked']]];

test('blocked label follows failing required checks on the head commit', async () => {
  const cases = [
    [{ runs: [{ name: 'test', conclusion: 'failure' }] }, added],
    [{ runs: [{ name: 'size-report', conclusion: 'failure' }] }, []],
    [{ runs: [{ name: 'test', conclusion: 'cancelled' }] }, []],
    [{ runs: [{ name: 'test', conclusion: 'failure' }], labels: ['blocked'], mergeable: 'MERGEABLE' }, []],
    [{ runs: [{ name: 'test', conclusion: 'success' }], labels: ['blocked'], mergeable: 'MERGEABLE' }, [['removeLabel', 7, 'blocked']]],
  ];
  for (const [options, expected] of cases) {
    assert.deepEqual(await run({ mergeable: 'MERGEABLE', rules: required, ...options }), expected, JSON.stringify(options));
  }
});

test('a finished CI run checks only the PR with that head commit', async () => {
  const open = [3, 7].map((number) => ({ number, head: { sha: `sha${number}` }, base: { ref: 'main' } }));
  const options = { mergeable: 'MERGEABLE', rules: required, runs: [{ name: 'test', conclusion: 'failure' }], open, payload: { workflow_run: { head_sha: 'sha7' } } };
  assert.deepEqual(await run(options), added);
});
