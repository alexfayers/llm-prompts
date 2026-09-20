const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveStatus } = require('./sync-project-status.js');

test('opened draft PR maps to In Progress', () => {
  const status = resolveStatus('pull_request_target', {
    action: 'opened',
    pull_request: { draft: true },
  });
  assert.equal(status, '47fc9ee4');
});

test('opened non-draft PR maps to Review', () => {
  const status = resolveStatus('pull_request_target', {
    action: 'opened',
    pull_request: { draft: false },
  });
  assert.equal(status, '432b1b61');
});

test('reopened draft PR maps to In Progress', () => {
  const status = resolveStatus('pull_request_target', {
    action: 'reopened',
    pull_request: { draft: true },
  });
  assert.equal(status, '47fc9ee4');
});

test('reopened non-draft PR maps to Review', () => {
  const status = resolveStatus('pull_request_target', {
    action: 'reopened',
    pull_request: { draft: false },
  });
  assert.equal(status, '432b1b61');
});

test('converted_to_draft maps to In Progress', () => {
  const status = resolveStatus('pull_request_target', {
    action: 'converted_to_draft',
    pull_request: { draft: true },
  });
  assert.equal(status, '47fc9ee4');
});

test('ready_for_review maps to Review', () => {
  const status = resolveStatus('pull_request_target', {
    action: 'ready_for_review',
    pull_request: { draft: false },
  });
  assert.equal(status, '432b1b61');
});

test('closed maps to Done regardless of merged state', () => {
  const merged = resolveStatus('pull_request_target', {
    action: 'closed',
    pull_request: { merged: true },
  });
  const notMerged = resolveStatus('pull_request_target', {
    action: 'closed',
    pull_request: { merged: false },
  });
  assert.equal(merged, '98236657');
  assert.equal(notMerged, '98236657');
});

test('edited and synchronize map to null', () => {
  assert.equal(
    resolveStatus('pull_request_target', { action: 'edited', pull_request: {} }),
    null
  );
  assert.equal(
    resolveStatus('pull_request_target', { action: 'synchronize', pull_request: {} }),
    null
  );
});

test('review submitted approved maps to Approved', () => {
  const status = resolveStatus('pull_request_review', {
    action: 'submitted',
    review: { state: 'approved' },
  });
  assert.equal(status, 'c6f50cd1');
});

test('review submitted changes_requested maps to Review', () => {
  const status = resolveStatus('pull_request_review', {
    action: 'submitted',
    review: { state: 'changes_requested' },
  });
  assert.equal(status, '432b1b61');
});

test('review submitted commented maps to null', () => {
  const status = resolveStatus('pull_request_review', {
    action: 'submitted',
    review: { state: 'commented' },
  });
  assert.equal(status, null);
});

test('unrelated events map to null', () => {
  assert.equal(resolveStatus('push', {}), null);
});
