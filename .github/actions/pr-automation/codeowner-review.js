const { findPullRequest } = require('./sync-project-status.js');

const STATUS_CONTEXT = 'codeowner-review';
const RENOVATE_LOGIN = 'renovate[bot]';
const SAFE_RENOVATE_BRANCHES = ['renovate/all-minor-patch', 'renovate/github-actions', 'renovate/lock-file-maintenance'];
const IGNORED_REVIEW_STATES = ['COMMENTED', 'PENDING'];

async function setStatus(github, context, pr, state, description) {
  await github.rest.repos.createCommitStatus({
    ...context.repo,
    sha: pr.head.sha,
    context: STATUS_CONTEXT,
    state,
    description,
  });
}

function patternToRegExp(pattern) {
  const body = pattern.replace(/^\/|\/$/g, '');
  const head = pattern.replace(/\/$/, '').includes('/') ? '' : '(?:.*/)?';
  const tail = pattern.endsWith('/') ? '/.*' : /[*?][^/]*$/.test(body) ? '' : '(?:/.*)?';
  const source = body.replace(/(^|\/)\*\*(?:\/|$)|\*+|\?|[.+^${}()|[\]\\]/g, (token, lead) => (lead !== undefined ? lead + (token.endsWith('/') ? '(?:.*/)?' : '.*') : token[0] === '*' ? '[^/]*' : token === '?' ? '[^/]' : `\\${token}`));
  return new RegExp(`^${head}${source}${tail}$`);
}

async function readCodeOwners(github, { owner, repo }, ref) {
  const { data } = await github.rest.repos.getContent({ owner, repo, path: 'CODEOWNERS', ref });
  return Buffer.from(data.content, 'base64').toString().split('\n')
    .map((line) => line.replace(/#.*/, '').trim())
    .filter(Boolean)
    .map((line) => ({ pattern: patternToRegExp(line.split(/\s+/)[0]), owners: (line.match(/@[\w-]+/g) ?? []).map((handle) => handle.slice(1).toLowerCase()) }));
}

function latestReviewStates(reviews) {
  const states = new Map();
  for (const { user, state } of reviews) {
    if (!IGNORED_REVIEW_STATES.includes(state)) {
      states.set(user.login.toLowerCase(), state);
    }
  }
  return states;
}

async function evaluate({ github, context, pr }) {
  const { owner, repo } = context.repo;
  if (pr.user.login === RENOVATE_LOGIN && SAFE_RENOVATE_BRANCHES.includes(pr.head.ref)) {
    return ['success', 'Renovate PR needs no code owner review'];
  }
  const author = pr.user.login.toLowerCase();
  const files = await github.paginate(github.rest.pulls.listFiles, { owner, repo, pull_number: pr.number, per_page: 100 });
  const rules = await readCodeOwners(github, context.repo, pr.base.ref);
  const needsReview = (path) => rules.findLast(({ pattern }) => pattern.test(path))?.owners.some((handle) => handle !== author);
  if (!files.some(({ filename, previous_filename }) => [filename, previous_filename].some((path) => path && needsReview(path)))) {
    return ['success', 'No code owner review needed'];
  }

  const owners = new Set(rules.flatMap((rule) => rule.owners));
  const reviews = await github.paginate(github.rest.pulls.listReviews, { owner, repo, pull_number: pr.number, per_page: 100 });
  const states = [...latestReviewStates(reviews)].filter(([login]) => owners.has(login) && login !== author);
  if (states.some(([, state]) => state === 'CHANGES_REQUESTED')) {
    return ['pending', 'Code owner requested changes'];
  }
  return states.some(([, state]) => state === 'APPROVED') ? ['success', 'Approved by a code owner'] : ['pending', 'Needs a code owner approval'];
}

function minReviews(labels) {
  const counts = labels.map(({ name }) => /^min-reviews:([12])$/.exec(name)?.[1]).filter(Boolean).map(Number);
  return counts.length ? Math.max(...counts) : 0;
}

async function evaluateMinReviews({ github, context, pr }) {
  const needed = minReviews(pr.labels ?? []);
  if (needed === 0) {
    return null;
  }
  const reviews = await github.paginate(github.rest.pulls.listReviews, { ...context.repo, pull_number: pr.number, per_page: 100 });
  const author = pr.user.login.toLowerCase();
  const approvals = [...latestReviewStates(reviews)].filter(([login, state]) => login !== author && state === 'APPROVED').length;
  return approvals >= needed ? null : ['pending', `Needs ${needed} approval${needed > 1 ? 's' : ''} (${approvals} so far)`];
}

async function gate({ github, context }) {
  const pr = await findPullRequest(github, context);
  if (!pr) {
    return;
  }
  try {
    const result = await evaluate({ github, context, pr });
    const required = result[0] === 'success' ? await evaluateMinReviews({ github, context, pr }) : null;
    await setStatus(github, context, pr, ...(required ?? result));
  } catch (error) {
    await setStatus(github, context, pr, 'error', 'Code owner review check failed to run');
    throw error;
  }
}

module.exports = { gate };
