const { findPr, isBlocked } = require('./sync-project-status.js');

const BLOCKED_LABEL = { name: 'blocked', color: 'd73a4a', description: 'Open dependencies or changes requested' };

const CONVENTIONAL_PREFIX = /^(\w+)(\([^)]*\))?(!)?:\s/;

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
  if (!hasBreakingChange(pr.title, pr.body)) {
    return;
  }

  await addLabels(github, core, { ...context.repo, issue_number: pr.number }, ['breaking']);
}

async function labelBlocked({ github, context, core }) {
  const pr = await findPr(github, context, core);
  if (!pr || pr.state !== 'OPEN') {
    return;
  }
  const blocked = isBlocked(pr);
  const labelled = pr.labels.nodes.some(({ name }) => name === BLOCKED_LABEL.name);
  const target = { ...context.repo, issue_number: pr.number };

  if (blocked && !labelled) {
    await ensureLabel(github, core, context.repo, BLOCKED_LABEL);
    await addLabels(github, core, target, [BLOCKED_LABEL.name]);
  }
}

module.exports = { hasBreakingChange, label, labelBlocked, ensureLabel, BLOCKED_LABEL };
