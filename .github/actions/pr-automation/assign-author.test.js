const test = require('node:test');
const assert = require('node:assert/strict');
const { authorToAssign } = require('./assign-author.js');

test('unassigned PR returns its author', () => {
  assert.equal(authorToAssign({ user: { login: 'octo', type: 'User' }, assignees: [] }), 'octo');
});

test('PR already assigned to its author returns null', () => {
  assert.equal(
    authorToAssign({ user: { login: 'octo', type: 'User' }, assignees: [{ login: 'octo' }] }),
    null
  );
});

test('PR assigned to someone else still returns its author', () => {
  assert.equal(
    authorToAssign({ user: { login: 'octo', type: 'User' }, assignees: [{ login: 'cat' }] }),
    'octo'
  );
});

test('bot-authored PR returns null', () => {
  assert.equal(
    authorToAssign({ user: { login: 'dependabot[bot]', type: 'Bot' }, assignees: [] }),
    null
  );
});
