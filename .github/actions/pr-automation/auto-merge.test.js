const test = require('node:test');
const assert = require('node:assert/strict');
const { isContributeBranch } = require('./auto-merge.js');

test('contribute batch branch matches', () => {
  assert.equal(isContributeBranch('octo/contribute/foo'), true);
});

test('non-contribute branch is rejected', () => {
  assert.equal(isContributeBranch('octo/feature'), false);
});

test('branch without a login prefix is rejected', () => {
  assert.equal(isContributeBranch('contribute/foo'), false);
});

test('main is rejected', () => {
  assert.equal(isContributeBranch('main'), false);
});

test('nested prefix before contribute is rejected', () => {
  assert.equal(isContributeBranch('a/b/contribute/c'), false);
});
