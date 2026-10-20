const test = require('node:test');
const assert = require('node:assert/strict');
const { parseTemplateSections, findBodyIssues, check } = require('./check-pr-template.js');

const TEMPLATE = `## Summary

<!-- Summarize the change. -->

## Rationale

<!-- Explain why. -->

## Dependencies

<!-- Depends on #N -->

## Issues

<!-- Closes #N -->
`;

test('parseTemplateSections extracts ordered sections', () => {
  const parsed = parseTemplateSections(TEMPLATE);
  assert.deepEqual(parsed.sections.map((s) => s.heading), ['Summary', 'Rationale', 'Dependencies', 'Issues']);
});

test('findBodyIssues passes a fully filled-in PR body', () => {
  const parsed = parseTemplateSections(TEMPLATE);
  const body = `## Summary

Added a new widget.

## Rationale

Users asked for it.
`;

  assert.deepEqual(findBodyIssues(parsed, body), []);
});

test('findBodyIssues fails when an entire section is missing', () => {
  const parsed = parseTemplateSections(TEMPLATE);
  const body = `## Summary

Added a new widget.
`;

  const issues = findBodyIssues(parsed, body);
  assert.equal(issues.length, 1);
  assert.match(issues[0], /## Rationale/);
});

test('findBodyIssues fails when a section is left as only the placeholder comment', () => {
  const parsed = parseTemplateSections(TEMPLATE);
  const body = `## Summary

Added a new widget.

## Rationale

<!-- Explain why. -->
`;

  const issues = findBodyIssues(parsed, body);
  assert.equal(issues.length, 1);
  assert.match(issues[0], /## Rationale/);
});

const lines = (prefix, count) => Array.from({ length: count }, (_, i) => `+${prefix} ${i}`).join('\n');
const MARKER = '<!-- pr-yappy-check -->\n';

async function runCheck({ files, body = '## What\n\nA.\n\n## Why\n\nB.', labels = [], comments = [], user }) {
  const calls = [];
  const record = (name, key) => async (args) => calls.push([name, args[key]]);
  const github = {
    paginate: async (method) => (method === github.rest.pulls.listFiles ? files : comments),
    rest: {
      pulls: { listFiles: () => {} },
      issues: {
        removeLabel: record('removeLabel', 'name'),
        addLabels: record('addLabels', 'labels'),
        createComment: record('createComment', 'body'),
        updateComment: record('updateComment', 'body'),
      },
    },
  };
  const pull_request = { number: 7, labels: labels.map((name) => ({ name })), body, user };
  await check({ github, context: { repo: { owner: 'o', repo: 'r' }, payload: { pull_request } }, core: {} });
  return calls;
}

test('check swaps the yappy label and posts one comment with the tier suffix', async () => {
  const files = [
    { filename: 'src/app.js', patch: `${lines('code', 150)}\n+moved line\n+\n+}` },
    { filename: 'src/old.js', patch: '-moved line\n-}' },
    { filename: 'tests/app.test.js', patch: lines('test', 60) },
    { filename: 'package-lock.json', patch: '+lock' },
    { filename: 'pnpm-lock.yaml', patch: '+lock' },
  ];
  const body = `## What\n\n${'word '.repeat(130)}\n\n## Why\n\nBecause.`;
  const calls = await runCheck({ files, body, labels: ['very yappy'] });

  assert.deepEqual(calls.slice(0, 2), [['removeLabel', 'very yappy'], ['addLabels', ['yappy']]]);
  assert.equal(calls.length, 3);
  assert.match(calls[2][1], /131 words/);
  assert.match(calls[2][1], /152 code, 60 test \(yappy above 200 total, lockfiles excluded\)/);
});

test('check warns about more test lines than code without a tier', async () => {
  const files = [{ filename: 'src/app.js', patch: '+code' }, { filename: 'tests/app.test.js', patch: lines('test', 2) }];
  const calls = await runCheck({ files });

  assert.deepEqual(calls.map(([name]) => name), ['createComment']);
  assert.match(calls[0][1], /1 code, 2 test \(lockfiles excluded\)/);
  assert.match(calls[0][1], /More test lines than code is kinda CRAZY/);
});

test('check clears an existing warning once the PR is no longer yappy', async () => {
  const files = [{ filename: 'src/app.js', patch: lines('code', 2) }];
  const calls = await runCheck({ files, comments: [{ id: 1, body: `${MARKER}warning` }] });

  assert.deepEqual(calls, [['updateComment', `${MARKER}This PR is no longer yappy.`]]);
});

test('check passes a bot PR whose body ignores the template', async () => {
  const calls = await runCheck({ files: [], body: 'Update dependency', user: { type: 'Bot' } });

  assert.deepEqual(calls, []);
});
