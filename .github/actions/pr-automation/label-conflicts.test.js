const test = require('node:test');
const assert = require('node:assert/strict');
const { labelConflicts } = require('./label-conflicts.js');

async function run({ mergeable, labels = [], reviewDecision = null, actor = 'github-actions[bot]', open = [], payload = { pull_request: { number: 7 } } }) {
  const changes = [];
  const states = [].concat(mergeable);
  const record = (kind) => async (args) => changes.push([kind, args.issue_number, args.labels ?? args.name]);
  const labelEvent = (login, name = 'blocked') => ({ event: 'labeled', label: { name }, actor: { login } });
  const github = {
    graphql: async () => ({ repository: { pullRequest: { reviewDecision, mergeable: states.shift() ?? 'UNKNOWN', labels: { nodes: labels.map((name) => ({ name })) } } } }),
    paginate: async (method) => (method === 'pulls' ? open : [labelEvent('someone'), labelEvent(actor), labelEvent('someone', 'other')]),
    rest: { pulls: { list: 'pulls' }, issues: { createLabel: record('createLabel'), addLabels: record('addLabels'), removeLabel: record('removeLabel') } },
  };
  const context = { repo: { owner: 'o', repo: 'r' }, ref: 'refs/heads/main', payload };
  await labelConflicts({ github, context, core: { warning() {} }, delay: async () => {} });
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
    [{ mergeable: 'UNKNOWN', labels: ['blocked'] }, []],
    [{ mergeable: ['UNKNOWN', 'UNKNOWN', 'MERGEABLE'], labels: ['blocked'] }, [['removeLabel', 7, 'blocked']]],
  ];
  for (const [options, expected] of cases) {
    assert.deepEqual(await run(options), expected, JSON.stringify(options));
  }
});

test('a push checks every open PR on the pushed branch', async () => {
  const changes = await run({ mergeable: ['CONFLICTING', 'CONFLICTING'], open: [{ number: 3 }, { number: 4 }], payload: {} });
  assert.deepEqual(changes.filter(([kind]) => kind === 'addLabels').map(([, number]) => number), [3, 4]);
});
