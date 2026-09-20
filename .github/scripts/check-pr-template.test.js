const test = require('node:test');
const assert = require('node:assert/strict');
const { parseTemplateSections, findBodyIssues } = require('./check-pr-template.js');

const TEMPLATE = `## Summary

<!-- Summarize the change. -->

## Rationale

<!-- Explain why. -->

## Checks

- [ ] Do the thing
`;

test('parseTemplateSections extracts ordered sections and Checks items', () => {
  const parsed = parseTemplateSections(TEMPLATE);
  assert.deepEqual(parsed.sections.map((s) => s.heading), ['Summary', 'Rationale', 'Checks']);
  assert.deepEqual(parsed.checklistItems, ['Do the thing']);
});

test('findBodyIssues passes a fully filled-in PR body', () => {
  const parsed = parseTemplateSections(TEMPLATE);
  const body = `## Summary

Added a new widget.

## Rationale

Users asked for it.

## Checks

- [x] Do the thing
`;

  assert.deepEqual(findBodyIssues(parsed, body), []);
});

test('findBodyIssues fails when an entire section is missing', () => {
  const parsed = parseTemplateSections(TEMPLATE);
  const body = `## Summary

Added a new widget.

## Checks

- [x] Do the thing
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

## Checks

- [x] Do the thing
`;

  const issues = findBodyIssues(parsed, body);
  assert.equal(issues.length, 1);
  assert.match(issues[0], /## Rationale/);
});

test('findBodyIssues fails when a Checks item text is deleted', () => {
  const parsed = parseTemplateSections(TEMPLATE);
  const body = `## Summary

Added a new widget.

## Rationale

Users asked for it.

## Checks

- [ ]
`;

  const issues = findBodyIssues(parsed, body);
  assert.equal(issues.length, 1);
  assert.match(issues[0], /Do the thing/);
});
