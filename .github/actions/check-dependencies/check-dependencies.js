const { BLOCKED_LABEL, ensureLabel } = require('../pr-automation/label-pr.js');

const STATUS_CONTEXT = 'dependencies';
const DEPENDENCY = /(?:depends on|blocked by)\s+(?:https:\/\/github\.com\/)?([\w.-]+\/[\w.-]+)?(?:#|\/(?:pull|issues)\/)(\d+)/gi;

async function setStatus(github, context, state, description) {
  await github.rest.repos.createCommitStatus({
    ...context.repo,
    sha: context.payload.pull_request.head.sha,
    context: STATUS_CONTEXT,
    state,
    description,
  });
}

async function evaluate({ github, context, core }) {
  const pr = context.payload.pull_request;
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
  await setStatus(github, context, open.length > 0 ? 'pending' : 'success', open.length > 0 ? `Waiting on ${open.join(', ')}` : 'No open dependencies');
  const labelled = pr.labels.some(({ name }) => name === BLOCKED_LABEL.name);
  if (open.length > 0) {
    if (!labelled) {
      await ensureLabel(github, core, context.repo, BLOCKED_LABEL);
      await github.rest.issues.addLabels({ ...target, labels: [BLOCKED_LABEL.name] });
    }
  } else if (labelled) {
    await github.rest.issues.removeLabel({ ...target, name: BLOCKED_LABEL.name });
  }
}

async function check({ github, context, core }) {
  try {
    await evaluate({ github, context, core });
  } catch (error) {
    await setStatus(github, context, 'error', 'Dependency check failed to run');
    throw error;
  }
}

module.exports = { check };
