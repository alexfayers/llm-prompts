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
  assert.ok(issues.some((issue) => /## Rationale.*empty/.test(issue)));
});

test('findBodyIssues fails when a placeholder comment is left in a filled body', () => {
  const parsed = parseTemplateSections(TEMPLATE);
  const body = `## Summary

Added a new widget.

## Rationale

Users asked for it.

## Dependencies

<!-- Depends on #N -->
`;

  const issues = findBodyIssues(parsed, body);
  assert.equal(issues.length, 1);
  assert.match(issues[0], /<!--/);
});

const lines = (prefix, count) => Array.from({ length: count }, (_, i) => `+${prefix} ${i}`).join('\n');
const MARKER = '<!-- pr-yappy-check -->\n';

async function runCheck({ files, body = '## What\n\nA.\n\n## Why\n\nB.', staleBody = body, labels = [], comments = [], user, core = {} }) {
  const calls = [];
  const record = (name, key) => async (args) => calls.push([name, args[key]]);
  const github = {
    paginate: async (method) => (method === github.rest.pulls.listFiles ? files : comments),
    rest: {
      pulls: { listFiles: () => {}, get: async () => ({ data: { body } }) },
      issues: {
        removeLabel: record('removeLabel', 'name'),
        addLabels: record('addLabels', 'labels'),
        createComment: record('createComment', 'body'),
        updateComment: record('updateComment', 'body'),
      },
    },
  };
  const pull_request = { number: 7, labels: labels.map((name) => ({ name })), body: staleBody, user };
  await check({ github, context: { repo: { owner: 'o', repo: 'r' }, payload: { pull_request } }, core });
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
  assert.match(calls[2][1], /- Changed lines: 213 \(yappy above 200 total, moved lines and lockfiles excluded\)/);
  assert.match(calls[2][1], /- Code lines: \+152 new \/ -1 old \(net \+151\)\n- Test lines: \+60 new \/ -0 old \(net \+60\)/);
});

test('check counts the lines of a deleted file toward the tier', async () => {
  const files = [
    { filename: 'src/gone.js', status: 'removed', patch: lines('gone', 150).replaceAll('+', '-') },
    { filename: 'src/app.js', patch: '+code' },
  ];
  const calls = await runCheck({ files });

  assert.deepEqual(calls.slice(0, 1), [['addLabels', ['slightly yappy']]]);
});

test('check ignores a file moved by deleting it and adding it elsewhere', async () => {
  const files = [
    { filename: 'src/old.js', status: 'removed', patch: lines('moved', 150).replaceAll('+', '-') },
    { filename: 'src/new.js', patch: lines('moved', 150) },
  ];
  const calls = await runCheck({ files });

  assert.deepEqual(calls, []);
});

test('check counts additions and deletions of a file without a patch', async () => {
  const files = [{ filename: 'tests/big.test.js', additions: 5, deletions: 500 }];
  const calls = await runCheck({ files });

  assert.deepEqual(calls.slice(0, 1), [['addLabels', ['very yappy']]]);
  assert.match(calls[1][1], /- Test lines: \+5 new \/ -500 old \(net -495\)/);
});

test('check ignores deleted test lines when comparing test to code', async () => {
  const files = [
    { filename: 'src/app.js', patch: lines('code', 2) },
    { filename: 'tests/app.test.js', patch: `+test\n${lines('gone', 5).replaceAll('+', '-')}` },
  ];
  const calls = await runCheck({ files });

  assert.deepEqual(calls, []);
});

test('check warns about more test lines than code without a tier', async () => {
  const files = [
    { filename: 'src/app.js', patch: '+code' },
    { filename: 'tests/app.test.js', patch: `${lines('test', 2)}\n-old 0\n-old 1` },
  ];
  const calls = await runCheck({ files });

  assert.deepEqual(calls.map(([name]) => name), ['createComment']);
  assert.match(calls[0][1], /- Changed lines: 5 \(moved lines and lockfiles excluded\)/);
  assert.match(calls[0][1], /- Code lines: \+1 new \/ -0 old \(net \+1\)\n- Test lines: \+2 new \/ -2 old \(net 0\)/);
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

test('check validates the live PR body, not the event payload body', async () => {
  const failures = [];
  const calls = await runCheck({ files: [], body: '## What\n\nA.', staleBody: '## What\n\nA.\n\n## Why\n\nB.', core: { setFailed: (message) => failures.push(message) } });

  assert.equal(failures.length, 1);
  assert.match(failures[0], /Missing section: "## Why"/);
  assert.deepEqual(calls.map(([name]) => name), ['createComment']);
});
