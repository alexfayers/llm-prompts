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

test('check labels the PR with the worst yappy tier and posts one comment', async () => {
  const calls = [];
  const files = [
    { filename: 'src/app.js', patch: Array.from({ length: 150 }, (_, i) => `+code ${i}`).join('\n') + '\n+moved line\n+\n+}' },
    { filename: 'src/old.js', patch: '-moved line\n-}' },
    { filename: 'tests/app.test.js', patch: Array.from({ length: 60 }, (_, i) => `+test ${i}`).join('\n') },
    { filename: 'package-lock.json', patch: '+lock' },
  ];
  const github = {
    paginate: async (method) => (method === github.rest.pulls.listFiles ? files : []),
    rest: {
      pulls: { listFiles: () => {} },
      issues: {
        removeLabel: async ({ name }) => calls.push(['removeLabel', name]),
        addLabels: async ({ labels }) => calls.push(['addLabels', labels]),
        createComment: async ({ body }) => calls.push(['createComment', body]),
      },
    },
  };
  const pr = {
    number: 7,
    labels: [{ name: 'very yappy' }],
    body: `## What\n\n${'word '.repeat(130)}\n\n## Why\n\nBecause.`,
  };
  const context = { repo: { owner: 'o', repo: 'r' }, payload: { pull_request: pr } };
  const core = { warning() {}, setFailed() {} };

  await check({ github, context, core });

  assert.deepEqual(calls.slice(0, 2), [['removeLabel', 'very yappy'], ['addLabels', ['yappy']]]);
  assert.equal(calls.length, 3);
  assert.match(calls[2][1], /131 words/);
  assert.match(calls[2][1], /152 code, 60 test/);
});
