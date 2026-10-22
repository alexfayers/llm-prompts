const { BLOCKED_LABEL, ensureLabel } = require('../pr-automation/label-pr.js');
const { fetchPr, requiredCheckFailed, clearsBlock } = require('../pr-automation/label-conflicts.js');

const STATUS_CONTEXT = 'dependencies';
const DISPATCH_EVENT = 'dependencies-recheck';
const DEPENDENCY = /(?:depends on|blocked by)\s+(?:https:\/\/github\.com\/)?([\w.-]+\/[\w.-]+)?(?:#|\/(?:pull|issues)\/)(\d+)/gi;

async function setStatus(github, context, pr, state, description) {
  await github.rest.repos.createCommitStatus({
    ...context.repo,
    sha: pr.head.sha,
    context: STATUS_CONTEXT,
    state,
    description,
  });
}

async function canUnblock(github, context, delay, pr) {
  const current = await fetchPr(github, context, pr.number, delay);
  return clearsBlock(current, await requiredCheckFailed(github, context.repo, pr));
}

async function evaluate({ github, removeClient, context, core, delay }, pr) {
  const { owner, repo } = context.repo;
  const open = [];
  for (const [, slug, number] of (pr.body || '').matchAll(DEPENDENCY)) {
    const [depOwner, depRepo] = slug ? slug.split('/') : [owner, repo];
    const { data } = await github.rest.issues.get({ owner: depOwner, repo: depRepo, issue_number: Number(number) });
    if (data.state === 'open') {
      open.push(`${depOwner}/${depRepo}#${number}`);
    }
  }

  const target = { owner, repo, issue_number: pr.number };
  await setStatus(github, context, pr, open.length > 0 ? 'pending' : 'success', open.length > 0 ? `Waiting on ${open.join(', ')}` : 'No open dependencies');
  const labelled = pr.labels.some(({ name }) => name === BLOCKED_LABEL.name);
  if (open.length > 0) {
    if (!labelled) {
      await ensureLabel(github, core, context.repo, BLOCKED_LABEL);
      await github.rest.issues.addLabels({ ...target, labels: [BLOCKED_LABEL.name] });
    }
  } else if (labelled && await canUnblock(github, context, delay, pr)) {
    try {
      await removeClient.rest.issues.removeLabel({ ...target, name: BLOCKED_LABEL.name });
    } catch (error) {
      if (error.status !== 404) {
        throw error;
      }
    }
  }
}

async function isPending(github, context, pr) {
  if (pr.labels.some(({ name }) => name === BLOCKED_LABEL.name)) {
    return true;
  }
  const { data } = await github.rest.repos.listCommitStatusesForRef({ ...context.repo, ref: pr.head.sha });
  return data.find((status) => status.context === STATUS_CONTEXT)?.state === 'pending';
}

function dependsOn(pr, { owner, repo }, target) {
  return [...(pr.body || '').matchAll(DEPENDENCY)].some(([, slug, number]) => `${slug || `${owner}/${repo}`}#${number}` === target);
}

async function pullsToCheck({ github, context }) {
  const { pull_request: event, issue, action } = context.payload;
  if (event && action !== 'closed') {
    return [event];
  }
  const pulls = await github.paginate(github.rest.pulls.list, { ...context.repo, state: 'open' });
  const changed = event ?? issue;
  if (changed) {
    const target = `${context.repo.owner}/${context.repo.repo}#${changed.number}`;
    const dependents = pulls.filter((pr) => dependsOn(pr, context.repo, target));
    return event ? [event, ...dependents] : dependents;
  }
  const verdicts = await Promise.all(pulls.map((pr) => isPending(github, context, pr)));
  return pulls.filter((_, index) => verdicts[index]);
}

async function dispatchCrossRepoDependents({ context, core, client }) {
  const { owner, repo } = context.repo;
  const { pull_request: pull, issue } = context.payload;
  const number = (pull ?? issue).number;
  const target = `${owner}/${repo}#${number}`;
  const items = [];
  for (const phrase of [target, `https://github.com/${owner}/${repo}/${pull ? 'pull' : 'issues'}/${number}`]) {
    items.push(...await client.paginate(client.rest.search.issuesAndPullRequests, { q: `"${phrase}" is:pr is:open user:${owner} in:body` }));
  }
  const repos = new Set();
  for (const item of items) {
    const slug = item.repository_url.split('/repos/')[1];
    const [itemOwner, itemRepo] = slug.split('/');
    if (slug !== `${owner}/${repo}` && dependsOn(item, { owner: itemOwner, repo: itemRepo }, target)) {
      repos.add(slug);
    }
  }
  for (const slug of repos) {
    const [depOwner, depRepo] = slug.split('/');
    try {
      await client.rest.repos.createDispatchEvent({ owner: depOwner, repo: depRepo, event_type: DISPATCH_EVENT });
    } catch (error) {
      core.warning(`Could not dispatch ${DISPATCH_EVENT} to ${slug}: ${error.message}`);
    }
  }
}

async function check({ github, context, core, getOctokit, token, delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) {
  let failure;
  const removeClient = token ? getOctokit(token) : github;
  for (const pr of await pullsToCheck({ github, context })) {
    try {
      await evaluate({ github, removeClient, context, core, delay }, pr);
    } catch (error) {
      await setStatus(github, context, pr, 'error', 'Dependency check failed to run');
      failure ??= error;
    }
  }
  if (token && (context.payload.issue || context.payload.action === 'closed')) {
    await dispatchCrossRepoDependents({ context, core, client: removeClient });
  }
  if (failure) {
    throw failure;
  }
}

module.exports = { check };
