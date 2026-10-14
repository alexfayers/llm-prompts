const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { isBlocked, resolveStatus } = require('./sync-project-status.js');

const openPr = { state: 'OPEN', isDraft: false, reviewDecision: null };
const reviewedAs = (...states) => ({ latestOpinionatedReviews: { nodes: states.map((state) => ({ state })) } });

test('open draft PR maps to In Progress and open ready PR to Review', () => {
  assert.equal(resolveStatus({ ...openPr, isDraft: true }), '47fc9ee4');
  assert.equal(resolveStatus(openPr), '432b1b61');
});

test('approved PR maps to Approved unless changes are also requested', () => {
  assert.equal(resolveStatus({ ...openPr, ...reviewedAs('APPROVED') }), 'c6f50cd1');
  assert.equal(resolveStatus({ ...openPr, ...reviewedAs('APPROVED', 'CHANGES_REQUESTED') }), '432b1b61');
});

test('blocked PRs keep their draft, review or approved status', () => {
  for (const blocker of [{ reviewDecision: 'CHANGES_REQUESTED' }]) {
    assert.equal(resolveStatus({ ...openPr, ...blocker }), '432b1b61');
    assert.equal(resolveStatus({ ...openPr, ...blocker, isDraft: true }), '47fc9ee4');
  }
  assert.equal(resolveStatus({ ...openPr, ...reviewedAs('APPROVED'), isDraft: true }), '47fc9ee4');
});

test('closed or merged PR maps to Done even with requested changes', () => {
  const reviewDecision = 'CHANGES_REQUESTED';
  assert.equal(resolveStatus({ ...openPr, state: 'CLOSED', reviewDecision }), '98236657');
  assert.equal(resolveStatus({ ...openPr, state: 'MERGED', reviewDecision }), '98236657');
});

test('status resolution never references the Triage option', () => {
  const source = fs.readFileSync(path.join(__dirname, 'sync-project-status.js'), 'utf8');
  assert.doesNotMatch(source, /triage/i);
});

test('PR is blocked by requested changes only', () => {
  assert.equal(isBlocked({ ...openPr, reviewDecision: 'CHANGES_REQUESTED' }), true);
  assert.equal(isBlocked({ ...openPr, reviewDecision: 'APPROVED' }), false);
});
