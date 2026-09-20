const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveTypeLabel, hasBreakingChange } = require('./label-pr.js');

test('feat maps to enhancement', () => {
  assert.equal(resolveTypeLabel('feat: add widget'), 'enhancement');
});

test('fix maps to bug', () => {
  assert.equal(resolveTypeLabel('fix: broken widget'), 'bug');
});

test('docs maps to documentation', () => {
  assert.equal(resolveTypeLabel('docs: update readme'), 'documentation');
});

test('chore maps to chore', () => {
  assert.equal(resolveTypeLabel('chore: bump deps'), 'chore');
});

test('refactor maps to refactor', () => {
  assert.equal(resolveTypeLabel('refactor: simplify parser'), 'refactor');
});

test('ci maps to ci', () => {
  assert.equal(resolveTypeLabel('ci: add workflow'), 'ci');
});

test('build and style map to chore', () => {
  assert.equal(resolveTypeLabel('build: bump esbuild'), 'chore');
  assert.equal(resolveTypeLabel('style: reformat'), 'chore');
});

test('perf and test map to null', () => {
  assert.equal(resolveTypeLabel('perf: speed up loop'), null);
  assert.equal(resolveTypeLabel('test: add coverage'), null);
});

test('scoped type prefix is still recognized', () => {
  assert.equal(resolveTypeLabel('feat(scope): add widget'), 'enhancement');
});

test('unrecognized type maps to null', () => {
  assert.equal(resolveTypeLabel('wip: exploring'), null);
});

test('title without conventional prefix maps to null', () => {
  assert.equal(resolveTypeLabel('add widget'), null);
});

test('bang before colon marks breaking regardless of body', () => {
  assert.equal(hasBreakingChange('feat!: drop old api', ''), true);
});

test('scoped bang before colon marks breaking', () => {
  assert.equal(hasBreakingChange('feat(scope)!: drop old api', ''), true);
});

test('BREAKING CHANGE footer marks breaking', () => {
  assert.equal(
    hasBreakingChange('feat: add widget', 'Some body.\n\nBREAKING CHANGE: removes old api'),
    true
  );
});

test('no bang and no footer is not breaking', () => {
  assert.equal(hasBreakingChange('feat: add widget', 'Just a normal change.'), false);
});

test('missing body does not throw', () => {
  assert.equal(hasBreakingChange('feat: add widget', undefined), false);
});
