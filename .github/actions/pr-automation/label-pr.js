const { findDependencyCheck, findPr, isBlocked } = require('./sync-project-status.js');

const BLOCKED_LABEL = { name: 'blocked', color: 'd73a4a', description: 'Failed dependency check or changes requested' };

const TYPE_TO_LABEL = {
  feat: 'enhancement',
  fix: 'bug',
  docs: 'documentation',
  chore: 'chore',
  refactor: 'refactor',
  ci: 'ci',
  build: 'chore',
  style: 'chore',
  perf: null,
  test: null,
};

const MANAGED_TYPE_LABELS = ['enhancement', 'bug', 'documentation', 'chore', 'refactor', 'ci'];

const CONVENTIONAL_PREFIX = /^(\w+)(\([^)]*\))?(!)?:\s/;

function resolveTypeLabel(title) {
  const match = CONVENTIONAL_PREFIX.exec(title);
  if (!match) {
    return null;
  }
  return TYPE_TO_LABEL[match[1].toLowerCase()] ?? null;
}

function hasBreakingChange(title, body) {
  const match = CONVENTIONAL_PREFIX.exec(title);
  if (match && match[3] === '!') {
    return true;
  }
  return /BREAKING[- ]CHANGE/.test(body || '');
}

async function removeLabel(github, core, target, name) {
  try {
    await github.rest.issues.removeLabel({ ...target, name });
  } catch (error) {
    core.warning(`Failed to remove label "${name}": ${error.message}`);
  }
}

async function addLabels(github, core, target, labels) {
  try {
    await github.rest.issues.addLabels({ ...target, labels });
  } catch (error) {
    core.warning(`Failed to add labels [${labels.join(', ')}]: ${error.message}`);
  }
}

async function ensureLabel(github, core, { owner, repo }, { name, color, description }) {
  try {
    await github.rest.issues.createLabel({ owner, repo, name, color, description });
  } catch (error) {
    if (error.status !== 422) {
      core.warning(`Failed to create label "${name}": ${error.message}`);
    }
  }
}

async function label({ github, context, core }) {
  const pr = context.payload.pull_request;
  const typeLabel = resolveTypeLabel(pr.title);
  const breaking = hasBreakingChange(pr.title, pr.body);
  const target = { ...context.repo, issue_number: pr.number };

  if (context.payload.action === 'edited') {
    const current = pr.labels.map((l) => l.name);
    const toRemove = current.filter(
      (name) => MANAGED_TYPE_LABELS.includes(name) && name !== typeLabel
    );
    for (const name of toRemove) {
      await removeLabel(github, core, target, name);
    }
  }

  const toAdd = [typeLabel, breaking ? 'breaking' : null].filter(Boolean);
  if (toAdd.length === 0) {
    return;
  }

  await addLabels(github, core, target, toAdd);
}

async function labelBlocked({ github, context, core }) {
  const pr = await findPr(github, context, core);
  if (!pr || pr.state !== 'OPEN') {
    return;
  }
  const dependencyCheck = await findDependencyCheck(github, core, context.repo, pr.headRefOid);
  const blocked = isBlocked({ ...pr, dependencyCheck });
  const labelled = pr.labels.nodes.some(({ name }) => name === BLOCKED_LABEL.name);
  const target = { ...context.repo, issue_number: pr.number };

  if (blocked && !labelled) {
    await ensureLabel(github, core, context.repo, BLOCKED_LABEL);
    await addLabels(github, core, target, [BLOCKED_LABEL.name]);
  } else if (!blocked && labelled && dependencyCheck !== null) {
    await removeLabel(github, core, target, BLOCKED_LABEL.name);
  }
}

module.exports = { resolveTypeLabel, hasBreakingChange, label, labelBlocked };
