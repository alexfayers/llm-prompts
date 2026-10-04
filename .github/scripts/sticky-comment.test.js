const test = require('node:test');
const assert = require('node:assert/strict');
const { findStickyComment, upsertStickyComment } = require('./sticky-comment.js');

const MARKER = '<!-- marker -->';
const context = { repo: { owner: 'o', repo: 'r' }, payload: { pull_request: { number: 7 } } };

function fakeGithub(comments = []) {
  const calls = { paginate: [], update: [], create: [] };
  const listComments = () => {};
  return {
    calls,
    paginate: async (fn, params) => {
      calls.paginate.push({ fn, params });
      return comments;
    },
    rest: {
      issues: {
        listComments,
        updateComment: async (params) => calls.update.push(params),
        createComment: async (params) => calls.create.push(params),
      },
    },
  };
}

test('findStickyComment paginates issue comments and returns the one containing the marker', async () => {
  const github = fakeGithub([{ id: 1, body: 'other' }, { id: 2, body: `${MARKER}\nhi` }]);
  const found = await findStickyComment(github, context, MARKER);
  assert.equal(found.id, 2);
  assert.equal(github.calls.paginate[0].fn, github.rest.issues.listComments);
  assert.deepEqual(github.calls.paginate[0].params, {
    owner: 'o',
    repo: 'r',
    issue_number: 7,
    per_page: 100,
  });
});

test('findStickyComment returns undefined when no comment has the marker', async () => {
  const github = fakeGithub([{ id: 1, body: 'other' }]);
  assert.equal(await findStickyComment(github, context, MARKER), undefined);
});

test('upsertStickyComment updates the existing comment by id with the marker prepended to the body', async () => {
  const github = fakeGithub();
  await upsertStickyComment(github, context, MARKER, 'body', { id: 5 });
  assert.deepEqual(github.calls.update, [{ owner: 'o', repo: 'r', comment_id: 5, body: `${MARKER}\nbody` }]);
  assert.equal(github.calls.create.length, 0);
});

test('upsertStickyComment creates a comment when none exists', async () => {
  const github = fakeGithub();
  await upsertStickyComment(github, context, MARKER, 'body', undefined);
  assert.deepEqual(github.calls.create, [{ owner: 'o', repo: 'r', issue_number: 7, body: `${MARKER}\nbody` }]);
  assert.equal(github.calls.update.length, 0);
});
