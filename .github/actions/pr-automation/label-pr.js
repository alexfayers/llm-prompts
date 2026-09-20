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

async function label({ github, context, core }) {
  const pr = context.payload.pull_request;
  const typeLabel = resolveTypeLabel(pr.title);
  const breaking = hasBreakingChange(pr.title, pr.body);
  const owner = context.repo.owner;
  const repo = context.repo.repo;
  const issue_number = pr.number;

  if (context.payload.action === 'edited') {
    const current = pr.labels.map((l) => l.name);
    const toRemove = current.filter(
      (name) => MANAGED_TYPE_LABELS.includes(name) && name !== typeLabel
    );
    for (const name of toRemove) {
      try {
        await github.rest.issues.removeLabel({ owner, repo, issue_number, name });
      } catch (error) {
        core.warning(`Failed to remove label "${name}": ${error.message}`);
      }
    }
  }

  const toAdd = [typeLabel, breaking ? 'breaking' : null].filter(Boolean);
  if (toAdd.length === 0) {
    return;
  }

  try {
    await github.rest.issues.addLabels({ owner, repo, issue_number, labels: toAdd });
  } catch (error) {
    core.warning(`Failed to add labels [${toAdd.join(', ')}]: ${error.message}`);
  }
}

module.exports = { resolveTypeLabel, hasBreakingChange, label };
