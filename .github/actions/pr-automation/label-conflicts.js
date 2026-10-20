const { BLOCKED_LABEL, ensureLabel, addLabels, removeLabel } = require('./label-pr.js');

const BOT_LOGIN = 'github-actions[bot]';
const MERGEABLE_ATTEMPTS = 5;
const MERGEABLE_DELAY_MS = 3000;

const GET_PR = `query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) { pullRequest(number: $number) { reviewDecision mergeable labels(first: 50) { nodes { name } } } }
}`;

async function fetchPr(github, context, number, delay) {
  for (let attempt = 1; ; attempt++) {
    const { pullRequest } = (await github.graphql(GET_PR, { ...context.repo, number })).repository;
    if (pullRequest.mergeable !== 'UNKNOWN' || attempt === MERGEABLE_ATTEMPTS) {
      return pullRequest;
    }
    await delay(MERGEABLE_DELAY_MS);
  }
}

async function labelledByBot(github, target) {
  const events = await github.paginate(github.rest.issues.listEvents, { ...target, per_page: 100 });
  return events.findLast(({ event, label }) => event === 'labeled' && label.name === BLOCKED_LABEL.name)?.actor.login === BOT_LOGIN;
}

async function labelConflicts({ github, context, core, delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) {
  const { payload, repo, ref } = context;
  const prs = payload.pull_request
    ? [payload.pull_request]
    : await github.paginate(github.rest.pulls.list, { ...repo, state: 'open', base: ref.replace('refs/heads/', ''), per_page: 100 });

  for (const { number } of prs) {
    const pr = await fetchPr(github, context, number, delay);
    const labelled = pr.labels.nodes.some(({ name }) => name === BLOCKED_LABEL.name);
    const target = { ...repo, issue_number: number };

    if (pr.mergeable === 'CONFLICTING' && !labelled) {
      await ensureLabel(github, core, repo, BLOCKED_LABEL);
      await addLabels(github, core, target, [BLOCKED_LABEL.name]);
    } else if (pr.mergeable === 'MERGEABLE' && labelled && pr.reviewDecision !== 'CHANGES_REQUESTED' && await labelledByBot(github, target)) {
      await removeLabel(github, core, target, BLOCKED_LABEL.name);
    }
  }
}

module.exports = { labelConflicts };
