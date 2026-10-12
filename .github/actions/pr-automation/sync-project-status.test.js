const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { isBlocked, latestCheck, resolveStatus } = require('./sync-project-status.js');

const openPr = { state: 'OPEN', isDraft: false, reviewDecision: null, dependencyCheck: null };

test('open draft PR maps to In Progress and open ready PR to Review', () => {
  assert.equal(resolveStatus({ ...openPr, isDraft: true }), '47fc9ee4');
  assert.equal(resolveStatus(openPr), '432b1b61');
});

test('approved PR maps to Approved', () => {
  assert.equal(resolveStatus({ ...openPr, reviewDecision: 'APPROVED' }), 'c6f50cd1');
});

test('blocked PRs keep their draft, review or approved status', () => {
  for (const blocker of [{ dependencyCheck: 'failure' }, { reviewDecision: 'CHANGES_REQUESTED' }]) {
    assert.equal(resolveStatus({ ...openPr, ...blocker }), '432b1b61');
    assert.equal(resolveStatus({ ...openPr, ...blocker, isDraft: true }), '47fc9ee4');
  }
  assert.equal(resolveStatus({ ...openPr, dependencyCheck: 'failure', reviewDecision: 'APPROVED' }), 'c6f50cd1');
});

test('closed or merged PR maps to Done even with a failed dependency check', () => {
  const dependencyCheck = 'failure';
  assert.equal(resolveStatus({ ...openPr, state: 'CLOSED', dependencyCheck }), '98236657');
  assert.equal(resolveStatus({ ...openPr, state: 'MERGED', dependencyCheck }), '98236657');
});

test('status resolution never references the Triage option', () => {
  const source = fs.readFileSync(path.join(__dirname, 'sync-project-status.js'), 'utf8');
  assert.doesNotMatch(source, /triage/i);
});

test('latestCheck returns the completed check run that started last, or null', () => {
  const runs = [
    { status: 'completed', conclusion: 'failure', started_at: '2026-10-11T10:00:00Z' },
    { status: 'completed', conclusion: 'success', started_at: '2026-10-11T11:00:00Z' },
    { status: 'in_progress', conclusion: null, started_at: '2026-10-11T12:00:00Z' },
  ];
  assert.equal(latestCheck(runs), runs[1]);
  assert.equal(latestCheck([runs[2]]), null);
  assert.equal(latestCheck([]), null);
});

test('PR is blocked by a failed dependency check or requested changes only', () => {
  assert.equal(isBlocked({ ...openPr, dependencyCheck: 'failure' }), true);
  assert.equal(isBlocked({ ...openPr, reviewDecision: 'CHANGES_REQUESTED' }), true);
  for (const dependencyCheck of ['success', 'cancelled', null]) {
    assert.equal(isBlocked({ ...openPr, dependencyCheck, reviewDecision: 'APPROVED' }), false);
  }
});
