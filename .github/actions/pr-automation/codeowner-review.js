const STATUS_CONTEXT = 'codeowner-review';
const RENOVATE_LOGIN = 'renovate[bot]';
const IGNORED_REVIEW_STATES = ['COMMENTED', 'PENDING'];

async function setStatus(github, context, state, description) {
  await github.rest.repos.createCommitStatus({
    ...context.repo,
    sha: context.payload.pull_request.head.sha,
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

async function evaluate({ github, context }) {
  const pr = context.payload.pull_request;
  const { owner, repo } = context.repo;
  if (pr.user.login === RENOVATE_LOGIN) {
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

async function gate({ github, context }) {
  try {
    await setStatus(github, context, ...(await evaluate({ github, context })));
  } catch (error) {
    await setStatus(github, context, 'error', 'Code owner review check failed to run');
    throw error;
  }
}

module.exports = { gate };
