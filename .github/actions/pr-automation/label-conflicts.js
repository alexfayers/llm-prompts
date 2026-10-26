const { BLOCKED_LABEL, ensureLabel, addLabels, removeLabel } = require('./label-pr.js');

const DEPENDENCIES_CONTEXT = 'dependencies';
const BOT_LOGIN = 'github-actions[bot]';
const MERGEABLE_ATTEMPTS = 5;
const MERGEABLE_DELAY_MS = 3000;
const FAILED_CONCLUSIONS = ['failure', 'timed_out'];

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

async function requiredCheckFailed(github, repo, { head, base }) {
  const rules = await github.paginate(github.rest.repos.getBranchRules, { ...repo, branch: base.ref, per_page: 100 });
  const required = rules.filter(({ type }) => type === 'required_status_checks').flatMap(({ parameters }) => parameters.required_status_checks.map(({ context }) => context));
  const runs = required.length ? await github.paginate(github.rest.checks.listForRef, { ...repo, ref: head.sha, per_page: 100 }) : [];
  return runs.some(({ name, conclusion }) => required.includes(name) && FAILED_CONCLUSIONS.includes(conclusion));
}

async function dependenciesPending(github, repo, sha) {
  const { data } = await github.rest.repos.listCommitStatusesForRef({ ...repo, ref: sha });
  return data.find(({ context }) => context === DEPENDENCIES_CONTEXT)?.state === 'pending';
}

function clearsBlock(pr, failed) {
  return pr.mergeable === 'MERGEABLE' && !failed && pr.reviewDecision !== 'CHANGES_REQUESTED';
}

async function labelConflicts({ github, removeClient = github, context, core, delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) {
  const { payload, repo, ref } = context;
  const headSha = payload.workflow_run?.head_sha;
  const prs = payload.pull_request
    ? [payload.pull_request]
    : (await github.paginate(github.rest.pulls.list, { ...repo, state: 'open', base: ref.replace('refs/heads/', ''), per_page: 100 })).filter((pr) => !headSha || pr.head.sha === headSha);

  for (const listed of prs) {
    const { number } = listed;
    const pr = await fetchPr(github, context, number, delay);
    const labelled = pr.labels.nodes.some(({ name }) => name === BLOCKED_LABEL.name);
    const target = { ...repo, issue_number: number };
    const failed = await requiredCheckFailed(github, repo, listed);

    if ((pr.mergeable === 'CONFLICTING' || failed) && !labelled) {
      await ensureLabel(github, core, repo, BLOCKED_LABEL);
      await addLabels(github, core, target, [BLOCKED_LABEL.name]);
    } else if (labelled && clearsBlock(pr, failed) && await labelledByBot(github, target) && !await dependenciesPending(github, repo, listed.head.sha)) {
      await removeLabel(removeClient, core, target, BLOCKED_LABEL.name);
    }
  }
}

module.exports = { labelConflicts, DEPENDENCIES_CONTEXT, dependenciesPending, fetchPr, requiredCheckFailed, clearsBlock };
